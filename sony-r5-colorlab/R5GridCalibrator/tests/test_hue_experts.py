import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hue_experts as h
import structured_response as s


class HueExpertTests(unittest.TestCase):
    def test_manual_gate_and_mixed_full_response_formula(self):
        rng = np.random.default_rng(19)
        x = rng.uniform(.02,.98,(70,3)); d = rng.uniform(-.06,.06,x.shape)
        shared = rng.normal(0,.03,(81,3)); experts = rng.normal(0,.04,(3,81,3))
        a = x[:,0]-(x[:,1]+x[:,2])/2
        b = np.sqrt(3)*(x[:,1]-x[:,2])/2
        q = a*a+b*b
        logits = 2/.25*np.stack([a,-.5*a+np.sqrt(3)/2*b,-.5*a-np.sqrt(3)/2*b],1)
        p = np.exp(logits-logits.max(1,keepdims=True));p /= p.sum(1,keepdims=True)
        gate = q[:,None]/(q[:,None]+.04**2)*p
        np.testing.assert_allclose(h.weights(x),gate,atol=2e-15)
        expected = s.predict_correction(x,d,shared,s.KIND_C1)
        field = np.einsum('nb,cbo->nco',s.basis(x,s.KIND_C1),shared.reshape(3,27,3))
        for i in range(3):
            expected += gate[:,i,None]*s.predict_correction(x,d,experts[i],s.KIND_C1)
            field += gate[:,i,None,None]*np.einsum('nb,cbo->nco',s.basis(x,s.KIND_C1),experts[i].reshape(3,27,3))
        np.testing.assert_allclose(h.predict_correction(x,d,shared,experts),expected,atol=2e-16)
        np.testing.assert_allclose(h.response_field(x,shared,experts),field,atol=2e-16)
        np.testing.assert_allclose(np.einsum('nc,nco->no',d,h.response_field(x,shared,experts)),expected,atol=2e-16)
        self.assertEqual(h.features(x,d).shape,(70,243))
        np.testing.assert_allclose(h.features(x,d)[:,:81],gate[:,0,None]*s.features(x,d,s.KIND_C1),atol=0)
        # A grid-component-to-different-output response is retained, not diagonalized.
        cross = np.zeros((3,81,3));cross[0,4,2]=1
        out=h.predict_correction(np.array([[1.,0,0]]),np.array([[.1,0,0]]),np.zeros((81,3)),cross)
        self.assertGreater(out[0,2],.09)

    def test_zero_experts_and_zero_grid_identity(self):
        rng=np.random.default_rng(20);x=rng.uniform(0,1,(60,3));d=rng.uniform(-.1,.1,x.shape)
        shared=rng.normal(0,.02,(81,3));experts=rng.normal(0,.02,(3,81,3))
        np.testing.assert_array_equal(h.predict_correction(x,d,shared,np.zeros_like(experts)),s.predict_correction(x,d,shared,s.KIND_C1))
        np.testing.assert_array_equal(h.predict_correction(x,np.zeros_like(x),shared,experts),np.zeros_like(x))
        # Fixed x: expert weighting cannot alter linearity in the grid lookup values.
        np.testing.assert_allclose(h.predict_correction(x,2*d,shared,experts),2*h.predict_correction(x,d,shared,experts),atol=0)
        np.testing.assert_array_equal(h.weights(x),h.weights(x.copy()))

    def test_neutral_fallback_and_c1_at_gray_and_red_hue_seam(self):
        gray=np.repeat(np.linspace(0,1,33)[:,None],3,axis=1)
        np.testing.assert_array_equal(h.weights(gray),0)
        self.assertTrue(np.isfinite(h.weights(gray)).all())
        rng=np.random.default_rng(72);shared=rng.normal(0,.03,(81,3));experts=rng.normal(0,.03,(3,81,3))
        base=np.einsum('nb,cbo->nco',s.basis(gray,s.KIND_C1),shared.reshape(3,27,3))
        np.testing.assert_array_equal(h.response_field(gray,shared,experts),base)
        # No atan2 wrap: crossing the red hue axis is an ordinary smooth line.
        for center,direction in ((np.array([[.8,.2,.2]]),np.array([[0.,1.,-1.]])),
                                 (np.array([[.5,.5,.5]]),np.array([[1.,-1.,0.]])),
                                 (np.array([[.5,.3,.7]]),np.array([[1.,0.,0.]]))):
            errors=[]
            for step in (1e-4,5e-5):
                def f(at): return h.response_field(center+at*direction,shared,experts)
                c=f(0);left=(3*c-4*f(-step)+f(-2*step))/(2*step)
                right=(-3*c+4*f(step)-f(2*step))/(2*step)
                errors.append(np.max(abs(left-right)))
            self.assertLess(errors[1],1e-5)
            self.assertLessEqual(errors[1],errors[0]*.3+1e-10)
        # The residual and its gradient vanish as chroma ->0; constants stay finite.
        center=np.array([[.4,.4,.4]])
        ratios=[]
        for step in (1e-4,5e-5):
            x=center+np.array([[step,-step,0]])
            ratios.append(h.weights(x).sum()/step)
        self.assertLess(ratios[1],ratios[0]*.501)

    def test_support_and_complete_path_regularization(self):
        rng=np.random.default_rng(88);x=rng.uniform(.05,.95,(50,3));e=rng.normal(0,.03,(3,81,3))
        support,factor=h.detail_support(x,np.ones(len(x)))
        self.assertEqual(support.shape,(3,19));self.assertTrue(np.all((factor>=1)&(factor<=16)))
        empty_support,empty_factor=h.detail_support(np.zeros((10,3)),np.ones(10))
        np.testing.assert_array_equal(empty_support,0);np.testing.assert_array_equal(empty_factor,16)
        paths=dict(first=rng.normal(0,.1,(7,243)),second=rng.normal(0,.2,(5,243)),
                   base_first=rng.normal(0,.01,(7,3)),base_second=rng.normal(0,.01,(5,3)))
        terms=h.regularization_terms(x,e,factor,paths)
        for name,key in [('path_gradient','first'),('path_curvature','second')]:
            value=paths['base_'+key]+paths[key]@e.reshape(243,3)
            self.assertAlmostEqual(terms[name],np.mean(value**2),places=15)
        zero=h.regularization_terms(x,np.zeros_like(e),factor,paths)
        self.assertEqual(zero['path_gradient'],np.mean(paths['base_first']**2))
        self.assertEqual(zero['path_curvature'],np.mean(paths['base_second']**2))
        for key in ['coarse_anchor','detail','gradient_delta','gradient_absolute','curvature','overlap']:
            self.assertEqual(zero[key],0)
        # Identical expert fields have zero pairwise disagreement, regardless of gates.
        same=np.repeat(e[:1],3,axis=0)
        self.assertEqual(h.regularization_terms(x,same)['overlap'],0)

    def test_invalid_inputs_and_gate_values(self):
        for gate in ({},{'kappa':2,'s0':.25,'c0':0},dict(h.GATE,kappa=True),
                     dict(h.GATE,s0=np.inf),dict(h.GATE,extra=1)):
            with self.assertRaises(ValueError):h.weights(np.ones((2,3))*.5,gate)
        for x in (np.ones((2,2)),np.array([[np.nan,0,0]]),np.ones((2,3))*1.1):
            with self.assertRaises(ValueError):h.weights(x)
        with self.assertRaises(ValueError):h.predict_correction(np.ones((2,3))*.5,np.zeros((2,3)),np.zeros((81,3)),np.zeros((243,3)))
        with self.assertRaises(ValueError):h.regularization_terms(np.ones((2,3))*.5,np.zeros((3,81,3)),path_constraints={'first':np.zeros((2,243))})
        self.assertEqual(h.validate_gate(),h.GATE)

    def test_cpu_fit_and_nonzero_numpy_torch_preflight(self):
        try:import torch
        except ImportError:self.skipTest('torch unavailable')
        rng=np.random.default_rng(31);x=rng.uniform(.15,.85,(100,3));d=rng.uniform(-.06,.06,x.shape)
        shared=rng.normal(0,.005,(81,3));saved=shared.copy();truth=np.zeros((3,81,3))
        for expert in range(3):
            truth[expert,:8]=(.02+expert*.01)*np.eye(3)[0]
        y=x+h.predict_correction(x,d,shared,truth)
        paths=dict(first=rng.normal(0,.001,(4,243)),second=rng.normal(0,.001,(5,243)),
                   base_first=rng.normal(0,.001,(4,3)),base_second=rng.normal(0,.001,(5,3)))
        e,note=h.solve(x,y,d,np.ones(len(x)),shared,device='cpu',regularization=.25,
                       iterations=50,scale=0,mix=0,path_constraints=paths)
        self.assertTrue(note['accepted']);self.assertTrue(note['shared_frozen'])
        np.testing.assert_array_equal(shared,saved)
        self.assertEqual(e.shape,(3,81,3));self.assertEqual(note['trainable_parameter_count'],729)
        self.assertLess(note['preflight_max_rgb_error'],1e-12)
        self.assertLess(max(note['preflight_regularizer_relative_errors'].values()),1e-12)
        self.assertLess(note['preflight_regularization_loss_error'],1e-12)
        self.assertLess(note['preflight_data_loss_error'],1e-12)
        self.assertLess(note['final_data_loss'],note['initial_objective']*.05)
        terms=h.regularization_terms(x,e,np.asarray(note['detail_support_factor']),paths)
        for key,value in terms.items():self.assertAlmostEqual(value,note['penalty_terms'][key],places=12)
        expected=.25*sum(h.PENALTY_RATES[key]*value for key,value in terms.items())
        self.assertAlmostEqual(expected,note['final_regularization_loss'],places=14)


if __name__=='__main__':unittest.main()
