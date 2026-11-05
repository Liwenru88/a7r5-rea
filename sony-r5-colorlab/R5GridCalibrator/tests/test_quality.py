from legacy_fit_fixture import legacy_fit
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import model,quality
import test_calibrator as fixtures

class QualityTests(unittest.TestCase):
    def test_weights_are_training_only_pair_balanced_and_boost_rare_colors(self):
        x=np.vstack([np.tile([.5,.5,.5],(100,1)),[[.8,.1,.1],[.1,.8,.1]],np.tile([.3,.4,.5],(80,1))])
        ids=np.r_[np.zeros(102,int),np.ones(80,int)];split=np.r_[np.zeros(102,int),np.ones(80,int)]
        w=quality.balanced_weights(x,ids,split)
        self.assertGreater(w[100],w[0]);self.assertAlmostEqual(w[:102].sum(),1)
        changed=x.copy();changed[102:]=.9
        np.testing.assert_array_equal(w[:102],quality.balanced_weights(changed,ids,split)[:102])
    def test_robust_response_improves_clean_holdout_with_training_outliers(self):
        pairs,_=fixtures.FitTests().pairs();damaged=copy.deepcopy(pairs)
        for p in damaged:
            if p['role']=='train':
                ix=np.flatnonzero(p['buckets']<7)[::9]
                p['y'][ix]=np.clip(p['y'][ix]+[.2,-.15,.12],0,1)
        robust=legacy_fit(damaged,refine=False)
        plain=legacy_fit(damaged,refine=False,options=dict(robust_scale=0))
        self.assertLess(robust['report']['test']['rmse'],plain['report']['test']['rmse']*.6)
        self.assertIn('grouped_test',robust['report']);self.assertIn('neutral',robust['report']['grouped_test'])
    def test_adaptive_fit_ignores_test_colors_and_reports_feature_rank(self):
        pairs,_=fixtures.FitTests().pairs();opts=dict(starts=1,alternations=2,max_nfev=10,samples_per_pair=40)
        a=legacy_fit(pairs,options=opts);p=copy.deepcopy(pairs)
        p[-1]['x']=np.ones_like(p[-1]['x'])*.1;p[-1]['y']=np.ones_like(p[-1]['y'])*.9
        b=legacy_fit(p,options=opts)
        np.testing.assert_array_equal(a['response_weights'],b['response_weights'])
        np.testing.assert_array_equal(a['coordinate_affine'],b['coordinate_affine'])
        runs=a['report']['optimization']['runs']
        self.assertTrue(any(r['search_samples']>a['report']['optimization']['search_samples'] for r in runs))
        self.assertLessEqual(a['report']['support_diagnostics']['touched_nodes'],405)
    def test_bad_new_options_fail(self):
        for val in [dict(robust_scale=float('nan')),dict(robust_scale=True),dict(adaptive=1),dict(color_balance='yes')]:
            with self.assertRaises(ValueError):model.optimization_options(val)
    def test_zero_grid_and_clipped_response_share_predictor(self):
        x=np.array([[.99,.95,.9],[.05,.1,.15]]);d=np.ones_like(x)*.1;y=np.clip(x+d,0,1)
        coef,pred,_=quality.response_solve(x,y,d,False,model.features,np.ones(2)/2,np.ones(2,bool),3)
        np.testing.assert_allclose(pred,np.clip(x+model.features(x,d)@coef,0,1))
        self.assertTrue(np.isfinite(pred).all())
