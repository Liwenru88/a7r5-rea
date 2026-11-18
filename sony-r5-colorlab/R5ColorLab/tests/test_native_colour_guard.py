"""颜色分桶保护使用原配方的量化上界，避免局部颜色退步被全图均值掩盖。"""
import numpy as np
import torch
from gpu_tensor import TensorTools
from native_full_photos import ColourBucketProtection,FullPhotoBank


def test_bucket_guard_rejects_local_colour_regression_with_finite_gradient():
    row=dict(scene='dev',role='development',inputs=np.zeros((144,9,3),np.uint16),
        target=np.full((144,3),.5),display=np.arange(144).reshape(12,12))
    bank=FullPhotoBank([row]);bank.reference=np.full((144,3),.5)
    guard=ColourBucketProtection(bank);tools=TensorTools('cpu',torch.float64)
    p=tools.tensor(np.full((144,3),.5));p[:80]+=.05;p.requires_grad_(True)
    loss,stats=guard.parts(tools,p);loss.backward()
    assert float(loss.detach())>0 and stats['colour_bucket_active']>0
    assert bool(torch.isfinite(p.grad).all())
