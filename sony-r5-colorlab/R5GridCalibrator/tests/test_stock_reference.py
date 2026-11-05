import sys
import unittest
from fractions import Fraction as Q
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stock_reference as s


class StockReferenceTests(unittest.TestCase):
    def test_original_nodes_interiors_planar_and_native_packing(self):
        report = s.audit()
        self.assertTrue(report['passed'])
        self.assertEqual(report['exact_point_counts'], dict(
            nodes=405, half_step_faces_edges_and_cell_centers=2601, rational_interiors=64))
        self.assertEqual(report['native_packed_bytes'], 1620)
        self.assertFalse(report['native_ISP_pixel_algorithm_proven'])
        self.assertFalse(report['Edit_equivalence_proven'])

    def test_swapped_chroma_axes_are_detected_by_local_exception(self):
        # Most of stock04 is symmetric, but this substitution moves its one
        # asymmetric +1. Full-node validation must detect the wrong axis order.
        def swapped(point):
            a, b, c = point
            d0, d1, d2 = s.compact((a, c, b))
            return d0, d2, d1
        with self.assertRaisesRegex(ValueError, 'stock04 nodes mismatch'):
            s.verify_candidate(swapped)

    def test_omitted_local_tent_is_detected(self):
        def missing(point):
            a, b, c = point
            d0, d1, d2 = s.compact(point)
            return d0, d1, d2 - max(0, 1-abs(a-1))*max(0, 1-abs(b-4))*max(0, 1-abs(c-3))
        with self.assertRaisesRegex(ValueError, 'stock04 nodes mismatch'):
            s.verify_candidate(missing)

    def test_fractional_special_tent_and_upper_edges(self):
        for point in [(Q(1,2), Q(7,2), Q(7,2)), (Q(31,10), Q(73,10), Q(79,10)),
                      (4,8,8), (0,0,0), (1,4,3)]:
            self.assertEqual(s.compact(point), s.dense(point))
        self.assertEqual(s.compact((1,4,3)), (0,0,4))
        for point in [(-1,0,0), (0,9,0), (0,0,float('nan')), (0,1)]:
            with self.assertRaises(ValueError):
                s.compact(point)

    def test_hash_pin_and_native_strength_floor(self):
        original = s.read_stock04()
        corrupted = bytes([original[0] ^ 1]) + original[1:]
        with patch.object(Path, 'read_bytes', return_value=corrupted):
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                s.read_stock04()
        import struct
        raw = bytearray(1215)
        raw[0] = 255  # -1 must remain -1 under arithmetic >>, not round to zero.
        word = struct.unpack('<405I', s.pack_hardware(bytes(raw), 1))[0]
        self.assertEqual(word >> 22 & 127, 127)
        with self.assertRaises(ValueError):
            s.pack_hardware(bytes([127])*1215)


if __name__ == '__main__':
    unittest.main()
