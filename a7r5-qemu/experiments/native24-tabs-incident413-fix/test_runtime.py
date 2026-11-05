"""新候选固定身份及旧模型拒绝保持，未知输入不能进入运行阶段。"""
import copy
import unittest
import environment as env


class IdentityTests(unittest.TestCase):
    def test_exact_candidate_only(self):
        record = dict(schema='native24-tabs-incident413-fix/1', model='ILCE-7RM5', AP_sha256=env.AP_SHA,
                      CP_sha256=env.CP_SHA, icon_sha256=env.ICON_SHAS, readonly_AP_state_bytes=2444, synthetic_recipes=False,actual_recipes=True,recipe_set='installed12')
        env.validate_identity(record)
        for key, bad in [('schema', 'native12-410-menu/1'), ('schema', 'native24-stable-menu/2'),
                         ('AP_sha256', 'af7e99791309be845d1c981598b521f6766aca266a7ccae96a067e590bc4dbe3'),
                         ('AP_sha256', env.parent.UNIFIED_AP_SHA),
                         ('CP_sha256', env.parent.CP_SHA), ('readonly_AP_state_bytes', 1264),
                         ('readonly_AP_state_bytes', 2328),
                         ('readonly_AP_state_bytes', 2404),
                         ('synthetic_recipes', True)]:
            with self.subTest(key=key):
                changed = copy.deepcopy(record)
                changed[key] = bad
                with self.assertRaisesRegex(ValueError, '不符'):
                    env.validate_identity(changed)
        for bad in (None, {}, dict(env.ICON_SHAS, **{'image_00_32_IPSX.uxc': 'a65afbdb43e4eca063baacdd77f822890b521c509ec383eacfaa8abe20971bc5'})):
            changed=copy.deepcopy(record);changed['icon_sha256']=bad
            with self.assertRaisesRegex(ValueError,'不符'):
                env.validate_identity(changed)
        changed=copy.deepcopy(record);changed['recipe_set']='unknown'
        with self.assertRaisesRegex(ValueError,'不符'):
            env.validate_identity(changed)

    def test_built_manifest_receipt_and_files_are_verified(self):
        from pathlib import Path
        for folder in ('native24-tabs-incident413-fix-20261103-02',):
            obj = type('Candidate', (), {'manifest_path': env.LAB / ('build/'+folder+'/manifest.json')})()
            files = env.MenuVM.runtime_inputs(obj)
            self.assertEqual(set(files), {'binary', 'kernel', 'initrd', 'dtb', 'gpe'})
            self.assertEqual(set(obj.loading_inputs), {'cp', 'receiver', 'bin'})


if __name__ == '__main__':
    unittest.main()
