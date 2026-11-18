"""整数配方复选只处理候选副本，基准与零操作必须逐字节保留。"""
import copy
import unittest
import numpy as np
import core


class PolishTests(unittest.TestCase):
    def test_grid_smoothing_isolates_channels_and_covers_all_spatial_axes(self):
        from native_integer_polish import polish_delta
        source=copy.deepcopy(core.presets()[0][0])
        source['grid_5x9x9']['coefficients']=np.zeros((3,5,9,9),dtype=int).tolist()
        pack=lambda e:core.compiler.pack(core.compiler.config([e],5))
        for channel in range(3):
            with self.subTest(channel=channel):
                candidate=copy.deepcopy(source)
                candidate['grid_5x9x9']['coefficients'][channel][2][4][4]=32
                before_source,before_candidate=pack(source),pack(candidate)
                result=polish_delta(source,candidate,grid_strength=1.)
                values=np.asarray(result['grid_5x9x9']['coefficients'])
                self.assertEqual(np.count_nonzero(np.delete(values,channel,axis=0)),0,'平滑不得串入其他颜色通道')
                for point in ((1,4,4),(2,3,4),(2,4,3)):
                    self.assertGreater(values[(channel,*point)],0,'三个空间轴均须传播邻域增量')
                self.assertEqual(pack(source),before_source)
                self.assertEqual(pack(candidate),before_candidate)

    def test_zero_operations_and_zero_alpha_preserve_recipe_bytes(self):
        from native_integer_polish import polish_delta
        source=core.presets()[0][0];candidate=copy.deepcopy(source)
        candidate['grid_5x9x9']['coefficients'][2][4][4][0]+=8
        pack=lambda x:core.compiler.pack(core.compiler.config([x],5))
        self.assertEqual(pack(polish_delta(source,candidate)),pack(candidate))
        self.assertEqual(pack(polish_delta(source,candidate,alpha=0)),pack(source))
        self.assertEqual(pack(polish_delta(source,source,grid_strength=.5,hue_strength=.5)),pack(source))

    def test_circular_hue_delta_smoothing_preserves_cc1_and_gamma(self):
        from native_integer_polish import polish_delta
        source=core.presets()[0][0];candidate=copy.deepcopy(source)
        candidate['block13'][0][0][0]+=32
        candidate['block13']=[copy.deepcopy(candidate['block13'][0]) for _ in range(3)]
        result=polish_delta(source,candidate,hue_strength=.5)
        delta=np.asarray(result['block13'])-np.asarray(source['block13'])
        self.assertGreater(delta[0,-1,0],0)
        self.assertLess(delta[0,0,0],32)
        self.assertEqual(result['gamma_native_129'],source['gamma_native_129'])
        self.assertEqual(result['cc1_delta'],source['cc1_delta'])
