"""Fixed-Hybrid NC objective: exact DE00, hue direction and target derivatives.

Only the isolated 4188 experiment imports this module. Loss units everywhere
are squared eight-bit codes, divided by 255**2 for differentiable evaluation.
"""
import numpy as np
from hue_direction import HueDirectionBank
from multiround import cpu_cost
from perceptual import to_lab


def de00_squared(tools, first, second):
    """CIEDE2000 squared with finite zero/gray subgradients, no final sqrt."""
    t = tools.torch
    l1, a1, b1 = first.unbind(1)
    l2, a2, b2 = second.unbind(1)
    norm = lambda a, b: t.sqrt((a*a+b*b).clamp(min=1e-20))
    c1, c2 = norm(a1,b1), norm(a2,b2)
    cm = (c1+c2)/2
    g = .5*(1-t.sqrt((cm**7/(cm**7+25**7)).clamp(min=1e-30)))
    ap1, ap2 = (1+g)*a1, (1+g)*a2
    cp1, cp2 = norm(ap1,b1), norm(ap2,b2)
    def hue(a,b,c):
        # atan2(0,0) is undefined even in an inactive where branch.
        gray = c <= 1.01e-10
        aa = t.where(gray,t.ones_like(a),a)
        bb = t.where(gray,t.zeros_like(b),b)
        return t.remainder(t.atan2(bb,aa)*(180/np.pi),360)
    hp1, hp2 = hue(ap1,b1,cp1), hue(ap2,b2,cp2)
    neutral = (cp1 <= 1.01e-10) | (cp2 <= 1.01e-10)
    dh = hp2-hp1
    dh = t.where(neutral,0,t.where(dh>180,dh-360,t.where(dh < -180,dh+360,dh)))
    d_h = 2*t.sqrt((cp1*cp2).clamp(min=1e-20))*t.sin(dh*(np.pi/360))
    lm, cm = (l1+l2)/2,(cp1+cp2)/2
    hm = t.where(neutral,hp1+hp2,t.where(t.abs(hp1-hp2)<=180,(hp1+hp2)/2,
        t.where(hp1+hp2<360,(hp1+hp2+360)/2,(hp1+hp2-360)/2)))
    rad = np.pi/180
    term = 1-.17*t.cos((hm-30)*rad)+.24*t.cos(2*hm*rad)
    term = term+.32*t.cos((3*hm+6)*rad)-.20*t.cos((4*hm-63)*rad)
    sl = 1+.015*(lm-50)**2/t.sqrt(20+(lm-50)**2)
    sc, sh = 1+.045*cm,1+.015*cm*term
    rt = -2*t.sqrt((cm**7/(cm**7+25**7)).clamp(min=1e-30))*t.sin(60*t.exp(-((hm-275)/25)**2)*rad)
    dl, dc = (l2-l1)/sl,(cp2-cp1)/sc
    d_h = d_h/sh
    return (dl**2+dc**2+d_h**2+rt*dc*d_h).clamp(min=0)


def data_loss(tools, prediction, target, mass):
    p,t = prediction.clamp(0,1),target.clamp(0,1)
    rows = (p-t).square().mean(dim=1)
    rows = rows+.35*(2.55/255)**2*de00_squared(tools,tools.lab(p),tools.lab(t))
    return (rows*mass).sum()


class TargetDerivatives:
    """Real TRAIN-ray finite differences, including target plateaus.

    Lab-vector supervision remains defined near the gray axis, unlike hue.
    First derivatives use actual design-V interval lengths. No synthetic
    target labels, validation targets or test targets are used here.
    """
    def __init__(self, design, target, split, kind, amount=.02):
        bank = HueDirectionBank(design,target,split,kind,
            minimum_saturation=0,minimum_lightness=0,minimum_target_step_degrees=0)
        self.source_indices = bank.source_indices
        self.edges,self.mass = bank.edges,bank.mass
        self.dv = np.diff(np.max(np.asarray(design)[self.source_indices][self.edges],axis=2),axis=1)[:,0]
        if np.any(self.dv<=0):raise ValueError('Target derivative edges need increasing V')
        lab=to_lab(np.clip(np.asarray(target)[self.source_indices],0,1)*255)/100
        self.desired=(lab[self.edges[:,1]]-lab[self.edges[:,0]])/self.dv[:,None]
        self.amount=float(amount)

    def cpu_cost(self,prediction):
        lab=to_lab(np.clip(prediction,0,1)*255)/100
        error=(lab[self.edges[:,1]]-lab[self.edges[:,0]])/self.dv[:,None]-self.desired
        # Pseudo-Huber: quadratic near zero, robust to uncertain finite differences.
        rows=.05**2*(np.sqrt(1+(error/.05)**2)-1).sum(axis=1)
        return float(rows@self.mass)*self.amount*255**2

    def tensor_loss(self,tools,prediction):
        edges=tools.tensor(self.edges,True)
        lab=tools.lab(prediction.clamp(0,1))/100
        error=(lab[edges[:,1]]-lab[edges[:,0]])/tools.tensor(self.dv)[:,None]-tools.tensor(self.desired)
        rows=.05**2*(tools.torch.sqrt(1+(error/.05)**2)-1).sum(dim=1)
        return (rows*tools.tensor(self.mass)).sum()*self.amount


