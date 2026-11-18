"""全射线密集验收必须同时保存局部风险，防止整体统计掩盖。"""
import unittest
import numpy as np


class DenseAuditTests(unittest.TestCase):
    def test_global_nonregression_does_not_hide_new_local_spike(self):
        from native_dense_audit import dense_report
        reference=np.full((2,33,3),.4)
        reference[1,::2]=[1,0,0];reference[1,1::2]=[0,0,1]
        candidate=reference.copy();candidate[0,16]=[0,1,0]
        report=dense_report(reference,candidate)
        self.assertEqual(report['global_exceedances'],[])
        self.assertGreater(len(report['local_raw_exceedances']),0)
        self.assertGreater(len(report['local_quantization_exceedances']),0)
        same=dense_report(reference,reference)
        self.assertEqual(same['global_exceedances'],[])
        self.assertEqual(same['local_raw_exceedances'],[])
        self.assertEqual(same['local_quantization_exceedances'],[])
