"""固定双组声音候选，继承已验收沙箱；不使用缺失归档的默认启动入口。"""
import importlib.util
import inspect
import json
from pathlib import Path
import struct
import sys

LAB = Path(__file__).resolve().parents[2]
ROOT = LAB.parent
sys.path[:0] = [str(LAB/'tools'), str(LAB/'experiments/native24-preview-idle')]
spec = importlib.util.spec_from_file_location('sound_qemu_parent', LAB/'experiments/native12-410-menu/environment.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
save, fact, digest, verified = parent.save, parent.fact, parent.digest, parent.verified
AP_SHA = '63072c53ff5d9ed4b32f01175667e057f85c1cc83c6d5067337354c6c52c6eda'
CP_SHA = '0e5ba4553064b1143a7d407b14dd9b5b353c98d77bd0d87bbfc8a4e490f4f523'


class MenuVM(parent.MenuVM):
    def runtime_inputs(self):
        if self.manifest_path.resolve().parent.parent != LAB/'build':
            raise ValueError('声音研究清单不在独立build目录')
        record = json.loads(self.manifest_path.read_text())
        if (record['schema'], record['model'], record['AP_sha256'], record['CP_sha256']) != (
                'r5-sound-dual-qemu/1', 'ILCE-7RM5', AP_SHA, CP_SHA):
            raise ValueError('声音研究固定组件不符')
        inputs = verified(record)
        if set(inputs) != {'binary', 'kernel', 'initrd', 'dtb', 'gpe'}:
            raise ValueError('声音研究输入不完整')
        default = json.loads((LAB/'runtime/manifest.json').read_text())
        for name in ('binary', 'kernel', 'gpe'):
            if record['files'][name]['sha256'] != default['files'][name]['sha256']:
                raise ValueError('固定基础输入发生变化 '+name)
        self.loading_inputs = verified({'files': record['loading_inputs']})
        if digest(self.loading_inputs['cp']) != CP_SHA:
            raise ValueError('CP侧车身份不符')
        build = verified({'files': {'build': record['candidate_build']}})['build']
        original = json.loads(build.read_text())
        if (original['AP_sha256'], original['CP_sha256'], original['sound_layout']) != (AP_SHA, CP_SHA, 'custom-dual-profile-candidate'):
            raise ValueError('声音候选来源不符')
        return inputs


body = inspect.getsource(parent.MenuVM.loading_state)
body = '\n'.join(line[4:] if line.startswith('    ') else line for line in body.splitlines())
body = body.replace('(1224,1264)', '(2400,)').replace('range(12)', 'range(24)').replace('size==1264', 'size==2400')
for old, new in [('raw,1184', 'raw,2240'), ('raw,1224', 'raw,2280'),
                 ('raw[1228:1252]', 'raw[2284:2308]'), ('raw,1252', 'raw,2308')]:
    body = body.replace(old, new)
names = ('count', 'mechanical_selected', 'electronic_selected', 'mechanical_volume', 'electronic_volume',
         'active_selected', 'active_volume', 'installs', 'starts', 'stops', 'installed_volume', 'installed_bytes', 'epoch')
extra = f"state['sound']=dict(zip({names!r},struct.unpack_from('<13I',raw,2320)))\n    state['mid']=struct.unpack_from('<I',raw,2312)[0]\n    "
body = body.replace("save(path.with_suffix('.json'),state)", extra+"save(path.with_suffix('.json'),state)")
namespace = dict(parent.__dict__)
exec(compile(body, 'sound-qemu-readonly-state', 'exec'), namespace)
MenuVM.loading_state = namespace['loading_state']
