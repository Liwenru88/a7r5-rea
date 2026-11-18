"""研究搜索半径只改变后续可达范围，不能瞬移配方或破坏默认行为。"""
import unittest
import torch

from native_search_radius import SearchRadius


class RadiusTests(unittest.TestCase):
    def test_expansion_requires_consecutive_confirmations(self):
        p=torch.nn.Parameter(torch.full((1448,),.6,dtype=torch.float64))
        radius=SearchRadius(p,adaptive=True);radius.confirmations=2
        optimizer=torch.optim.Adam([p])
        self.assertEqual(radius.expand(p,optimizer,feasible=True,improved=True),[])
        self.assertEqual(radius.expand(p,optimizer,feasible=False,improved=True),[])
        self.assertEqual(radius.expand(p,optimizer,feasible=True,improved=True),[])
        events=radius.expand(p,optimizer,feasible=True,improved=True)
        self.assertEqual(len(events),4)

    def test_fixed_radius_matches_old_forward(self):
        x=torch.linspace(-1,1,1448,dtype=torch.float64)
        radius=SearchRadius(x,adaptive=False)
        self.assertTrue(torch.equal(radius.delta(x),.25*torch.tanh(x/.25)))

    def test_expand_preserves_recipe_and_rescales_adam_moments(self):
        p=torch.nn.Parameter(torch.zeros(1448,dtype=torch.float64))
        radius=SearchRadius(p,adaptive=True)
        with torch.no_grad():p[104:233]=.6
        optimizer=torch.optim.Adam([p]);p.grad=torch.ones_like(p);optimizer.step()
        before=radius.delta(p).detach().clone();old=p.detach().clone()
        old_m=optimizer.state[p]['exp_avg'].clone();old_v=optimizer.state[p]['exp_avg_sq'].clone()
        events=radius.expand(p,optimizer,feasible=True,improved=True)
        self.assertEqual([x['group'] for x in events],['gamma'])
        self.assertTrue(torch.allclose(before,radius.delta(p),atol=1e-14,rtol=0))
        self.assertTrue(torch.equal(p[:104],old[:104]))
        self.assertTrue(torch.equal(p[233:],old[233:]))
        ratio=(1-(before[104:233]/.375).square())/(1-(before[104:233]/.25).square())
        self.assertTrue(torch.allclose(optimizer.state[p]['exp_avg'][104:233],old_m[104:233]*ratio))
        self.assertTrue(torch.allclose(optimizer.state[p]['exp_avg_sq'][104:233],old_v[104:233]*ratio.square()))
        for _ in range(5):radius.expand(p,optimizer,feasible=True,improved=True)
        self.assertLessEqual(float(radius.values.max()),.5)

    def test_bad_or_stalled_candidates_cannot_expand(self):
        for feasible,improved in ((False,True),(True,False)):
            p=torch.nn.Parameter(torch.full((1448,),.8));r=SearchRadius(p,adaptive=True)
            optimizer=torch.optim.Adam([p]);old=p.detach().clone()
            self.assertEqual(r.expand(p,optimizer,feasible=feasible,improved=improved),[])
            self.assertTrue(torch.equal(old,p))


if __name__=='__main__':unittest.main()
