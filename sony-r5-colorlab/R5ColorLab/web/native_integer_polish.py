"""整数候选的有限复选；平滑相对原配方的增量，不改原库。"""
import math
import numpy as np

from native_feasible_experiment import blend_entry


def polish_delta(source,candidate,*,alpha=1.,grid_strength=0.,hue_strength=0.):
    if any(not math.isfinite(x) or not 0<=x<=1 for x in (alpha,grid_strength,hue_strength)):
        raise ValueError('整数复选强度必须位于0和1之间')
    result=blend_entry(source,candidate,alpha)
    if grid_strength:
        base=np.asarray(source['grid_5x9x9']['coefficients'],float)
        delta=np.asarray(result['grid_5x9x9']['coefficients'],float)-base
        smooth=delta.copy()
        # 存储顺序为颜色通道×5×9×9，仅平滑三个空间轴。
        for axis in (1,2,3):
            pad=[(0,0)]*4;pad[axis]=(1,1);padded=np.pad(smooth,pad,mode='edge')
            left=[slice(None)]*4;right=left.copy();left[axis]=slice(0,-2);right[axis]=slice(2,None)
            smooth=(2*smooth+padded[tuple(left)]+padded[tuple(right)])/4
        result['grid_5x9x9']['coefficients']=np.rint(base+(1-grid_strength)*delta+grid_strength*smooth).astype(int).tolist()
    if hue_strength:
        base=np.asarray(source['block13'],float);delta=np.asarray(result['block13'],float)-base
        smooth=(2*delta+np.roll(delta,1,axis=1)+np.roll(delta,-1,axis=1))/4
        result['block13']=np.rint(base+(1-hue_strength)*delta+hue_strength*smooth).astype(int).tolist()
    # 编解码执行原格式合法性与范围校验，不以裁剪掩盖非法候选。
    return blend_entry(source,result,1.)
