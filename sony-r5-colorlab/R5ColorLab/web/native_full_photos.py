"""开发照片整批损失：逐图等权，平均误差显式约束，区域保护沿用冻结容差。"""
import json
from pathlib import Path
import numpy as np
import torch
from native_objective_research import PhotoBank,PhotoProtection,self_rounded
from native_guard_policy import photo_regions
from native_scoring import color_metrics


class FullPhotoBank:
    def __init__(self,rows,*,per_region=256,seed=42):
        xs=[];ts=[];self.spans=[];offset=0;self.reference=None;self.cached=None
        if not rows:raise ValueError('照片整批损失需要开发照片')
        for row in rows:
            if row['role']!='development':raise ValueError('照片整批损失只接受开发集')
            x,t=np.asarray(row['inputs']),np.asarray(row['target'],float)
            if (x.shape!=(len(t),9,3) or t.shape!=(len(x),3) or not len(t)
                    or not np.isfinite(x).all() or not np.isfinite(t).all()
                    or x.min()<0 or x.max()>65535 or t.min()<0 or t.max()>1):
                raise ValueError('开发照片整批输入无效')
            self.spans.append((row['scene'],slice(offset,offset+len(t))));offset+=len(t)
            xs.append(x);ts.append(t)
        self.inputs=np.concatenate(xs);self.target=np.concatenate(ts)
        minimum=min(len(ids) for row in rows for name,ids in photo_regions(row['display']).items() if name!='whole')
        self.regional=PhotoBank(rows,per_region=min(per_region,minimum),seed=seed)
        starts={scene:span.start for scene,span in self.spans}
        self.regional_indices=np.concatenate([np.asarray(g['indices'])+starts[g['scene']] for g in self.regional.groups])

    def errors(self,tools,prediction):
        from stack_objective import de00_squared
        if tuple(prediction.shape)!=self.target.shape:raise ValueError('照片整批预测形状不同')
        if self.cached is None:
            target=tools.tensor(np.floor(self.target*255+.5)/255)
            self.cached=(target,tools.lab(target))
        target,lab=self.cached;p=self_rounded(prediction)
        de=((de00_squared(tools,tools.lab(p),lab)+1e-10).sqrt()-1e-5).clamp(min=0)
        return (p-target).square().mean(1),de

    def means(self,tools,prediction):
        mse,de=self.errors(tools,prediction)
        return torch.stack((torch.stack([(mse[span].mean()+1e-20).sqrt()*255 for _,span in self.spans]).mean(),
            torch.stack([de[span].mean() for _,span in self.spans]).mean()))

    def tensor_loss(self,tools,prediction,de_weight):
        mse,de=self.errors(tools,prediction)
        return torch.stack([mse[span].mean()+de_weight*(de[span].mean()+
            .1*torch.topk(de[span],max(1,int(.05*(span.stop-span.start)))).values.mean())
            for _,span in self.spans]).mean()


class FullPhotoProtection:
    def __init__(self,bank,*,log_path=None,margin=.002,colour_buckets=False):
        if bank.reference is None:raise ValueError('照片约束缺少冻结参考')
        self.bank=bank;self.step=0;self.rho=100.;self.multipliers=None
        metrics=[color_metrics(bank.reference[span],bank.target[span]) for _,span in bank.spans]
        self.limits=np.array([np.mean([m[k] for m in metrics]) for k in ('rgb_rmse','delta_e00_mean')])*(1-margin)
        self.limits=np.maximum(self.limits,1e-6);self.log_path=Path(log_path) if log_path else None
        bank.regional.reference=bank.reference[bank.regional_indices]
        self.regional=PhotoProtection(bank.regional)
        self.colours=ColourBucketProtection(bank) if colour_buckets else None

    def parts(self,tools,prediction):
        self.step+=1;values=self.bank.means(tools,prediction);g=values/tools.tensor(self.limits)-1
        if self.multipliers is None:self.multipliers=torch.zeros_like(g)
        augmented=((self.multipliers+self.rho*g).clamp(min=0).square()-self.multipliers.square()).mean()/(2*self.rho)
        region,stats=self.regional.parts(tools,prediction[tools.tensor(self.bank.regional_indices,True)])
        if self.colours:
            colour,colour_stats=self.colours.parts(tools,prediction)
            region=region+colour;stats.update(colour_stats)
        if self.step%25==0:
            with torch.no_grad():self.multipliers.copy_((self.multipliers+self.rho*g.detach()).clamp(0,10000))
        stats.update(full_photo_rgb_rmse=float(values[0].detach().cpu()),full_photo_delta_e00=float(values[1].detach().cpu()),
            full_photo_max_violation=float(g.detach().max().cpu()),full_photo_rho=self.rho)
        if self.log_path and (self.step==1 or self.step%25==0):
            with self.log_path.open('a') as log:log.write(json.dumps(dict(step=self.step,limits=self.limits.tolist(),**stats))+'\n')
        if self.step%100==0:self.rho=min(10000.,2*self.rho)
        return augmented+region,stats


class ColourBucketProtection:
    def __init__(self,bank,bins=4,minimum=64):
        self.bank=bank;self.step=0;self.rho=100.;self.multipliers=None;self.cached=None
        ids=[]
        for i,(_,span) in enumerate(bank.spans):
            cell=np.clip((bank.reference[span]*bins).astype(int),0,bins-1)
            ids.extend((i*bins**3+cell[:,0]*bins*bins+cell[:,1]*bins+cell[:,2]).tolist())
        self.ids=np.asarray(ids);self.counts=np.bincount(self.ids,minlength=len(bank.spans)*bins**3)
        self.active=self.counts>=minimum
        target=np.floor(bank.target*255+.5);ref=bank.reference*255
        worst=np.maximum((np.floor(ref)-target)**2,(np.ceil(ref)-target)**2).mean(1)
        self.bounds=np.maximum(np.bincount(self.ids,weights=worst,minlength=len(self.counts))/np.maximum(self.counts,1),1e-4)

    def parts(self,tools,prediction):
        self.step+=1
        if self.cached is None:
            self.cached=(tools.tensor(self.ids,True),tools.tensor(self.counts).clamp(min=1),
                tools.tensor(self.active,True).bool(),tools.tensor(self.bounds),
                tools.tensor(np.floor(self.bank.target*255+.5)))
        ids,counts,active,bounds,target=self.cached
        mse=(self_rounded(prediction)*255-target).square().mean(1)
        sums=torch.zeros_like(counts).scatter_add(0,ids,mse)
        g=(sums/counts/bounds-1)[active]
        if not len(g):return prediction.sum()*0,dict(colour_bucket_active=0,colour_bucket_max_violation=0.)
        if self.multipliers is None:self.multipliers=torch.zeros_like(g)
        terms=((self.multipliers+self.rho*g).clamp(min=0).square()-self.multipliers.square())/(2*self.rho)
        loss=torch.topk(terms,max(1,int(.2*len(terms)))).values.mean()
        if self.step%25==0:
            with torch.no_grad():self.multipliers.copy_((self.multipliers+self.rho*g.detach()).clamp(0,10000))
        if self.step%100==0:self.rho=min(10000.,2*self.rho)
        return loss,dict(colour_bucket_active=int((g.detach()>0).sum().cpu()),colour_bucket_max_violation=float(g.detach().max().cpu()))
