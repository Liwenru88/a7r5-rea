"""四组单款离线实验；不修改正式训练入口、工程或原始配方。"""
import copy
import struct

import numpy as np
import torch
from torch import nn

import core
from apple_gpu import SmoothGPU
from concave_gamma import ConcaveGamma
from edit_parameter_context import ParameterContext
from fit_anchor_native import SmoothNative
from fit_bin_joint import grid_from
from gpu_color import paired_tensor
from gpu_tensor import TensorTools
from measured_response import get
from native_gamma import CP_AXIS, EDIT_AXIS
from native_rounding import RoundedGPU

POLICY='native-four-arm-experiment/2'
ARM_SPECS={
    'A':dict(name='当前129点机制',kind='concave',corrected=False,normalized=False,new_loss=False,neural=False),
    'B':dict(name='动态整数前向与归一化',kind='concave',corrected=True,normalized=True,new_loss=False,neural=False),
    'C':dict(name='目标一致损失与约束',kind='monotone',corrected=True,normalized=True,new_loss=True,neural=False),
    'D':dict(name='四个神经参数头',kind='monotone',corrected=True,normalized=True,new_loss=True,neural=True),
}


def ste(value, hard):
    return value+(hard-value).detach()


def metric_failures(candidate, reference):
    keys=('rgb_rmse','delta_e00_mean','delta_e00_p95','gray_rmse')
    if any(not np.isfinite(candidate.get(key,np.nan)) for key in keys):
        return ['nonfinite_or_missing']
    if any(not np.isfinite(reference.get(key,np.nan)) for key in keys):
        raise ValueError('基准指标无效')
    errors=[key for key in keys[:2] if candidate[key]>=reference[key]-1e-10]
    errors.extend(key for key in keys[2:] if candidate[key]>reference[key]+1e-10)
    return errors


def transition_failures(before,after,margins):
    from calibrated_guard import ramp_report
    failures=ramp_report(before,after,margins)[1]
    for axis,start in before.items():
        end=after[axis]
        for key,func in (('p95',lambda x:np.percentile(x,95)),('max',np.max)):
            if not np.isfinite(end).all() or func(end)>func(start)+1e-10:
                failures.append(f'strict:{axis}:{key}')
    return failures


