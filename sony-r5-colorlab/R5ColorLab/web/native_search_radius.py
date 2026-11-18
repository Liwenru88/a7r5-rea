"""离线C研究：可行且继续改善时扩大分组半径，保留当前物理配方。"""
import torch

GROUPS=(('cc1',0,8),('hue',8,104),('gamma',104,233),('grid',233,1448))


class SearchRadius:
    def __init__(self,reference,*,adaptive=False,confirmations=1):
        if reference.shape!=(1448,):raise ValueError('搜索空间必须为1448维')
        if type(confirmations) is not int or confirmations<1:raise ValueError('连续确认次数必须为正整数')
        self.values=torch.full_like(reference,.25)
        self.adaptive=adaptive
        self.confirmations=confirmations;self.pending={name:0 for name,_,_ in GROUPS}

    def delta(self,offset):return self.values*torch.tanh(offset/self.values)

    def expand(self,offset,optimizer,*,feasible,improved):
        if not self.adaptive or not feasible or not improved:
            self.pending=dict.fromkeys(self.pending,0)
            return []
        events=[]
        with torch.no_grad():
            delta=self.delta(offset).clone()
            for name,start,end in GROUPS:
                at=slice(start,end);old=self.values[at].clone()
                fraction=float(((delta[at]/old).abs()>=.85).float().mean().cpu())
                if fraction<.1 or float(old.max().cpu())>=.5:
                    self.pending[name]=0;continue
                self.pending[name]+=1
                if self.pending[name]<self.confirmations:continue
                new=(old*1.5).clamp(max=.5)
                ratio=(1-(delta[at]/new).square())/(1-(delta[at]/old).square()).clamp(min=1e-7)
                offset[at]=new*torch.atanh((delta[at]/new).clamp(-.999999,.999999))
                self.values[at]=new
                # 更换坐标后相应变换Adam矩估计；配方与已用更新步幅保持不变。
                state=optimizer.state.get(offset,{})
                for key,power in (('exp_avg',1),('exp_avg_sq',2),('max_exp_avg_sq',2)):
                    if key in state:state[key][at]*=ratio.pow(power)
                self.pending[name]=0
                events.append(dict(group=name,old=float(old[0].cpu()),new=float(new[0].cpu()),saturated_fraction=fraction))
        return events
