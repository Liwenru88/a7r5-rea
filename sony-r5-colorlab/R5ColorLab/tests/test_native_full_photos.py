"""照片整批训练保持逐图等权，并禁止留出目标反向传播。"""
import numpy as np
import pytest
import torch
from gpu_tensor import TensorTools
from native_full_photos import FullPhotoBank,FullPhotoProtection


def row(scene,n):
    return dict(scene=scene,role='development',inputs=np.zeros((n,9,3),np.uint16),
        target=np.full((n,3),128/255),display=np.arange(n)[None])


def test_full_photos_average_scenes_instead_of_pixels_and_keep_gradients():
    bank=FullPhotoBank([row('short',1),row('long',9)])
    tools=TensorTools('cpu',torch.float64)
    p=tools.tensor(np.r_[np.full((1,3),129/255),np.full((9,3),131/255)]).requires_grad_(True)
    means=bank.means(tools,p)
    assert abs(float(means[0].detach())-2)<1e-8
    means.sum().backward()
    assert bool(torch.isfinite(p.grad).all())


def test_holdout_photos_cannot_enter_full_batch_loss():
    with pytest.raises(ValueError,match='开发'):
        FullPhotoBank([dict(row('held',9),role='holdout')])


def test_mean_guard_updates_multipliers_without_invalidating_backward():
    bank=FullPhotoBank([row('a',9)])
    bank.reference=np.full((9,3),129/255)
    guard=FullPhotoProtection(bank)
    tools=TensorTools('cpu',torch.float64)
    for _ in range(26):
        p=tools.tensor(np.full((9,3),130/255)).requires_grad_(True)
        loss,stats=guard.parts(tools,p);loss.backward()
        assert bool(torch.isfinite(p.grad).all())
    assert guard.step==26 and float(guard.multipliers.min())>0
    assert stats['full_photo_max_violation']>0