class Space:
    """1448个搜索坐标；硬化只使用固定BIN刻度，不学习量化步长。"""
    def __init__(self,context,seed,*,kind='monotone',device='mps',dtype=None):
        if kind not in ('concave','monotone'):
            raise ValueError('未知Gamma参数化')
        if any(any(row) for row in seed['cc1_delta'][1:]) or any(row!=seed['block13'][0] for row in seed['block13'][1:]):
            raise ValueError('单款首轮只训练共享照明参数的B端点')
        self.context,self.seed,self.kind=context,copy.deepcopy(seed),kind
        self.tools=TensorTools(device,dtype)
        self.tensor=self.tools.tensor
        self.device,self.dtype=self.tools.device,self.tools.dtype
        self.shape=ConcaveGamma(EDIT_AXIS,control_count=129,parameter_count=129)
        model=context.build(**core.slot_native_parameters(context,seed))
        self.cc_remainder=np.asarray(seed['cc1_delta'][0],int)%4
        cc=np.asarray(seed['cc1_delta'][0],int)//4
        matrix=np.asarray(struct.unpack_from('<96f',model.config,0x28))*1024
        q=np.asarray(seed['gamma_native_129'],float)
        if kind=='concave':
            gamma=self.shape.encode(q/8)
        else:
            slopes=np.maximum(np.diff(q)/np.diff(CP_AXIS),1e-8)
            gamma=np.r_[np.where(slopes>30,slopes,np.log(np.expm1(np.minimum(slopes,30)))),q[-1]]
        self.initial=np.r_[cc,matrix,gamma,grid_from(seed).ravel()].astype(float)
        if self.initial.shape!=(1448,):
            raise ValueError('实验搜索坐标数量不符')
        self.legacy_scales=np.r_[np.full(4,25.6),np.full(4,12.8),np.full(96,512.),
            np.full(129,.5),np.full(1215,32.)]
        if kind=='monotone':self.legacy_scales[232]=20000.

    def gamma(self,values):
        if self.kind=='concave':
            return self.shape.tensor_curve(torch,values)*8
        widths=self.tensor(np.diff(CP_AXIS))
        increments=torch.nn.functional.softplus(values[:128].clamp(-30,50))*widths
        endpoint=values[128].clamp(1,131071)
        return torch.cat((values.new_zeros(1),increments.cumsum(0)))*endpoint/increments.sum()

    def decode(self,vector,*,quantized=True):
        if vector.shape!=(1448,):raise ValueError('实验向量维度不符')
        low=vector.new_tensor([-256.]*4+[0.]*4)
        cc=torch.minimum(torch.maximum(vector[:8],low),vector.new_full((8,),255.))
        m=vector[8:104].clamp(-8191,8191)
        gamma=self.gamma(vector[104:233])
        grid=vector[233:].reshape(405,3).clamp(-64,63)
        if quantized:
            cc=ste(cc,cc.round())
            magnitude=torch.where(m<0,2*((m.abs()-1)/2).round()+1,m.round())
            hard=torch.where(m.abs()<.5,0,torch.where(m<0,-magnitude,magnitude))
            m=ste(m,hard)
            if self.kind=='concave':
                ordinates=self.shape.quantize_raw(gamma.detach().cpu().numpy()*2)//2
                gamma=ste(gamma,self.tensor(ordinates))
            else:
                gamma=ste(gamma,torch.cummax(gamma.round(),0).values.clamp(0,131071))
            grid=ste(grid,grid.round())
        ordered=torch.cat((cc[[3,0,1,2]]/256,cc[[7,4,5,6]]/64))
        native=torch.cat((ordered,m/1024,vector.new_zeros(129)))
        return dict(vector=native,cc=cc,matrix=m,gamma=gamma/8,grid=grid)

    def entry(self,vector):
        with torch.no_grad():
            value=self.decode(vector,quantized=True)
            convert=lambda x:np.rint(x.detach().cpu().numpy()).astype(np.int64)
            entry=copy.deepcopy(self.seed)
            entry['cc1_delta'][0]=(4*convert(value['cc'])+self.cc_remainder).tolist()
            matrix=convert(value['matrix'])
            storage=np.where(matrix<0,matrix-1,matrix).reshape(6,16).T.tolist()
            entry['block13']=[copy.deepcopy(storage) for _ in range(3)]
            entry['gamma_native_129']=convert(value['gamma']*8).tolist()
            entry['grid_5x9x9']=dict(coefficients=convert(value['grid']).T.reshape(3,5,9,9).tolist())
        return core.compiler.unpack(core.compiler.pack(core.compiler.config([entry],5)))['entries'][0]


class FourHeads(nn.Module):
    """共享主干与四个坐标参数头；独立残差保留全部原生自由度。"""
    def __init__(self,size=1448,*,device='mps',dtype=None,seed=42):
        super().__init__()
        if size!=1448:raise ValueError('四头模型需要1448个搜索坐标')
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.latent=nn.Parameter(torch.linspace(-1,1,32))
            self.trunk=nn.Sequential(nn.Linear(32,64),nn.SiLU(),nn.Linear(64,64),nn.SiLU())
            def head(width,hidden,output):
                value=nn.Sequential(nn.Linear(width,hidden),nn.SiLU(),nn.Linear(hidden,32),nn.SiLU(),nn.Linear(32,output))
                nn.init.zeros_(value[-1].weight);nn.init.zeros_(value[-1].bias)
                return value
            self.cc_head=head(64,32,8)
            self.gamma_head=head(66,64,1)
            self.matrix_head=head(66,64,6)
            self.grid_head=head(67,64,3)
        self.residual=nn.Parameter(torch.zeros(size))
        gamma_x=np.r_[((CP_AXIS[:-1]+CP_AXIS[1:])/2)/65535,1.]
        self.register_buffer('gamma_coords',torch.tensor(np.column_stack((gamma_x,np.r_[np.zeros(128),1.])),dtype=torch.float32))
        angle=np.arange(16)*2*np.pi/16
        self.register_buffer('hue_coords',torch.tensor(np.column_stack((np.sin(angle),np.cos(angle))),dtype=torch.float32))
        axes=np.meshgrid(np.linspace(-1,1,5),np.linspace(-1,1,9),np.linspace(-1,1,9),indexing='ij')
        self.register_buffer('grid_coords',torch.tensor(np.stack(axes,-1).reshape(405,3),dtype=torch.float32))
        self.to(device=device,dtype=torch.float32 if dtype is None else dtype)

    def neural_delta(self):
        features=self.trunk(self.latent)
        cc=self.cc_head(features)
        gamma=self.gamma_head(torch.cat((features.expand(129,-1),self.gamma_coords),dim=1)).flatten()
        matrix=self.matrix_head(torch.cat((features.expand(16,-1),self.hue_coords),dim=1)).T.flatten()
        grid=self.grid_head(torch.cat((features.expand(405,-1),self.grid_coords),dim=1)).flatten()
        return .2*torch.cat((cc,matrix,gamma,grid))

    def forward(self):
        return self.residual+self.neural_delta()


