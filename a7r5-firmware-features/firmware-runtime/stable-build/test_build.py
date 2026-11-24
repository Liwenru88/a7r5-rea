"""4.31 补丁与树组装离线单元测试。"""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class StableBuildTests(unittest.TestCase):
    def test_stable_sources_are_copied_without_reapplying_patches(self):
        builder = _load(HERE / 'build.py', 'test_stable_sources')
        source = Path('a7r5-firmware-features/firmware-runtime/runtime/unified-look.c')
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / 'build-tree'
            builder.prepare_build_tree(tree)
            self.assertTrue((tree / source).is_file())
            self.assertEqual((tree / source).read_bytes(), (builder.SOURCE_TREE / source).read_bytes())

    def test_stable_launcher_rejects_version_override(self):
        result = subprocess.run(
            [str(ROOT / 'scripts/build_from_400.sh'), '--version', '4.32'],
            env=dict(os.environ, PYTHON_BIN=sys.executable),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn('unrecognized arguments: --version', result.stderr)

    def test_stable_sources_include_current_firmware_features(self):
        builder = _load(HERE / 'build.py', 'test_stable_build')
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / 'tree431'
            builder.prepare_build_tree(tree)

            unified_c = (tree / 'a7r5-firmware-features/firmware-runtime/runtime/unified-look.c').read_text(encoding='utf-8')
            self.assertIn('bank_unavailable_only(void)', unified_c)
            self.assertIn('(!r5_filter_recovery_required() || bank_unavailable_only())', unified_c)
            self.assertIn('case 0x0200ab65u:return "2.35:1";', unified_c)

            probe_c = (tree / 'a7r5-firmware-features/firmware-runtime/runtime/r5_stage413_probe.c').read_text(encoding='utf-8')
            self.assertIn('now-start>=3000u', probe_c)
            self.assertIn('poll==30', probe_c)

            thread_c = (tree / 'a7r5-firmware-features/firmware-runtime/runtime/r5_stage413_thread.c').read_text(encoding='utf-8')
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

            cp_compact = (tree / 'a7r5-firmware-features/firmware-runtime/aspect/cp_aspect_compact.c').read_text(encoding='utf-8')
            notify_fn = cp_compact.split('void r5_cp_notify_jpeg', 1)[1].split('uint32_t r5_cp_raw_emb', 1)[0]
            self.assertIn('uint16_t w = wh[0], h = wh[1];', notify_fn)
            self.assertNotIn('task + MAIN_ROI', notify_fn)

    def test_default_24_slot_filter_bundle_matches_container_package(self):
        packager = _load(HERE / 'container_package.py', 'test_stable_container_package')
        payload = packager.compile_default_filters()
        self.assertEqual(len(payload), 58976)
        self.assertEqual(payload[:8], b'R5CUST5\0')
        audit = json.loads((HERE / 'filters/export_audit.json').read_text(encoding='utf-8'))
        self.assertEqual(hashlib.sha256(payload).hexdigest(), audit['binary_sha256'])


if __name__ == '__main__':
    unittest.main()
