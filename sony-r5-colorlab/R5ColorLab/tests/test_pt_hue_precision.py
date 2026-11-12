"""用保留的 Edit 边界反例保护原生色相索引精度。"""
import unittest

import numpy as np

import baseline
from edit_color_pipeline import RuntimeColor


class PTHuePrecisionTests(unittest.TestCase):
    def test_retained_edit_half_index_output(self):
        model = RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID))
        inputs = np.tile(np.array([4208, 1574, 6937], np.uint16), (1, 9, 1))
        np.testing.assert_array_equal(model.sectors(inputs), np.full((1, 9), 59))
        np.testing.assert_array_equal(
            model.color_only(inputs), np.tile([16383, 9795, 16383], (1, 9, 1)))


if __name__ == '__main__':
    unittest.main()