class Renderer:
    """CPU同参数整数前向值，MPS代理梯度；对照A保留初始位置偏移。"""
    def __init__(self,space,inputs,response,*,allow_nonflat=False):
        self.space,self.inputs,self.response=space,np.asarray(inputs),response
        self.tools=space.tools
        flat=np.array_equal(self.inputs,np.broadcast_to(self.inputs[:,4:5],self.inputs.shape))
        if not flat and not allow_nonflat:
            raise ValueError('本轮只接受已验证的平坦九点色卡/渐变输入')
        initial=space.entry(space.tensor(space.initial))
        model=space.context.build(**core.slot_native_parameters(space.context,initial))
        smooth=SmoothNative(ParameterContext(model),self.inputs)
        self.gpu=RoundedGPU(smooth,device=space.device,dtype=space.dtype,compact_flat=flat)
        self.initial_controls=model.chroma_controls()
        self.gain=model._h(0x18ee)/64
        exposure=struct.unpack_from('<i',model.runtime,0xc)[0]/300
        if exposure!=0:
            raise ValueError('首轮实验只验证了中性曝光设置上下文')
        threshold=model._rawh(0xf06)
        self.query=float(struct.unpack_from('<h',model.runtime,0x89962+2*min(threshold,16383))[0])
        self.low_ratio=model._rawh(0xf0e)/threshold if threshold else 0.
        self.calls=0
        with torch.no_grad():
            decoded=space.decode(space.tensor(space.initial),quantized=False)
            approx=self.soft_native(decoded,dynamic=False)
            _,_,native=self.exact_entry(initial)
            self.offset=self.tools.tensor(native)-approx

    def exact_entry(self,entry):
        model=self.space.context.build(**core.slot_native_parameters(self.space.context,entry))
        parts=[]
        for start in range(0,len(self.inputs),8192):
            parts.append(model.color_only(self.inputs[start:start+8192])[:,2:7].mean(1)/16383)
        native=np.concatenate(parts)
        self.calls+=1
        return get(self.response).predict_cpu(native,grid_from(entry)),model,native

    def dynamic_controls(self,gamma,actual=None):
        axis=self.gpu.axis
        query=gamma.new_tensor(self.query)
        right=torch.searchsorted(gamma.detach().contiguous(),query).clamp(1,128)
        left=right-1
        fraction=((query-gamma[left])/(gamma[right]-gamma[left]).clamp(min=1e-4)).clamp(0,1)
        inverse=axis[left]*(1-fraction)+axis[right]*fraction
        inverse=torch.where(query>=gamma[-1],axis[-1],inverse)
        source=(inverse*self.gain).clamp(0,32767)
        main=self.gpu.interp(source,axis,gamma)
        index=main.clamp(0,len(self.gpu.ytable)-1)
        lo=index.long();hi=(lo+1).clamp(max=len(self.gpu.ytable)-1)
        cutoff=self.gpu.ytable[lo]*(1-(index-lo))+self.gpu.ytable[hi]*(index-lo)
        low=cutoff*self.low_ratio
        if actual is not None:
            cutoff=ste(cutoff,cutoff.new_tensor(actual['high_cutoff']))
            low=ste(low,low.new_tensor(actual['low_cutoff']))
        return dict(self.initial_controls,high_cutoff=cutoff,low_cutoff=low)

    def soft_native(self,decoded,*,dynamic=True,actual=None):
        self.gpu.override_gamma=decoded['gamma']
        self.gpu.chroma=self.dynamic_controls(decoded['gamma'],actual) if dynamic else self.initial_controls
        return self.gpu.render(decoded['vector'])/16383

    def evaluate(self,vector,*,corrected=True,dynamic=True):
        decoded=self.space.decode(vector,quantized=corrected)
        if corrected:
            entry=self.space.entry(vector)
            expected,model,_=self.exact_entry(entry)
            controls=model.chroma_controls()
            native=self.soft_native(decoded,dynamic=dynamic,actual=controls)
            predicted=paired_tensor(self.tools,native,decoded['grid'],self.response)
            error=float(np.max(np.abs(predicted.detach().cpu().numpy()-expected)))
            predicted=ste(predicted,self.tools.tensor(expected))
        else:
            controls=self.initial_controls
            native=(self.soft_native(decoded,dynamic=False)+self.offset).clamp(0,1)
            predicted=paired_tensor(self.tools,native,decoded['grid'],self.response)
            error=None
        high=self.gpu.chroma['high_cutoff']
        audit=dict(exact_corrected=corrected,controls=controls,
                   surrogate_high_cutoff=float(high.detach().cpu()) if torch.is_tensor(high) else float(high),
                   surrogate_max_rgb_difference=error)
        return predicted,audit


