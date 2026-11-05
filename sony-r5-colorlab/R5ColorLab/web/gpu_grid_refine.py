"""Parallel grid coordinate updates on disjoint interpolation-node groups."""
import numpy as np
from gpu_tensor import TensorTools,stencil_tensor,provisional_coordinates,de2000_tensor


def refine(grid,base,target,gate,weights,sweeps,perceptual_weight,response,progress,parameter_smoothing):
    import torch
    from parameter_smoothing import multiplier,grid_cost
    from gpu_grid import edges
    tools=TensorTools();tensor=tools.tensor
    source=tensor(base);desired=tensor(target).clamp(0,1)
    mass=tensor(np.asarray(weights)/np.sum(weights))
    if isinstance(response,dict):
        from measured_response import get
        model=get(response)
        if not hasattr(model,'affine'):raise ValueError('GPU refinement requires an R5 paired snapshot')
        coords=model.coordinates_tensor(tools,source)
        mixing=tensor(model.response(np.asarray(base)))
        gates=torch.ones(len(source),device='mps')
    else:
        model=None;coords=provisional_coordinates(tools,source)
        mixing=tensor(np.eye(3) if response is None else response).expand(len(source),3,3)/256
        gates=tensor(gate)
    ids,w=stencil_tensor(tools,coords)
    w=w*gates[:,None]
    table=tensor(grid)
    original=np.asarray(grid).copy()
    raw=source+torch.einsum('nc,nco->no',(table[ids]*w[:,:,None]).sum(dim=1),mixing)
    target_lab=tools.lab(desired)
    def costs(values):
        p=values.clamp(0,1)
        loss=(p-desired).square().mean(dim=1)*255**2
        if perceptual_weight:
            de=de2000_tensor(tools,tools.lab(p),target_lab)
            loss=loss+perceptual_weight*(2.55*de).square()
        return loss
    node_ids=torch.arange(405,device='mps')
    node_group=(node_ids//81%2)*4+(node_ids//9%9%2)*2+node_ids%9%2
    groups=node_group[ids]
    edge=tensor(edges((5,9,9)),True)
    degree=torch.zeros(405,device='mps')
    degree.index_add_(0,edge[:,0],torch.ones(len(edge),device='mps'))
    degree.index_add_(0,edge[:,1],torch.ones(len(edge),device='mps'))
    # grid_cost uses strength/100 only as the enable flag; its actual multiplier
    # is .01*(1+strength/5), with no extra strength/100 factor.
    penalty=(.01*multiplier(parameter_smoothing))*255**2/(405*3*256**2) if parameter_smoothing else 0.
    actual_gram=None
    if model is not None and parameter_smoothing:
        from grid_regularization import get_penalty
        regularizer=get_penalty(response)
        actual_gram=tensor(regularizer.dense_gram)*regularizer.scale(parameter_smoothing)*255**2
    accepted=0;current=costs(raw)
    def quadratic(values):
        flat=values.reshape(-1)
        return flat@(actual_gram@flat)

    for sweep in range(sweeps):
        changed=False
        for group in range(8):
            mask=(groups==group)&(w>0)
            row_node=(ids*mask).sum(dim=1)
            row_weight=(w*mask).sum(dim=1)
            active=node_group==group
            for channel in range(3):
                neighbor=torch.zeros(405,device='mps')
                neighbor.index_add_(0,edge[:,0],table[edge[:,1],channel])
                neighbor.index_add_(0,edge[:,1],table[edge[:,0],channel])
                laplacian=degree*table[:,channel]-neighbor
                if actual_gram is not None:
                    applied_gradient=(actual_gram@table.reshape(-1)).reshape(405,3)[:,channel]
                    applied_diagonal=actual_gram.diagonal().reshape(405,3)[:,channel]
                proposals=[]
                for sign in (-1,1):
                    rgb=raw+sign*row_weight[:,None]*mixing[:,channel,:]
                    differences=(costs(rgb)-current)*mass
                    loss=torch.zeros(405,device='mps')
                    loss.index_add_(0,row_node,differences)
                    loss=loss+(2*sign*applied_gradient+applied_diagonal if actual_gram is not None else
                        penalty*(2*sign*laplacian+degree))
                    legal=active&(table[:,channel]+sign>=-64)&(table[:,channel]+sign<=63)
                    proposals.append(torch.where(legal,loss,torch.full_like(loss,float('inf'))))
                values,choice=torch.stack(proposals).min(dim=0)
                move=torch.where(values < -1e-7,choice*2-1,0).to(torch.float32)
                count=int(torch.count_nonzero(move).cpu())
                if count:
                    # RGB stencil groups are independent for the data term,
                    # but the applied-response quadratic couples their nodes.
                    # Accept the actual combined GPU objective, shrinking the
                    # integer move set if its cross terms outweigh the gain.
                    if actual_gram is not None:
                        before_gpu=(current*mass).sum()+quadratic(table)
                        order=torch.argsort(torch.where(move!=0,values,torch.full_like(values,float('inf'))))
                        kept=count
                        while kept:
                            subset=torch.zeros_like(move)
                            subset[order[:kept]]=move[order[:kept]]
                            candidate=table.clone();candidate[:,channel]+=subset
                            next_raw=raw+subset[row_node,None]*row_weight[:,None]*mixing[:,channel,:]
                            next_cost=costs(next_raw)
                            score=(next_cost*mass).sum()+quadratic(candidate)
                            if float(score.cpu()) < float(before_gpu.cpu())-1e-7:
                                table=candidate;raw=next_raw;current=next_cost
                                accepted+=kept;changed=True;break
                            kept//=2
                    else:
                        table[:,channel]+=move
                        raw=raw+move[row_node,None]*row_weight[:,None]*mixing[:,channel,:]
                        current=costs(raw);accepted+=count;changed=True
            if progress:progress(sweep=sweep+1,total_sweeps=sweeps,point=(group+1)*405//8,total_points=405,gpu_backend='Apple Metal/MPS')
        if not changed:break
    result=table.cpu().numpy().astype(np.int8)
    # A single full float64 objective check protects final acceptance while the
    # thousands of neighborhood candidates stay on the GPU.
    from perceptual import to_lab,de2000
    def reference_cost(table):
        if model is None:
            from residual_grid import stencil,coordinates
            at,weight=stencil(coordinates(base))
            delta=(np.asarray(table)[at]*weight[:,:,None]).sum(1)*np.asarray(gate)[:,None]/256
            prediction=np.clip(np.asarray(base)+delta@np.asarray(np.eye(3) if response is None else response),0,1)
        else:prediction=model.predict_cpu(base,table)
        p,t=[np.clip(np.asarray(value),0,1)*255 for value in (prediction,target)]
        rows=np.mean((p-t)**2,axis=1)
        if perceptual_weight:rows+=perceptual_weight*(2.55*de2000(to_lab(p),to_lab(t)))**2
        return float(rows@np.asarray(weights)/np.sum(weights))+grid_cost(table,parameter_smoothing,response=response)
    before,after=reference_cost(original),reference_cost(result)
    if not np.isfinite(after) or after>before:
        result=original;after=before;accepted=0
    return result,dict(before=before,after=after,accepted=accepted,sweeps=sweeps,
        backend='Apple Metal/MPS',optimizer='8 stencil parity groups; coupled actual-response quadratic with integer subset acceptance',
        cpu_final_objective_check=True,training_only=True,parameter_smoothing=parameter_smoothing,
        regularization_policy=(regularizer.metadata if actual_gram is not None else 'disabled' if not parameter_smoothing else 'teacher-neighbor-rgb-residual'),
        objective='floating RGB MSE + continuous DE00 on quantized grid; native signed 7-bit bounds')
