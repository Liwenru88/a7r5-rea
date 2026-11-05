import unittest
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor/fit_eval_python312'))
from scipy.optimize import least_squares
from native_alternation import solve_round


class AlternationTests(unittest.TestCase):
    def test_coupled_blocks_frozen_and_training_cost_decreases(self):
        vector=np.zeros(107);lo=np.full(107,-10.);hi=-lo
        seen=[]
        def residual(v):
            return np.r_[v[:3]+v[104:]-3,v[:3]-v[104:]-1,v[3:104]]
        def solve(stage,fun,initial,**kw):
            seen.append((stage,len(initial)))
            return least_squares(fun,initial,**kw)
        original=np.sum(residual(vector)**2)
        for index in range(1,5):
            vector,audit=solve_round(vector,residual,lo,hi,solve,100,index)
            self.assertTrue(all(a['after']<=a['before']+1e-10 for a in audit))
        self.assertLess(np.sum(residual(vector)**2),original*1e-8)
        self.assertEqual([size for _,size in seen],[3,104]*4)
        np.testing.assert_allclose(vector[:3],2,atol=1e-5)
        np.testing.assert_allclose(vector[104:],1,atol=1e-5)

    def test_non_improving_solver_result_is_rejected(self):
        from types import SimpleNamespace
        v=np.zeros(105);bounds=np.full(105,10.)
        def bad(stage,fun,initial,**kw):
            return SimpleNamespace(x=initial+1,nfev=1,success=False)
        result,audit=solve_round(v,lambda a:a,-bounds,bounds,bad,10,1)
        np.testing.assert_array_equal(result,v)
        self.assertFalse(any(a['accepted'] for a in audit))