def sensitivity_scales(space,renderer,*,probes=6,seed=42):
    """训练输入上的随机VJP估计；不读取验证/测试目标。"""
    rng=np.random.default_rng(seed)
    squared=np.zeros(1448)
    vector=space.tensor(space.initial).requires_grad_(True)
    for _ in range(probes):
        prediction=renderer.soft_native(space.decode(vector,quantized=False),dynamic=True)
        prediction=paired_tensor(space.tools,prediction,space.decode(vector,quantized=False)['grid'],renderer.response)
        noise=space.tensor(rng.choice((-1.,1.),prediction.shape))/np.sqrt(prediction.numel())
        gradient=torch.autograd.grad((prediction*noise).sum(),vector)[0]
        squared+=gradient.detach().cpu().numpy().astype(float)**2
    sensitivity=np.sqrt(squared/probes)
    lower=np.r_[np.ones(8),np.full(96,8.),np.full(129,.1),np.ones(1215)]
    upper=np.r_[np.full(4,256.),np.full(4,128.),np.full(96,2048.),np.full(129,4.),np.full(1215,64.)]
    if space.kind=='monotone':lower[232]=128.;upper[232]=32768.
    active=sensitivity>1e-8
    scales=np.clip(np.where(active,.02/np.maximum(sensitivity,1e-8),space.legacy_scales),lower,upper)
    return scales,dict(probes=probes,seed=seed,inactive=int((~active).sum()),
        scale_min=float(scales.min()),scale_max=float(scales.max()),
        sensitivity_min=float(sensitivity.min()),sensitivity_max=float(sensitivity.max()))


def quantile95(values):
    values=values.flatten()
    position=(values.numel()-1)*.95
    lower=int(np.floor(position));fraction=position-lower
    top=torch.topk(values,values.numel()-lower).values
    return top[-1] if not fraction else (1-fraction)*top[-1]+fraction*top[-2]


def local_violations(candidate,reference,peak,local):
    """按相同路径位置保护尖峰与连续三点；整体最大值下降不能抵消局部恶化。"""
    increase=candidate-reference
    spike=((increase-peak)/max(peak,.005)).clamp(min=0).max()
    runs=torch.minimum(torch.minimum(increase[:,:-2],increase[:,1:-1]),increase[:,2:])
    cluster=((runs-local)/max(local,.005)).clamp(min=0).max()
    return spike,cluster


