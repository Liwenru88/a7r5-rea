"""新候选固定身份及旧模型拒绝保持，未知输入不能进入运行阶段。"""
import copy
import unittest
import environment as env


class IdentityTests(unittest.TestCase):
    def test_exact_candidate_only(self):
        record = dict(schema='native24-menu/1', model='ILCE-7RM5', AP_sha256=env.AP_SHA,
                      CP_sha256=env.CP_SHA, readonly_AP_state_bytes=2320, synthetic_recipes=True)
        env.validate_identity(record)
        for key, bad in [('schema', 'native12-410-menu/1'), ('AP_sha256', env.parent.UNIFIED_AP_SHA),
                         ('CP_sha256', env.parent.CP_SHA), ('readonly_AP_state_bytes', 1264),
                         ('synthetic_recipes', False)]:
            with self.subTest(key=key):
                changed = copy.deepcopy(record)
                changed[key] = bad
                with self.assertRaisesRegex(ValueError, '不符'):
                    env.validate_identity(changed)

    def test_built_manifest_receipt_and_files_are_verified(self):
        from pathlib import Path
        obj = type('Candidate', (), {'manifest_path': env.LAB / 'build/native24-menu-20261103-02/manifest.json'})()
        files = env.MenuVM.runtime_inputs(obj)
        self.assertEqual(set(files), {'binary', 'kernel', 'initrd', 'dtb', 'gpe'})
        self.assertEqual(set(obj.loading_inputs), {'cp', 'receiver', 'bin'})


if __name__ == '__main__':
    unittest.main()