class Scorer:
    def __init__(self,model,target,train,weights,direction,derivatives):
        self.model,self.target,self.train=model,np.asarray(target),np.asarray(train)
        self.weights=np.asarray(weights)
        self.direction,self.derivatives=direction,derivatives
        lookup={int(row):i for i,row in enumerate(self.train)}
        self.direction_ids=np.asarray([lookup[int(i)]for i in direction.source_indices])
        self.derivative_ids=np.asarray([lookup[int(i)]for i in derivatives.source_indices])

    def score(self,base,grid):
        p=self.model.predict_cpu(np.asarray(base)[self.train],grid)
        data=cpu_cost(p,self.target[self.train],self.weights)
        direction=self.direction.cost(p[self.direction_ids],30)
        derivatives=self.derivatives.cpu_cost(p[self.derivative_ids])
        return dict(data=data,direction=direction,derivatives=derivatives,
            total=data+direction+derivatives)


class GridRenderer:
    def __init__(self,tools,base,model):
        from gpu_tensor import stencil_tensor
        self.tools=tools
        self.base=tools.tensor(base)
        self.ids,self.mass=stencil_tensor(tools,model.coordinates_tensor(tools,self.base))
        self.response=tools.tensor(model.response(base))

    def __call__(self,grid):
        delta=(grid[self.ids]*self.mass[:,:,None]).sum(dim=1)
        return (self.base+self.tools.torch.einsum('nc,nco->no',delta,self.response)).clamp(0,1)


class GridObjective:
    def __init__(self,tools,base,scorer):
        self.tools,self.scorer=tools,scorer
        # Render only TRAIN. Keep an index map for the two real-ray banks.
        self.rows=np.asarray(scorer.train)
        lookup={int(row):i for i,row in enumerate(self.rows)}
        self.direction_ids=tools.tensor([lookup[int(i)]for i in scorer.direction.source_indices],True)
        self.derivative_ids=tools.tensor([lookup[int(i)]for i in scorer.derivatives.source_indices],True)
        self.renderer=GridRenderer(tools,np.asarray(base)[self.rows],scorer.model)
        self.target=tools.tensor(scorer.target[self.rows])
        self.mass=tools.tensor(scorer.weights/scorer.weights.sum())

    def loss(self,grid):
        p=self.renderer(grid)
        return (data_loss(self.tools,p,self.target,self.mass)
            +self.scorer.direction.tensor_loss(self.tools,p[self.direction_ids],30)
            +self.scorer.derivatives.tensor_loss(self.tools,p[self.derivative_ids]))


def acceptable(before,after):
    """All proposals pass actual packed CPU64 training acceptance."""
    return after['total']<before['total']-1e-10 and after['data']<=before['data']+1e-9