class Objective:
    """训练整批目标与独立训练渐变；所有验收阈值先从旧配方冻结。"""
    def __init__(self,space,target,gray,bank,reference,*,new_loss,response,margins=None):
        from stack_objective import de00_squared
        from grid_regularization import get_penalty
        self.space,self.tools,self.bank=space,space.tools,bank
        self.new_loss,self.ntrain=new_loss,len(target)
        self.target=self.tools.tensor(target)
        self.gray=self.tools.tensor(np.flatnonzero(gray),True)
        if len(gray)!=len(target) or not np.any(gray) or len(reference)!=len(target)+len(bank.rgb):
            raise ValueError('损失只接受完整训练集、训练灰阶和独立渐变')
        self.target8=torch.floor(self.target.clamp(0,1)*255+.5)/255
        self.target_lab=self.tools.lab(self.target8 if new_loss else self.target)
        self.reference=self.tools.tensor(reference)
        with torch.no_grad():
            ref= self.rounded(self.reference)
            de=(de00_squared(self.tools,self.tools.lab(ref[:self.ntrain]),self.tools.lab(self.target8))+1e-12).sqrt()
            self.de_weight=.35*.0001*2*float(de.mean().cpu())
            self.gray_limit=((ref[:self.ntrain][self.gray]-self.target8[self.gray]).square().mean()).clamp(min=1e-8)
            self.p95_limit=quantile95(de).clamp(min=.05)
            self.reference_jumps=[row.detach() for row in self.ramp_jumps(ref[self.ntrain:])]
            self.ramp_limits=[(quantile95(j),j.max()) for j in self.reference_jumps]
        from integer_grid import PROBE_AXES
        if margins is None:
            from calibrated_guard import calibrate
            margins=calibrate(bank,np.asarray(reference)[len(target):],[],allow_no_photos=True)
        self.local_limits=[(margins['axes'][axis]['peak']/100,margins['axes'][axis]['local']/100) for axis in PROBE_AXES]
        self.multipliers=torch.ones(2+(4 if new_loss else 2)*len(self.ramp_limits),device=space.device,dtype=space.dtype)*.001
        self.gram=self.tools.tensor(get_penalty(response).dense_gram)
        self.config=space.context.build(**core.slot_native_parameters(space.context,space.seed)).config

    @staticmethod
    def rounded(value):
        return ste(value,torch.floor(value.clamp(0,1)*255+.5)/255)

    def ramp_jumps(self,rgb):
        from integer_grid import PROBE_AXES
        rows=[]
        for axis in PROBE_AXES:
            span,shape=self.bank.span(axis)
            lab=self.tools.lab(rgb[span]).reshape(*shape,3)[...,1:]/100
            curvature=lab[:,2:]-2*lab[:,1:-1]+lab[:,:-2]
            jumps=(curvature.square().sum(-1)+1e-12).sqrt()
            rows.append(jumps)
        return rows

    def __call__(self,prediction,decoded):
        from stack_objective import de00_squared
        from parameter_smoothing import native_rows_tensor
        p=self.rounded(prediction) if self.new_loss else prediction
        target=self.target8 if self.new_loss else self.target
        error=(p[:self.ntrain]-target).square().mean()
        de2=de00_squared(self.tools,self.tools.lab(p[:self.ntrain]),self.target_lab)
        de=(de2+1e-10).sqrt()
        if self.new_loss:
            tail=torch.topk(de,max(1,int(np.ceil(.05*self.ntrain)))).values.mean()
            data=error+self.de_weight*(de.mean()+.1*tail)
        else:
            data=error+.35*.0001*de2.mean()
        gray=(p[:self.ntrain][self.gray]-target[self.gray]).square().mean()
        constraints=[(gray/self.gray_limit-1).clamp(min=0),
                     (quantile95(de)/self.p95_limit-1).clamp(min=0)]
        for jumps,limits,reference,local in zip(self.ramp_jumps(p[self.ntrain:]),self.ramp_limits,self.reference_jumps,self.local_limits):
            current=quantile95(jumps),jumps.max()
            constraints.extend((v/limit.clamp(min=.0005)-1).clamp(min=0) for v,limit in zip(current,limits))
            if self.new_loss:
                constraints.extend(local_violations(jumps,reference,*local))
        violations=torch.stack(constraints).clamp(max=100)
        guard=(self.multipliers*(violations+.5*violations.square())).sum()
        grid=decoded['grid'].flatten()
        regularization=.007*(grid@(self.gram@grid))
        rows=native_rows_tensor(self.tools,decoded['matrix']/1024,decoded['gamma']*16,
                               EDIT_AXIS,30,cc1=decoded['vector'][:8],config=self.config)
        regularization=regularization+rows.square().sum()
        loss=data+regularization+guard
        self.last_violations=violations.detach()
        stats=dict(training_samples=self.ntrain,data=float(data.detach().cpu()),
            constraint=float(guard.detach().cpu()),regularization=float(regularization.detach().cpu()),
            max_violation=float(violations.max().detach().cpu()),
            violations=violations.detach().cpu().tolist(),multipliers=self.multipliers.detach().cpu().tolist(),
            rgb_rmse=float(error.detach().sqrt().cpu())*255,
            delta_e00_mean=float(de.mean().detach().cpu()),gray_rmse=float(gray.detach().sqrt().cpu())*255)
        return loss,stats

    def adapt(self):
        if self.new_loss:
            self.multipliers=(self.multipliers+.0002*self.last_violations).clamp(max=.1)
