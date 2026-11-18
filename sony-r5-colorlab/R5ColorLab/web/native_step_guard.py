"""真实整数过渡的步后接受检查；完全拒绝时恢复参数和Adam状态。"""
import torch


def backtrack_update(parameters,old,optimizer,optimizer_before,evaluate):
    with torch.no_grad():proposed=[p.clone() for p in parameters]
    attempts=[]
    for fraction in (1.,.5,.25,.125):
        with torch.no_grad():
            for p,a,b in zip(parameters,old,proposed):p.copy_(a+fraction*(b-a))
        row=evaluate()
        attempts.append(dict(fraction=fraction,**row))
        if not row['failures']:
            return dict(accepted=True,fraction=fraction,attempts=attempts)
    with torch.no_grad():
        for p,a in zip(parameters,old):p.copy_(a)
    optimizer.load_state_dict(optimizer_before)
    return dict(accepted=False,fraction=0.,attempts=attempts)
