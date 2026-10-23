"""注册表、上下文、输入语义与篡改不能越过正式白名单。"""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from input_registry import InputRegistry


class RegistryContract(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((ROOT / 'config/controls.json').read_text())
        self.manifest = json.loads((ROOT / 'runtime/manifest.json').read_text())
        self.registry = InputRegistry(self.document, self.manifest)

    def test_official_controls_and_c4_label(self):
        expected = {'SHUTTER_HALF', 'SHUTTER_FULL', 'POWER', 'FRONT_DIAL', 'LENS_RELEASE',
                    'SHOOT_SELECTOR', 'MODE_DIAL', 'REAR_DIAL_L', 'REAR_DIAL_R', 'MOVIE',
                    'C1', 'C2', 'C3', 'C4', 'AF_ON', 'AEL', 'JOYSTICK', 'FN', 'CONTROL_WHEEL',
                    'PLAYBACK', 'TOUCH', 'EYE_SENSOR', 'DIOPTER'}
        self.assertTrue(expected <= self.registry.controls.keys())
        self.assertIn('删除', self.registry.controls['C4']['label'])
        self.assertEqual(self.registry.controls['C2']['label'], 'C2 自定义键')

    def test_only_proven_actions_and_semantics_enabled(self):
        for control in self.registry.controls:
            request = {'action': 'input', 'control': control, 'event': 'tap', 'value': None}
            if control in ('UP', 'DOWN', 'LEFT', 'RIGHT', 'ENTER', 'MENU', 'C4'):
                self.assertEqual(self.registry.resolve(request), control)
            else:
                with self.subTest(control=control), self.assertRaises(ValueError):
                    self.registry.resolve(request)

    def test_release_hold_raw_codes_ranges_and_context_are_rejected(self):
        good = {'action': 'input', 'control': 'UP', 'event': 'tap', 'value': None}
        for change in ({'event': 'press'}, {'event': 'release'}, {'event': 'hold'},
                       {'event': 'rotate', 'value': 1000}, {'control': 3}, {'control': []},
                       {'value': True}, {'shell': 'anything'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.registry.resolve(dict(good, **change))
        with self.assertRaises(ValueError):
            self.registry.resolve(dict(good,control='C4'), context='shooting')
        for context in ('menu_option', 'menu'):
            self.assertEqual(self.registry.resolve(dict(good, control='C4'), context=context), 'C4')
        for context in ('unknown', 'guide', 'shooting'):
            self.assertFalse(self.registry.available('C4', context))

    def test_json_cannot_enable_unknown_code_and_fingerprint_mismatch_disables(self):
        document = copy.deepcopy(self.document)
        c4 = next(row for row in document['controls'] if row['id'] == 'MOVIE')
        c4.update(mapping_status='verified', behavior_status='pass', enabled_contexts=['menu'])
        registry = InputRegistry(document, self.manifest)
        self.assertFalse(registry.available('MOVIE'))
        document['input_fingerprint']['initrd'] = '0' * 64
        registry = InputRegistry(document, self.manifest)
        self.assertFalse(registry.available('UP'))
        document['controls'].append(document['controls'][0])
        with self.assertRaises(ValueError):
            InputRegistry(document, self.manifest)

    def test_function_keys_require_completed_shooting_context(self):
        for key in ('FN','DISP','PLAYBACK'):
            self.assertTrue(self.registry.available(key,'shooting_ready'),key)
            for context in ('shooting','unknown','initial_setup','menu'):
                self.assertFalse(self.registry.available(key,context),(key,context))
        self.assertTrue(self.registry.available('C4','setup_on_camera'))
        self.assertTrue(self.registry.available('RIGHT','menu_group'))
        self.assertFalse(self.registry.available('C4','menu_group'))


if __name__ == '__main__':
    unittest.main()
