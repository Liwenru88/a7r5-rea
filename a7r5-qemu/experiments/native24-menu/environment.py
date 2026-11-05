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
AP_SHA = 'c4efcaa0ac1578a719f11f36d6a316c63ff1d76aa8fb145c78895005b723cda1'
CP_SHA = '31f85fa3d3015d3d553abb6540a98ae67e280631c0bff73cd4eada7fe02db0b2'
BIN_SHA = '5287043ca32c315705ac99c67e8dfd7c5cbd3dea920e5c64505a81edc3f7fd46'


def validate_identity(record):
    if (record.get('schema'), record.get('model'), record.get('AP_sha256'), record.get('CP_sha256')) != (
            'native24-menu/1', 'ILCE-7RM5', AP_SHA, CP_SHA):
        raise ValueError('24槽清单固定身份不符')
    if record.get('readonly_AP_state_bytes') != 2320 or not record.get('synthetic_recipes'):
        raise ValueError('24槽只读状态／测试配方标识不符')


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
        if set(self.loading_inputs) != {'cp', 'receiver', 'bin'} or digest(self.loading_inputs['cp']) != CP_SHA or digest(self.loading_inputs['bin']) != BIN_SHA:
            raise ValueError('24槽加载组件不符')
        build = verified({'files': {'build': record['native24_build']}})['build']
        receipt = json.loads(build.read_text())
        if (receipt['AP_sha256'], receipt['CP_sha256'], receipt['CP_heap_bytes'], receipt['installable']) != (AP_SHA, CP_SHA, 947000, False):
            raise ValueError('24槽构建来源不符')
        return inputs


# 仅扩大只读快照的名称区和尾字段位置，不改变采样／传输／调度行为。
body = inspect.getsource(parent.MenuVM.loading_state)
body = '\n'.join(line[4:] if line.startswith('    ') else line for line in body.splitlines())
body = body.replace('(1224,1264)', '(2320,)').replace('range(12)', 'range(24)').replace('size==1264', 'size==2320')
for before, after in [('raw,1184', 'raw,2240'), ('raw,1224', 'raw,2280'), ('raw[1228:1252]', 'raw[2284:2308]'), ('raw,1252', 'raw,2308')]:
    body = body.replace(before, after)
namespace = dict(parent.__dict__)
exec(compile(body, 'native24-readonly-state-parser', 'exec'), namespace)
MenuVM.loading_state = namespace['loading_state']
