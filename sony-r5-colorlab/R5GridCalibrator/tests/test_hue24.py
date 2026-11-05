import colorsys,sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import model
from quality import balanced_weights,color_groups,grouped_metrics,weighting_report
class Hue24Tests(unittest.TestCase):
 def colors(self):
  return np.array([colorsys.hsv_to_rgb((k+.5)/24,.7,.8) for k in range(24) for _ in range(k+1)]+[[.3,.3,.3]]*40)
 def test_equal_sector_mass_and_split_isolation(self):
  a=self.colors();x=np.tile(a,(3,1));ids=np.zeros(len(x),int);split=np.repeat([0,1,2],len(a));w=balanced_weights(x,ids,split,hue24=True)
  _,neutral,hue=color_groups(x,24);sector=np.where(neutral,24,hue)
  for k in range(3):np.testing.assert_allclose(np.bincount(sector[split==k],weights=w[split==k],minlength=25),np.full(25,1/25),atol=1e-12)
  changed=x.copy();changed[split!=0]=[.1,.9,.2];v=balanced_weights(changed,ids,split,hue24=True);np.testing.assert_array_equal(w[split==0],v[split==0])
  report=weighting_report(x,ids,split,w);self.assertEqual(len(report['per_pair_split']),3)
 def test_default_unchanged_and_24_metrics(self):
  x=self.colors();ids=np.zeros(len(x),int);split=np.zeros(len(x),int)
  np.testing.assert_array_equal(balanced_weights(x,ids,split),balanced_weights(x,ids,split,hue24=False))
  metrics=grouped_metrics(x,x,x,np.ones(len(x),bool),24);self.assertEqual(len(metrics),26)
  self.assertEqual(sum(v['count'] for k,v in metrics.items() if k.startswith('hue_')),300)
  self.assertTrue(all(v['metrics']['rmse']==0 for v in metrics.values()))
  for value in ['yes',1,None]:
   with self.assertRaises(ValueError):model.optimization_options(dict(hue24_balance=value))
