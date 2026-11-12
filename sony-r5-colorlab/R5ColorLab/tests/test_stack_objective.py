"""Independent objective, gradient and packed-acceptance checks for NC stack."""
import colorsys,unittest
import numpy as np
import torch
import core
from gpu_tensor import TensorTools
from measured_response import get
from grid_models import default_response
from perceptual import de2000,to_lab
from hue_direction import HueDirectionBank
from stack_objective import (de00_squared,TargetDerivatives,Scorer,GridObjective,
    acceptable,optimize_grid,optimize_rounding)


class StackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools=TensorTools('cpu',torch.float64)
        cls.design=np.array([colorsys.hsv_to_rgb(h/24,.7,v)for h in range(24)for v in (.1,.3,.6,.9)])
        cls.target=np.clip(cls.design*[.94,1.01,.97]+.002,0,1)
        cls.split=np.full(len(cls.design),'train');cls.kind=np.full(len(cls.design),'hue24_tonal')
        cls.direction=HueDirectionBank(cls.design,cls.target,cls.split,cls.kind)
        cls.derivatives=TargetDerivatives(cls.design,cls.target,cls.split,cls.kind)
        cls.scorer=Scorer(get(default_response()),cls.target,np.arange(len(cls.design)),np.ones(len(cls.design)),cls.direction,cls.derivatives)
        cls.grid=np.random.default_rng(74).integers(-6,7,(405,3),dtype=np.int8)

    def test_squared_de00_matches_independent_numpy(self):
        rng=np.random.default_rng(57)
        a=np.r_[rng.random((150,3)),np.zeros((1,3)),np.ones((1,3))*.5]
        b=np.r_[rng.random((150,3)),np.ones((1,3))*.01,np.ones((1,3))*.6]
        actual=de00_squared(self.tools,self.tools.tensor(to_lab(a*255)),self.tools.tensor(to_lab(b*255))).numpy()
        np.testing.assert_allclose(actual,de2000(to_lab(a*255),to_lab(b*255))**2,rtol=2e-10,atol=1e-8)

    def test_equal_and_gray_colors_have_finite_gradients(self):
        v=self.tools.tensor([[0.,0.,0.],[50.,0.,0.],[50.,15.,-30.]]).requires_grad_(True)
        loss=de00_squared(self.tools,v,v.detach()).sum();loss.backward()
        self.assertTrue(torch.isfinite(v.grad).all())
        self.assertLess(float(loss.detach()),1e-12)

    def test_derivative_cpu_gpu_and_target_zero(self):
        b=self.derivatives
        self.assertAlmostEqual(b.cpu_cost(self.target[b.source_indices]),0,places=12)
        pred=self.design[b.source_indices]
        actual=float(b.tensor_loss(self.tools,self.tools.tensor(pred)))*255**2
        self.assertAlmostEqual(actual,b.cpu_cost(pred),places=9)

    def test_active_hue_direction30_penalty_and_gradient(self):
        target=np.array([colorsys.hsv_to_rgb((h/24+.04*v)%1,.7,v)for h in range(24)for v in (.1,.3,.6,.9)])
        predicted=np.array([colorsys.hsv_to_rgb((h/24-.04*v)%1,.7,v)for h in range(24)for v in (.1,.3,.6,.9)])
        bank=HueDirectionBank(self.design,target,self.split,self.kind)
        values=predicted[bank.source_indices]
        tensor=self.tools.tensor(values).requires_grad_(True)
        loss=bank.tensor_loss(self.tools,tensor,30)*255**2;loss.backward()
        self.assertGreater(float(loss.detach().cpu()),0)
        self.assertAlmostEqual(float(loss.detach().cpu()),bank.cost(values,30),delta=max(1e-6,bank.cost(values,30)*1e-4))
        self.assertTrue(torch.isfinite(tensor.grad).all())

    def test_grid_full_objective_and_gradient_match_cpu(self):
        o=GridObjective(self.tools,self.design,self.scorer)
        g=self.tools.tensor(self.grid).requires_grad_(True)
        loss=o.loss(g)*255**2;loss.backward()
        self.assertAlmostEqual(float(loss.detach()),self.scorer.score(self.design,self.grid)['total'],places=8)
        direction=np.random.default_rng(32).normal(size=(405,3));direction/=np.linalg.norm(direction)
        eps=1e-5
        plus=self.scorer.score(self.design,self.grid+eps*direction)['total']
        minus=self.scorer.score(self.design,self.grid-eps*direction)['total']
        self.assertAlmostEqual(float((g.grad*self.tools.tensor(direction)).sum()),(plus-minus)/(2*eps),delta=2e-5)

    def test_validation_and_test_targets_do_not_enter_objective(self):
        # Duplicate rows as validation/test, then corrupt their targets. The
        # scorer must render/score only the TRAIN rows and frozen TRAIN banks.
        from unittest.mock import Mock
        x=np.r_[self.design,self.design[:2]]
        target=np.r_[self.target,[[100,100,100],[-100,-100,-100]]]
        model=Mock(wraps=self.scorer.model)
        s=Scorer(model,target,self.scorer.train,self.scorer.weights,self.direction,self.derivatives)
        self.assertEqual(s.score(x,self.grid),self.scorer.score(self.design,self.grid))
        self.assertEqual(len(model.predict_cpu.call_args.args[0]),len(self.design))

    def test_exact_acceptance_rejects_color_regression(self):
        before=dict(total=4.,data=2.)
        self.assertFalse(acceptable(before,dict(total=3.,data=2.01)))
        self.assertTrue(acceptable(before,dict(total=3.,data=1.99)))

    def test_short_fit_and_rounding_preserve_packed_bounds(self):
        events=[]
        grid,continuous,audit=optimize_grid(self.tools,self.design,self.grid,self.scorer,lambda **v:events.append(v),evaluations=3)
        grid,rounding=optimize_rounding(self.tools,self.design,grid,continuous,self.scorer,lambda **v:None,steps=2,block_budget=2)
        self.assertTrue(np.all(grid>=-64)&np.all(grid<=63))
        self.assertLessEqual(self.scorer.score(self.design,grid)['data'],audit['before']['data']+1e-9)
        self.assertTrue(any('loss_sample' in row for row in events))

    def test_native_update_freezes_gamma_and_accepts_actual_integers(self):
        import baseline,v4_dataset
        from edit_parameter_context import ParameterContext,RuntimeColor
        from fit_anchor_native import SmoothNative,vector_for
        from stack_training import FrozenGamma,native_update
        from patch_sampling import center_mean
        ctx=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.PT_ID)))
        arrays,_=v4_dataset.load()
        x=arrays['input'][np.flatnonzero(arrays['sample_kind']=='uniform_luma')[:len(self.design)]]
        smooth=SmoothNative(ctx,x);vector=vector_for(ctx);smooth.gamma_shape=FrozenGamma(ctx.gamma_y)
        base=center_mean(ctx.base.color_only(x))/16383
        target=np.clip(base*[.99,1.01,.98],0,1)
        direction=HueDirectionBank(self.design,target,self.split,self.kind)
        derivatives=TargetDerivatives(self.design,target,self.split,self.kind)
        scorer=Scorer(self.scorer.model,target,np.arange(len(x)),np.ones(len(x)),direction,derivatives)
        render=lambda p:center_mean(ctx.build(**p).color_only(x))/16383
        updated,new_base,params,audit=native_update(self.tools,smooth,vector,base,self.grid,scorer,render,lambda **v:None,evaluations=2)
        np.testing.assert_array_equal(updated[104:],vector[104:])
        np.testing.assert_array_equal(smooth.params(updated)['gamma_y'],ctx.gamma_y)
        if params is not None:np.testing.assert_array_equal(params['gamma_y'],ctx.gamma_y)
        self.assertLessEqual(audit['after']['data'],audit['before']['data']+1e-9)


if __name__=='__main__':unittest.main()
