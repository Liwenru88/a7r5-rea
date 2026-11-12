import unittest
import numpy as np

from hue_direction import HueDirectionBank
from gpu_tensor import TensorTools


def hsv_rgb(h, s, v):
    import colorsys
    return np.array([colorsys.hsv_to_rgb(float(a), float(b), float(c)) for a, b, c in zip(h, s, v)])


class HueDirectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows=[];targets=[]
        for hue in np.arange(24)/24:
            value=np.linspace(.08,1,24)
            rows.append(hsv_rgb(np.full(24,hue),np.full(24,.82),value))
            targets.append(hsv_rgb((hue+.03*value**2)%1,np.full(24,.82),value))
        cls.design=np.concatenate(rows);cls.target=np.concatenate(targets)
        cls.split=np.full(len(cls.design),'train');cls.kind=np.full(len(cls.design),'hue24_tonal')
        cls.bank=HueDirectionBank(cls.design,cls.target,cls.split,cls.kind)

    def test_target_direction_is_zero_cost_and_reverse_is_penalized(self):
        self.assertEqual(self.bank.report(self.target[self.bank.source_indices],30)['opposite_edges'],0)
        reverse=[]
        for hue in np.arange(24)/24:
            value=np.linspace(.08,1,24)
            reverse.append(hsv_rgb((hue-.03*value**2)%1,np.full(24,.82),value))
        reverse=np.concatenate(reverse)
        report=self.bank.report(reverse[self.bank.source_indices],30)
        self.assertGreater(report['opposite_edges'],0)
        self.assertGreater(self.bank.cost(reverse[self.bank.source_indices],30),0)

    def test_target_turns_are_preserved_per_edge(self):
        target=self.target.copy()
        # A target-defined local reversal changes the trusted direction rather
        # than being flattened into a globally monotone track.
        target[10:14]=target[10:14][::-1]
        bank=HueDirectionBank(self.design,target,self.split,self.kind)
        self.assertEqual(bank.report(target[bank.source_indices],30)['opposite_edges'],0)

    def test_tensor_matches_numpy_and_has_finite_gradient(self):
        import torch
        tools=TensorTools('cpu',torch.float64)
        ordered=self.target[self.bank.source_indices]
        value=tools.tensor(ordered).requires_grad_(True)
        loss=self.bank.tensor_loss(tools,value,30)
        self.assertAlmostEqual(float(loss.detach())*255**2,self.bank.cost(ordered,30),places=12)
        loss.backward()
        self.assertTrue(bool(torch.isfinite(value.grad).all()))

    def test_final_grid_optimizer_reports_same_constraint(self):
        from continuity_grid import constrain
        from measured_response import default_response
        grid=np.zeros((405,3),np.int8)
        base=self.design[:8];target=base.copy();weights=np.ones(len(base))
        hue_base=self.design[self.bank.source_indices]
        result,audit=constrain(grid,base,target,weights,default_response(),0,None,
            evaluations=1,device='cpu',hue_direction=(self.bank,hue_base,30))
        self.assertEqual(result.shape,(405,3))
        self.assertEqual(audit['hue_direction']['policy'],'target-hue-offset-direction/1')


if __name__=='__main__':unittest.main()