def optimize_grid(tools,base,grid,scorer,progress,evaluations=180):
    from scipy.optimize import minimize
    from residual_grid import pack,unpack
    objective=GridObjective(tools,base,scorer)
    seed=unpack(pack(grid));before=scorer.score(base,seed)
    initial=tools.tensor(seed).requires_grad_(True)
    expected=before['total']/255**2
    actual=float(objective.loss(initial).detach().cpu())
    if abs(actual-expected)>max(2e-7,abs(expected)*2e-3):
        raise ValueError(f'Stack grid CPU/GPU loss mismatch {actual} vs {expected}')
    calls=0;best_loss=before['total']
    def fg(v):
        nonlocal calls,best_loss
        table=tools.tensor(v.reshape(405,3)).requires_grad_(True)
        loss=objective.loss(table)*255**2
        loss.backward();calls+=1
        value=float(loss.detach().cpu());gradient=table.grad.detach().cpu().numpy().astype(float).ravel()
        if not np.isfinite(value) or not np.isfinite(gradient).all():raise ValueError('Nonfinite stack grid gradient')
        best_loss=min(best_loss,value)
        if calls==1 or calls%10==0 or calls==evaluations:
            progress(stage='叠加：精确RGB/ΔE00＋同向30＋目标导数',evaluations=calls,max_evaluations=evaluations,
                loss_sample=('MPS 叠加网格 L-BFGS-B',calls,value,best_loss))
        return value,gradient
    result=minimize(fg,seed.astype(float).ravel(),jac=True,method='L-BFGS-B',bounds=[(-64,63)]*1215,
        options=dict(maxfun=evaluations,maxiter=evaluations,maxls=20,ftol=1e-10,gtol=1e-6))
    best=seed;score=before
    for alpha in (1.,.75,.5,.25):
        candidate=unpack(pack(np.clip(np.rint(seed+alpha*(result.x.reshape(405,3)-seed)),-64,63).astype(np.int8)))
        proposed=scorer.score(base,candidate)
        if acceptable(score,proposed):best,score=candidate,proposed
    return best,result.x.reshape(405,3),dict(before=before,after=score,calls=calls,
        solver_message=str(result.message),loss_units='squared 8-bit',cpu_gpu_gate=dict(cpu=expected,gpu=actual))


def optimize_rounding(tools,base,grid,continuous,scorer,progress,steps=80,block_budget=64):
    """Task-aware floor/ceil relaxation, followed by joint RGB/node proposals.

    This is an AdaRound-inspired adaptation, not an implementation or claim of
    the original paper's regularizer/benchmark. Every acceptance is exact.
    """
    from residual_grid import pack,unpack
    t=tools.torch;objective=GridObjective(tools,base,scorer)
    low=np.clip(np.floor(continuous),-64,63)
    high=np.clip(low+1,-64,63)
    fraction=np.clip(continuous-low,.01,.99)
    logits=tools.tensor(np.log(fraction/(1-fraction))).requires_grad_(True)
    optimizer=t.optim.Adam([logits],lr=.12)
    lo,span=tools.tensor(low),tools.tensor(high-low)
    best=unpack(pack(grid));before=score=scorer.score(base,best)
    accepted=0
    for step in range(steps):
        optimizer.zero_grad();prob=t.sigmoid(logits)
        table=lo+span*prob
        # Annealed binary pressure, small relative to the task objective.
        loss=objective.loss(table)*255**2+.001*(step/max(steps-1,1))*t.mean(prob*(1-prob))
        loss.backward()
        if not t.isfinite(logits.grad).all():raise ValueError('Nonfinite adaptive rounding gradient')
        optimizer.step()
        if step%10==9 or step==steps-1:
            candidate=unpack(pack((lo+span*(t.sigmoid(logits)>=.5)).detach().cpu().numpy().astype(np.int8)))
            proposed=scorer.score(base,candidate)
            if acceptable(score,proposed):best,score=candidate,proposed;accepted+=1
            progress(stage='叠加：任务感知整数舍入',evaluations=step+1,max_evaluations=steps)
    # Gradient-ranked bounded joint moves. Exact CPU scoring follows every move.
    variable=tools.tensor(best).requires_grad_(True)
    (objective.loss(variable)*255**2).backward()
    gradient=variable.grad.detach().cpu().numpy()
    nodes=np.argsort(np.linalg.norm(gradient,axis=1))[::-1][:max(1,block_budget//2)]
    trials=0
    for node in nodes:
        direction=-np.sign(gradient[node]).astype(int)
        for mode in ('rgb','adjacent'):
            candidate=best.astype(int).copy()
            candidate[node]+=direction
            if mode=='adjacent':
                # Actual neighbor in the innermost lattice axis, not wraparound.
                neighbor=node+1 if node%9<8 else node-1
                candidate[neighbor]+=direction
            candidate=unpack(pack(np.clip(candidate,-64,63).astype(np.int8)))
            proposed=scorer.score(base,candidate);trials+=1
            if acceptable(score,proposed):best,score=candidate,proposed;accepted+=1
            if trials%8==0:progress(stage='叠加：多系数联合整数搜索',evaluations=trials,max_evaluations=block_budget)
            if trials>=block_budget:break
        if trials>=block_budget:break
    return best,dict(before=before,after=score,adaptive_steps=steps,block_trials=trials,accepted=accepted,
        cpu64_packed_acceptance=True,train_data_non_regression=True)
