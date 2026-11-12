"""Optional target-aware tone/tint derivatives retain real target turns."""
import json
import unittest
from unittest.mock import patch
import numpy as np
import core  # Establish the shared scripts import path, like PC integration tests.
import pc_stages as pc


class TargetCurveConstraintTests(unittest.TestCase):
    def test_default_zero_keeps_old_solver_and_curve_bytes(self):
        x=np.linspace(0,1,41)**1.3;values=np.sin(x)*.3+x*.5
        axis,actual=pc.curve_fit(x,values)
        nodes=len(axis);pos=x*(nodes-1);low=np.minimum(pos.astype(int),nodes-2);frac=pos-low
        a=np.zeros((len(x),nodes));a[np.arange(len(x)),low]=1-frac;a[np.arange(len(x)),low+1]=frac
        d2=np.diff(np.eye(nodes),n=2,axis=0);mass=np.full(len(x),1/len(x))
        expected=np.linalg.solve(a.T@(a*mass[:,None])+.002*(d2.T@d2)+np.eye(nodes)*1e-10,a.T@(values*mass))
        np.testing.assert_array_equal(actual,expected)
        base=np.repeat(x[:,None],3,axis=1);target=base**.9
        a=pc.fit_curves(base,target);b=pc.fit_curves(base,target,target_neighborhood=0)
        self.assertEqual(json.dumps(a,sort_keys=True),json.dumps(b,sort_keys=True))
        self.assertNotIn('target_neighborhood',a)

    def test_true_target_turns_zero_residual_and_added_turn_nonzero(self):
        x=np.arange(7)*.05;target=np.array([.1,.2,.18,.3,.28,.4,.35])
        operator,report=pc.curve_neighborhood_design(x,target_neighborhood=30)
        self.assertEqual(float(np.sum((operator@(target-target))**2)),0.)
        changed=target.copy();changed[3]+=.05
        self.assertGreater(float(np.sum((operator@(changed-target))**2)),0.)
        self.assertTrue(report['enabled']);self.assertFalse(report['target_interpolation'])

    def test_nonuniform_second_derivative_and_duplicate_weighted_average(self):
        x=np.array([0,.03,.09,.12]);operator,report=pc.curve_neighborhood_design(x,target_neighborhood=30)
        # After the first-order rows, a linear residual has zero curvature.
        np.testing.assert_allclose(operator[report['first_rows']:]@(x*.3+.2),0,atol=1e-15)
        xx=np.r_[x,x[[1]]];weight=np.array([1,2,1,1,3])
        op,r=pc.curve_neighborhood_design(xx,weight,30)
        error=np.array([.1,.2,.3,.4,.5]);aggregated=error[:4].copy();aggregated[1]=(.2*2+.5*3)/5
        np.testing.assert_allclose(op@error,operator@aggregated,atol=1e-15)
        self.assertEqual(r['duplicate_lumas'],1)

    def test_sparse_and_zero_weight_lumas_do_not_create_target_interpolation(self):
        operator,report=pc.curve_neighborhood_design([0,.4,1],target_neighborhood=30)
        self.assertFalse(report['enabled']);self.assertEqual(operator.shape,(0,3))
        op,r=pc.curve_neighborhood_design([0,.05,.1],[1,0,1],30)
        self.assertEqual(r['first_rows'],1);self.assertEqual(r['second_rows'],0)
        np.testing.assert_array_equal(op.toarray()[:,1],0)
        for bad in (True,'30',-1,101,np.inf):
            with self.assertRaises(ValueError):pc.curve_neighborhood_design([0,.1],target_neighborhood=bad)

    def test_enabled_initializer_removes_absolute_and_target_derivative_squares(self):
        x=np.array([0,.015,.04,.08,.13,.21,.3]);values=np.column_stack([np.sqrt(x+.01),x*x])
        axis,actual=pc.curve_fit(x,values,target_neighborhood=60,nodes=17)
        position=x*16;low=np.minimum(position.astype(int),15);frac=position-low
        a=np.zeros((len(x),17));a[np.arange(len(x)),low]=1-frac;a[np.arange(len(x)),low+1]=frac
        design=np.vstack([a/np.sqrt(len(x)),np.eye(17)*1e-5])
        target=np.vstack([values/np.sqrt(len(x)),np.zeros((17,2))])
        expected=np.linalg.lstsq(design,target,rcond=None)[0]
        np.testing.assert_allclose(actual,expected,atol=1e-9,rtol=1e-9)

    def test_training_threads_option_and_keeps_native_curve_invariants(self):
        x=np.linspace(0,1,51);base=np.repeat(x[:,None],3,axis=1)
        target=np.clip(base**.9+np.sin(x[:,None]*9)*np.array([[.01,-.003,.005]]),0,1)
        curve,grid,audit=pc.fit_training(base,target,np.ones(len(x),bool),np.ones(len(x)),
            strategy='none',target_neighborhood=30)
        pc.validate(curve)
        self.assertTrue(np.all(np.diff(curve['tone'])>=0))
        np.testing.assert_allclose(np.asarray(curve['tint'])@pc.LUMA,0,atol=1e-15)
        self.assertTrue(audit['curve_target_neighborhood']['enabled'])
        self.assertGreater(audit['curve_target_neighborhood']['windows'],0)
        self.assertFalse(audit['curve_target_neighborhood']['legacy_d1_d2'])
        self.assertLessEqual(audit['curve_target_neighborhood']['after'],audit['curve_target_neighborhood']['before'])

    def test_sustained_curvature_single_turn_and_target_own_turn_are_free(self):
        target=np.full((5,3),.3);windows=np.arange(2)[:,None]+np.arange(4)[None,:]
        for channel in ([.1,.12,.16,.22,.3],[.1,.2,.3,.25,.2]):
            p=target.copy();p[:,0]=channel
            loss,_,_=pc.curve_backstep_loss_gradient(p,target,windows,30)
            self.assertEqual(loss,0.)
        p=target[:4].copy();p[:,0]=np.array([95,88,91,82])/255
        loss,_,_=pc.curve_backstep_loss_gradient(p,p,np.array([[0,1,2,3]]),30)
        self.assertEqual(loss,0.)

    def test_single_channel_backstep_is_penalized_and_gradient_matches(self):
        t=np.full((4,3),.3);p=t.copy();p[:,0]=np.array([95,88,91,82])/255
        windows=np.array([[0,1,2,3]])
        loss,gradient,_=pc.curve_backstep_loss_gradient(p,t,windows,30)
        self.assertGreater(loss,0.)
        np.testing.assert_array_equal(gradient[:,1:],0)
        direction=np.random.default_rng(3).normal(size=p.shape);eps=1e-6
        hi=pc.curve_backstep_loss_gradient(p+eps*direction,t,windows,30)[0]
        lo=pc.curve_backstep_loss_gradient(p-eps*direction,t,windows,30)[0]
        self.assertAlmostEqual(float(np.sum(gradient*direction)),(hi-lo)/(2*eps),places=10)

    def test_target_clip_allowance_is_per_channel_and_prediction_clip_does_not_escape(self):
        t=np.full((4,3),.3);t[:,0]=[0,.03,.06,.09]
        quantum=1/16383
        p=t.copy();p[:,0]=[0,.03,.03-2*quantum,.06-2*quantum];p[:,1]=np.array([95,88,91,82])/255
        windows=np.array([[0,1,2,3]])
        loss,gradient,audit=pc.curve_backstep_loss_gradient(p,t,windows,30)
        self.assertEqual(audit['clip_channels'],1)
        self.assertGreater(loss,0.);np.testing.assert_array_equal(gradient[:,0],0)
        self.assertTrue(np.any(gradient[:,1]!=0))
        tt=t.copy();tt[:,0]+=.1;pp=p.copy();pp[:,0]+=.1
        self.assertGreater(pc.curve_backstep_loss_gradient(pp,tt,windows,30)[0],loss)
        # Preclip values outside the display gamut retain their increments.
        p[:,1]=[-.02,-.07,-.04,-.08]
        self.assertGreater(pc.curve_backstep_loss_gradient(p,t,windows,30)[0],0.)

    def test_enabled_training_passes_zero_to_grid_neighbor_regularization(self):
        x=np.linspace(0,1,21);base=np.repeat(x[:,None],3,axis=1)
        grid=np.zeros((405,3),np.int8)
        with patch.object(pc,'fit_grid',return_value=(grid,{})) as fit:
            pc.fit_training(base,base,np.ones(len(x),bool),np.ones(len(x)),target_neighborhood=30)
        self.assertEqual(fit.call_args.kwargs['strength'],0.)
        with patch.object(pc,'fit_compressed',return_value=(grid,{})) as fit:
            pc.fit_training(base,base,np.ones(len(x),bool),np.ones(len(x)),strategy='dense-compressed',
                parameter_smoothing=30,target_neighborhood=30)
        self.assertEqual(fit.call_args.kwargs['smooth_factor'],0.)
        self.assertEqual(fit.call_args.kwargs['target_neighborhood'],30)


if __name__=='__main__':unittest.main()
