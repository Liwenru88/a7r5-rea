import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hue24_experts as h
import structured_response as s


class Hue24Tests(unittest.TestCase):
    def test_manual_gate_and_bernstein_full_matrix_mix(self):
        rng=np.random.default_rng(9);x=rng.uniform(.03,.97,(60,3));d=rng.uniform(-.06,.06,x.shape)
        shared=rng.normal(0,.01,(81,3));e=rng.normal(0,.02,(24,9,3))
        a=x[:,0]-(x[:,1]+x[:,2])/2;b=np.sqrt(3)/2*(x[:,1]-x[:,2]);q=a*a+b*b
        angles=np.arange(24)*np.pi/12
        z=12*(a[:,None]*np.cos(angles)+b[:,None]*np.sin(angles))/np.sqrt(q[:,None]+.04**2)
        p=np.exp(z-z.max(1,keepdims=True));p/=p.sum(1,keepdims=True);g=q[:,None]/(q[:,None]+.04**2)*p
        np.testing.assert_allclose(h.weights(x),g,atol=2e-15)
        l=x@np.array([.2126,.7152,.0722]);bern=np.column_stack([(1-l)**2,2*l*(1-l),l*l])
        np.testing.assert_array_equal(h.luminosity_basis(x),bern)
        np.testing.assert_allclose(bern.sum(1),1,atol=2e-16)
        expected=np.einsum('nb,cbo->nco',s.basis(x,s.KIND_C1),shared.reshape(3,27,3))
        for k in range(24):expected+=g[:,k,None,None]*np.einsum('nb,cbo->nco',bern,e[k].reshape(3,3,3))
        np.testing.assert_allclose(h.response_field(x,shared,e),expected,atol=2e-16)
        np.testing.assert_allclose(h.predict_correction(x,d,shared,e),np.einsum('nc,nco->no',d,expected),atol=2e-16)
        self.assertEqual(h.features(x,d).shape,(60,216))
        np.testing.assert_allclose(h.features(x,d)[:,:9],np.einsum('n,nc,nb->ncb',g[:,0],d,bern).reshape(60,9),atol=0)
        # All cross-channel interactions are available in every expert.
        e=np.zeros((24,9,3));e[:,:,2]=1
        out=h.predict_correction(np.array([[1.,0,0]]),np.array([[.1,0,0]]),np.zeros((81,3)),e)
        self.assertGreater(out[0,2],.09)

    def test_neutral_zero_experts_zero_grid_and_grid_linearity(self):
        rng=np.random.default_rng(8);x=rng.uniform(0,1,(50,3));d=rng.uniform(-.1,.1,x.shape)
        shared=rng.normal(0,.02,(81,3));e=rng.normal(0,.03,(24,9,3))
        gray=np.repeat(np.linspace(0,1,31)[:,None],3,axis=1)
        np.testing.assert_array_equal(h.weights(gray),0)
        np.testing.assert_array_equal(h.predict_correction(x,d,shared,np.zeros_like(e)),s.predict_correction(x,d,shared,s.KIND_C1))
        np.testing.assert_array_equal(h.predict_correction(x,np.zeros_like(d),shared,e),0)
        np.testing.assert_array_equal(h.predict_correction(x,2*d,shared,e),2*h.predict_correction(x,d,shared,e))
        base=np.einsum('nb,cbo->nco',s.basis(gray,s.KIND_C1),shared.reshape(3,27,3))
        np.testing.assert_array_equal(h.response_field(gray,shared,e),base)

    def test_periodic_gate_and_c1_gray_and_halfstep(self):
        # Input opponent hue -15 degrees is direction23, with direction0 its
        # immediate neighbor. Rotate by one bin: gates roll by one exactly.
        def rgb(angle):
            a=.25*np.cos(angle);b=.25*np.sin(angle)
            return np.array([[.5+2*a/3,.5-a/3+b/np.sqrt(3),.5-a/3-b/np.sqrt(3)]])
        np.testing.assert_allclose(h.weights(rgb(np.pi/12)),np.roll(h.weights(rgb(0)),1,axis=1),atol=3e-15)
        self.assertGreater(h.weights(rgb(-np.pi/12))[0,23],h.weights(rgb(-np.pi/12))[0,22])
        rng=np.random.default_rng(2);shared=rng.normal(0,.02,(81,3));e=rng.normal(0,.02,(24,9,3))
        for center,direction in [(np.array([[.8,.2,.2]]),np.array([[0.,1.,-1.]])),
                                 (np.array([[.5,.5,.5]]),np.array([[1.,-1.,0.]])),
                                 (np.array([[.5,.3,.7]]),np.array([[1.,0.,0.]]))]:
            errors=[]
            for step in (1e-4,5e-5):
                def f(at):return h.response_field(center+at*direction,shared,e)
                mid=f(0);left=(3*mid-4*f(-step)+f(-2*step))/(2*step);right=(-3*mid+4*f(step)-f(2*step))/(2*step)
                errors.append(np.max(abs(left-right)))
            self.assertLess(errors[1],1e-5)
            self.assertLessEqual(errors[1],errors[0]*.3+1e-10)

    def test_support_full_paths_overlap_and_cyclic_curvature(self):
        rng=np.random.default_rng(12);x=rng.uniform(.05,.95,(50,3));e=rng.normal(0,.02,(24,9,3))
        support,factor=h.detail_support(x,np.ones(50));self.assertEqual(support.shape,(24,3))
        self.assertTrue(np.all((factor>=1)&(factor<=16)))
        zero_support,zero_factor=h.detail_support(np.zeros((10,3)),np.ones(10))
        np.testing.assert_array_equal(zero_support,0);np.testing.assert_array_equal(zero_factor,16)
        paths={key:rng.normal(0,.01,(7,216 if key in ('first','second') else 3)) for key in ['first','second','base_first','base_second']}
        terms=h.regularization_terms(x,e,factor,paths)
        for key,name in [('first','path_gradient'),('second','path_curvature')]:
            val=paths['base_'+key]+paths[key]@e.reshape(216,3)
            self.assertAlmostEqual(terms[name],np.mean(val*val),places=15)
        c=e.reshape(24,3,3,3)
        self.assertAlmostEqual(terms['lum_curvature'],np.mean((2*np.diff(c,n=2,axis=2))**2),places=15)
        ring=np.roll(c,1,axis=0)-2*c+np.roll(c,-1,axis=0)
        self.assertAlmostEqual(terms['ring_curvature'],np.mean(ring*ring),places=15)
        fields=np.einsum('nb,ecbo->neco',h.luminosity_basis(x),c);g=h.weights(x)
        manual=[]
        for k in range(24):manual.append(g[:,k]*g[:,(k+1)%24]*np.sum((fields[:,k]-fields[:,(k+1)%24])**2,axis=(1,2)))
        self.assertAlmostEqual(terms['overlap'],np.mean(manual),places=15)
        # A coefficient at direction23 is coupled to direction0 at wrap.
        impulse=np.zeros_like(e);impulse[23]=1
        wrapped=h.regularization_terms(x,impulse)
        self.assertGreater(wrapped['ring_curvature'],0)
        same=np.repeat(e[:1],24,axis=0)
        self.assertEqual(h.regularization_terms(x,same)['overlap'],0)
        self.assertEqual(h.regularization_terms(x,same)['ring_curvature'],0)

    def test_invalid_arguments(self):
        x=np.ones((2,3))*.5
        for gate in ({},dict(h.GATE,s0=0),dict(h.GATE,kappa=True),dict(h.GATE,c0=np.inf)):
            with self.assertRaises(ValueError):h.weights(x,gate)
        for bad in (np.ones((2,2)),np.ones((2,3))*1.1,np.array([[np.nan,0,0]])):
            with self.assertRaises(ValueError):h.weights(bad)
        with self.assertRaises(ValueError):h.response_field(x,np.zeros((81,3)),np.zeros((24,81,3)))
        with self.assertRaises(ValueError):h.regularization_terms(x,np.zeros((24,9,3)),path_constraints={})
        self.assertEqual(h.validate_gate(),h.GATE)

    def test_cpu_fit_and_every_nonzero_numpy_torch_regularizer(self):
        try:import torch
        except ImportError:self.skipTest('torch unavailable')
        rng=np.random.default_rng(22);x=rng.uniform(.15,.85,(100,3));d=rng.uniform(-.07,.07,x.shape)
        shared=rng.normal(0,.003,(81,3));saved=shared.copy();e=rng.normal(0,.002,(24,9,3))
        e[:,:3,0]+=.04
        y=x+h.predict_correction(x,d,shared,e)
        paths={key:rng.normal(0,.001,(5,216 if key in ('first','second') else 3)) for key in ['first','second','base_first','base_second']}
        fitted,note=h.solve(x,y,d,np.ones(100),shared,device='cpu',regularization=.25,iterations=70,scale=0,mix=0,path_constraints=paths)
        self.assertEqual(fitted.shape,(24,9,3));self.assertTrue(note['accepted'])
        self.assertEqual(note['trainable_parameter_count'],648);self.assertEqual(note['expert_count'],24)
        np.testing.assert_array_equal(saved,shared)
        self.assertLess(note['preflight_max_rgb_error'],1e-12)
        self.assertLess(max(note['preflight_regularizer_relative_errors'].values()),1e-12)
        self.assertLess(note['preflight_data_loss_error'],1e-12)
        self.assertLess(note['preflight_regularization_loss_error'],1e-12)
        self.assertLess(note['final_data_loss'],note['initial_objective']*.03)
        terms=h.regularization_terms(x,fitted,np.asarray(note['detail_support_factor']),paths)
        for key,val in terms.items():self.assertAlmostEqual(val,note['penalty_terms'][key],places=12)
        self.assertAlmostEqual(.25*sum(h.PENALTY_RATES[k]*v for k,v in terms.items()),note['final_regularization_loss'],places=14)


if __name__=='__main__':unittest.main()
