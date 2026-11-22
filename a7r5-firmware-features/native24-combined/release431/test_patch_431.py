"""4.31 补丁与树组装离线单元测试。"""
import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Release431PatchTests(unittest.TestCase):
    def test_prepare_431_build_tree_applies_all_patches_cleanly(self):
        builder = _load(HERE / 'build_431_from_400.py', 'test_build_431')
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / 'tree431'
            receipt = builder.prepare_431_build_tree(tree)
            self.assertEqual(receipt['schema'], 'release431-tree-patch/1')
            self.assertEqual(len(receipt['modified']), 11)

            unified_c = (tree / 'a7r5-firmware-features/native24-combined/runtime/unified-look.c').read_text(encoding='utf-8')
            self.assertIn('bank_unavailable_only(void)', unified_c)
            self.assertIn('(!r5_filter_recovery_required() || bank_unavailable_only())', unified_c)
            self.assertIn('case 0x0200ab65u:return "2.35:1";', unified_c)

            probe_c = (tree / 'a7r5-firmware-features/native24-combined/runtime/r5_stage413_probe.c').read_text(encoding='utf-8')
            self.assertIn('now-start>=3000u', probe_c)
            self.assertIn('poll==30', probe_c)

            thread_c = (tree / 'a7r5-firmware-features/native24-combined/runtime/r5_stage413_thread.c').read_text(encoding='utf-8')
            self.assertIn('for(poll=0;poll<8&&r5_session_current();poll++){', thread_c)

            ap_menu_c = (tree / 'a7r5-firmware-features/photo-aspect-ratios/src/ap_menu.c').read_text(encoding='utf-8')
            self.assertIn('ASPECT_PRIVATE_FIRST = 0x1640,', ap_menu_c)

            ap_menu_s = (tree / 'a7r5-firmware-features/photo-aspect-ratios/src/ap_menu.S').read_text(encoding='utf-8')
            self.assertNotIn('#0x600', ap_menu_s)
            self.assertEqual(ap_menu_s.count('#0x640'), 3)

            build_ap = (tree / 'a7r5-firmware-features/photo-aspect-ratios/src/build_ap.py').read_text(encoding='utf-8')
            self.assertIn('FIRST_ROW = 0x1640', build_ap)
            self.assertIn('SELECTION = 0x8f13000', build_ap)
            self.assertIn('state_size = 0x8f00000 + shift, 0x8f10000 + shift, 0x3300', build_ap)

            ap_ld = (tree / 'a7r5-firmware-features/photo-aspect-ratios/src/ap.ld').read_text(encoding='utf-8')
            self.assertIn('aspect_selection = 0x8f13000;', ap_ld)
            self.assertIn('aspect_registrations = 0x8f13008;', ap_ld)
            self.assertIn('aspect_guide_slots = 0x8f13068;', ap_ld)
            self.assertIn('aspect_session = 0x8f131a0;', ap_ld)

            avcam_views_c = (tree / 'a7r5-firmware-features/photo-aspect-ratios/src/avcam_views.c').read_text(encoding='utf-8')
            self.assertIn('aspect_match_custom_wh(uint32_t w, uint32_t h)', avcam_views_c)
            self.assertIn('{3120, 1104}, {3120, 1152}, {2608, 2080}', avcam_views_c)
            self.assertIn('{2432, 2080}, {3120, 1632}, {3120, 1328}', avcam_views_c)

            avcam_views_s = (tree / 'a7r5-firmware-features/photo-aspect-ratios/src/avcam_views.S').read_text(encoding='utf-8')
            self.assertIn('mov w3, w21', avcam_views_s)
            self.assertNotIn('mov w3, w0', avcam_views_s)

            cp_compact = (tree / 'a7r5-firmware-features/native24-combined/release431/cp_aspect_compact.c').read_text(encoding='utf-8')
            notify_fn = cp_compact.split('void r5_cp_notify_jpeg', 1)[1].split('uint32_t r5_cp_raw_emb', 1)[0]
            self.assertIn('uint16_t w = wh[0], h = wh[1];', notify_fn)
            self.assertNotIn('task + MAIN_ROI', notify_fn)


if __name__ == '__main__':
    unittest.main()
