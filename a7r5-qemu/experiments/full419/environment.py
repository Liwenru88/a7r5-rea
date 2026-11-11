"""只接受经独立解包并与构建锁一致的 4.19 全功能组件。"""
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / 'shutter-dual-profile'
sys.path.insert(0, str(PARENT))
spec = importlib.util.spec_from_file_location('full419_sound_environment', PARENT / 'environment.py')
sound = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sound)
LAB, ROOT = sound.LAB, sound.ROOT
save, fact, digest, verified = sound.save, sound.fact, sound.digest, sound.verified


def checked_lock(record):
    lock_path = verified({'files': {'lock': record['full419_lock']}})['lock']
    lock = json.loads(lock_path.read_text())
    if (lock['version'] != '4.19' or len(lock['plan']['modules']) != 10
            or lock['plan'].get('variants') != {'photo-electronic-shutter-sound': 'custom-dual-full'}):
        raise ValueError('不是已登记的 4.19 全功能构建锁')
    ap = lock['expected']['components']['usr/lib/appFw.so']['sha256']
    cp = lock['expected']['components']['cpapp-b.bin']['sha256']
    if (record['AP_sha256'], record['CP_sha256'], record['source_DAT_sha256']) != (ap, cp, lock['dat']['sha256']):
        raise ValueError('4.19 客体组件与 DAT 构建锁不符')
    return lock


class MenuVM(sound.MenuVM):
    def runtime_inputs(self):
        if self.manifest_path.resolve().parent.parent != LAB / 'build':
            raise ValueError('4.19 清单不在独立 build 目录')
        record = json.loads(self.manifest_path.read_text())
        if (record['schema'], record['model']) != ('r5-full419-qemu/1', 'ILCE-7RM5'):
            raise ValueError('4.19 客体清单身份不符')
        lock = checked_lock(record)
        inputs = verified(record)
        if set(inputs) != {'binary', 'kernel', 'initrd', 'dtb', 'gpe'}:
            raise ValueError('4.19 客体材料不完整')
        default = json.loads((LAB / 'runtime/manifest.json').read_text())
        for key in ('binary', 'kernel', 'gpe'):
            if record['files'][key]['sha256'] != default['files'][key]['sha256']:
                raise ValueError('固定客体材料不符 ' + key)
        self.loading_inputs = verified({'files': record['loading_inputs']})
        if digest(self.loading_inputs['cp']) != record['CP_sha256']:
            raise ValueError('4.19 CP 侧车组件不符')
        if digest(self.loading_inputs['bin']) != lock['expected']['companion']['sha256']:
            raise ValueError('4.19 配方与随包配方不符')
        candidate = verified({'files': {'build': record['candidate_build']}})['build']
        source = json.loads(candidate.read_text())
        if (source['AP_sha256'], source['CP_sha256'], source['sound_layout']) != (
                record['AP_sha256'], record['CP_sha256'], 'custom-dual-full'):
            raise ValueError('4.19 组件来源不符')
        return inputs
