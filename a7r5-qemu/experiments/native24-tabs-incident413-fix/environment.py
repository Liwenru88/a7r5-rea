"""独立24槽客体；固定新组件身份，复用原沙箱和无成像完成的服务边界。"""
import importlib.util
import inspect
import json
from pathlib import Path
import struct

LAB = Path(__file__).resolve().parents[2]
ROOT = LAB.parent
OLD = LAB / 'experiments/native12-410-menu'
spec = importlib.util.spec_from_file_location('native24_parent_environment', OLD / 'environment.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
digest, fact, save, verified = parent.digest, parent.fact, parent.save, parent.verified
AP_SHA = '1f7fda3baf1afbe2badaee5007383839c5843b67023e546c10edbc70d28da58e'
CP_SHA = '35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300'
ICON_SHAS = {'image_00_23_IPSX.uxc': '202a5aa8fb0e3a26b7d2018c56c2ea8ab048ed2dc622179c9f092467f52646f6',
             'image_00_32_IPSX.uxc': '7adc49cf46a99802e8e68e06455d813730ff0f32c4efe96f76bd80161e442b2c'}
BIN_SHA = '19e020fa48c79643aaf9526e9c720d38ec5a92c3df11d0852b0a93a25ee880b6'
EMPTY_BIN_SHA = '17408d7d5518c5ddc465a645f350a9b59eaa9b043bcd43a9ea7855e624d91a84'


def validate_identity(record):
    if (record.get('schema'), record.get('model'), record.get('AP_sha256'), record.get('CP_sha256')) != (
            'native24-tabs-incident413-fix/1', 'ILCE-7RM5', AP_SHA, CP_SHA):
        raise ValueError('24槽清单固定身份不符')
    if record.get('readonly_AP_state_bytes') != 2444 or (record.get('synthetic_recipes') is not False or record.get('actual_recipes') is not True):
        raise ValueError('24槽只读状态／测试配方标识不符')
    if record.get('recipe_set') != 'installed12':
        raise ValueError('配方场景固定身份不符')
    if record.get('icon_sha256') != ICON_SHAS:
        raise ValueError('F0图标固定身份不符')


class MenuVM(parent.MenuVM):
    def runtime_inputs(self):
        if not self.manifest_path.is_relative_to(LAB / 'build'):
            raise ValueError('清单路径越界')
        record = json.loads(self.manifest_path.read_text())
        validate_identity(record)
        inputs = verified(record)
        if set(inputs) != {'binary', 'kernel', 'initrd', 'dtb', 'gpe'}:
            raise ValueError('24槽研究输入不全')
        self.loading_inputs = verified({'files': record['loading_inputs']})
        expected_bin = BIN_SHA
        if set(self.loading_inputs) != {'cp', 'receiver', 'bin'} or digest(self.loading_inputs['cp']) != CP_SHA or digest(self.loading_inputs['bin']) != expected_bin:
            raise ValueError('24槽加载组件不符')
        build = verified({'files': {'build': record['native24_build']}})['build']
        receipt = json.loads(build.read_text())
        if any(receipt['components'][name]['sha256'] != expected for name, expected in ICON_SHAS.items()):
            raise ValueError('F0图标构建来源不符')
        if (receipt['AP_sha256'], receipt['CP_sha256'], receipt['CP_heap_bytes'], receipt['installable']) != (AP_SHA, CP_SHA, 947000, False):
            raise ValueError('24槽构建来源不符')
        if receipt.get('stability_revision') != 1:
            raise ValueError('稳定性构建来源不符')
        if receipt.get('interaction_revision') != 1:
            raise ValueError('后台恢复构建来源不符')
        if receipt.get('parameter_revision') != 1:
            raise ValueError('八项调参构建来源不符')
        if receipt.get('tabs_revision') != 1:
            raise ValueError('分组Tab构建来源不符')
        return inputs


# 仅扩大只读快照的名称区和尾字段位置，不改变采样／传输／调度行为。
body = inspect.getsource(parent.MenuVM.loading_state)
body = '\n'.join(line[4:] if line.startswith('    ') else line for line in body.splitlines())
body = body.replace('(1224,1264)', '(2444,)').replace('range(12)', 'range(24)').replace('size==1264', 'size==2444')
for before, after in [('raw,1184', 'raw,2240'), ('raw,1224', 'raw,2280'), ('raw[1228:1252]', 'raw[2284:2308]'), ('raw,1252', 'raw,2308')]:
    body = body.replace(before, after)
body = body.replace("save(path.with_suffix('.json'),state)", "state['native_E4_inflight']=struct.unpack_from('<I',raw,2320)[0]\n    state['recovery_required']=struct.unpack_from('<I',raw,2324)[0]\n    state['tune']={'slot':struct.unpack_from('<I',raw,2328)[0],'status':struct.unpack_from('<I',raw,2332)[0],'values':list(struct.unpack_from('<8i',raw,2336)),'defaults':list(struct.unpack_from('<8i',raw,2368)),'unapplied':struct.unpack_from('<I',raw,2400)[0]}\n    save(path.with_suffix('.json'),state)")
namespace = dict(parent.__dict__)
body = body.replace("save(path.with_suffix('.json'),state)", "state['tabs']=dict(zip(('active','focus','group','browse_only','last_factory','last_custom','mid','revision','command_sequence'),struct.unpack_from('<9I',raw,2404)))\n    state['current_screen']=struct.unpack_from('<I',raw,2440)[0]\n    save(path.with_suffix('.json'),state)")
exec(compile(body, 'native24-readonly-state-parser', 'exec'), namespace)
MenuVM.loading_state = namespace['loading_state']
