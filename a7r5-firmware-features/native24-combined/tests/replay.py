"""复用已归档的CPU服务夹具，身份／符号／文件格式显式绑定24槽产物。"""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parents[1]
FEATURE = HERE / 'dependencies/native12-combined'
BUILD = Path(os.environ.get('A7R5_NATIVE24_BUILD', HERE.parents[1] / '.local/native24-runtime-20261103-05'))
sys.path[:0] = [str(FEATURE), str(FEATURE / 'tests')]
import runtime_support

runtime_support.BASELINE = BUILD
from runtime_support import AP
from cp_services import receiver_services


class CP(runtime_support.CP):
    def receiver_services(self, budget=1048576):
        receiver_services(self, budget)


def components():
    record = json.loads((BUILD / 'build.json').read_text())
    patch = record['unified']
    raw = (BUILD / 'appFw.so').read_bytes()
    import hashlib
    assert hashlib.sha256(raw).hexdigest() == record['AP_sha256'] == patch['target_sha256']
    cp = (BUILD / 'cpapp-b.bin').read_bytes()
    assert hashlib.sha256(cp).hexdigest() == record['CP_sha256']
    before = bytearray(raw[:patch['source_bytes']])
    for p in reversed(patch['patches']):
        data = bytes.fromhex(p['before'])
        before[p['offset']:p['offset'] + len(data)] = data
    assert hashlib.sha256(before).hexdigest() == patch['source_sha256']
    if folder := os.environ.get('A7R5_FINAL_READBACK'):
        final = Path(folder)
        manifest = json.loads((final / 'manifest.json').read_text())
        lock = json.loads((Path(os.environ['A7R5_FINAL_BUNDLE']) / 'lock.json').read_text())
        assert manifest['source'] == lock['dat'] and lock['version'] == '4.19'
        assert lock['plan']['native24']['sound_layout'] == 'custom-dual-full'
        raw = (final / 'components/usr/lib/appFw.so').read_bytes()
        cp = (final / 'components/cpapp-b.bin').read_bytes()
        for name, data in [('usr/lib/appFw.so', raw), ('cpapp-b.bin', cp)]:
            assert hashlib.sha256(data).hexdigest() == lock['expected']['components'][name]['sha256']
    if folder := os.environ.get('A7R5_COMPONENT_CAPTURE'):
        assert not os.environ.get('A7R5_FINAL_READBACK'), '组件回放不能冒充 DAT 回读'
        folder = Path(folder)
        manifest = json.loads((folder / 'manifest.json').read_text())
        assert manifest['schema'] == 'r5-operation-fixes-components/1'
        assert not manifest['installable'] and not manifest['camera_io']
        assert hashlib.sha256((BUILD / 'build.json').read_bytes()).hexdigest() == manifest['native24_build_sha256']
        data = (folder / 'capture-build.json').read_bytes()
        assert hashlib.sha256(data).hexdigest() == manifest['capture_build_sha256']
        capture = json.loads(data)

        def inverse(data, proof):
            assert hashlib.sha256(data).hexdigest() == proof['target_sha256']
            original = bytearray(data)
            for row in reversed(proof['patches']):
                at = row['offset']
                before, after = bytes.fromhex(row['before']), bytes.fromhex(row['after'])
                assert original[at:at + len(after)] == after
                original[at:at + len(before)] = before
            assert hashlib.sha256(original).hexdigest() == proof['source_sha256']
            return bytes(original)

        raw = (folder / 'appFw.so').read_bytes()
        cp = (folder / 'cpapp-b.bin').read_bytes()
        assert inverse(inverse(raw, manifest['AP']), capture['AP']) == (BUILD / 'appFw.so').read_bytes()
        assert hashlib.sha256(cp).hexdigest() == capture['CP_sha256'] == manifest['CP_sha256']
        prior_cp = inverse(cp, capture['CP_lens_af']) if capture['lens_af'] else cp
        assert inverse(prior_cp, capture['CP_aspect']) == (BUILD / 'cpapp-b.bin').read_bytes()
    return (raw, patch, bytes(before)), cp, record


def recipe():
    return (HERE / 'dependencies/native24-format/verification/2026-11-03-01/fixtures/R5NATIVE24.synthetic.test.BIN').read_bytes()


candidate, cp_raw, receipt = components()
helper = FEATURE / 'tests/unified_verification_support.py'
assert hashlib.sha256(helper.read_bytes()).hexdigest() == 'a4a73c18cc0c092b277eb40ba837b1e7f1d76fb47a6ca5d44c584ce63e4cfae4'
text = helper.read_text()
text = text.replace("AP_SHA = 'e833e0290fe60207cc5d9d2b7a0a66b253f7ab0db99ed12afb2a0c47ca6f72f1'", f"AP_SHA = '{hashlib.sha256(candidate[0]).hexdigest()}'")
text = text.replace("CP_SHA = 'bb8eeaaeb9d13a4687605de6e01ccbe4adc500f595d2f8dbfe886eedd8a643d0'", f"CP_SHA = '{hashlib.sha256(cp_raw).hexdigest()}'")
text = text.replace("assert len(sidecar) == 24 and sidecar[:8] == b'R5SEL4\\0\\0'",
    "if not sidecar:return (self.ap.call('r5_filter_selected'), self.cp.words(0x1a3945c + 8, 1)[0], None)\n"
    "        assert len(sidecar) == 24 and sidecar[:8] in (b'R5SEL4\\0\\0', b'R5SEL5\\0\\0')")
namespace = {'__name__': 'native24_replay_services'}
exec(compile(text, str(helper) + ':24-slot-derived', 'exec'), namespace)
# 新的多库夹具按实际长度分配；冻结十二槽夹具的固定步长不适用于24槽。
namespace['CP'] = CP
BaseReplay = namespace['UnifiedReplay']


class Replay(BaseReplay):
    def __init__(self, files=None, cards=None, native_selector=0):
        self.fail_selection_rename = False
        super().__init__(candidate, cp_raw, files=files, cards=cards, native_selector=native_selector)

    @staticmethod
    def storage_names():
        return {stem + suffix for stem in ('R5NATIVE', 'R5FILTER', 'R5RECOV', 'R5PREV', 'R5TUNE', 'R5TREC') for suffix in ('.BIN', '.NEW')}

    def openat(self, ap):
        assert ap.arg(0) == 9
        name, flags = ap.string(ap.arg(1)), ap.arg(2)
        assert name in self.storage_names()
        self.trace.append(['open', name, flags])
        if flags == 0x8000:
            return self.descriptor(name, self.files[name]) if name in self.files else self.error(2)
        assert flags == 0x80c1
        if name in self.files:
            return self.error(17)
        self.files[name] = b''
        return self.descriptor(name, b'', True)

    def rename(self, ap):
        if self.fail_selection_rename and ap.string(ap.arg(1)) == 'R5FILTER.NEW':
            self.fail_selection_rename = False
            self.trace.append(['injected_selection_rename_failure', 5])
            return self.error(5)
        assert ap.arg(0) == ap.arg(2) == 9
        source, target = ap.string(ap.arg(1)), ap.string(ap.arg(3))
        assert source in self.storage_names() and source.endswith('.NEW') and target == source[:-4] + '.BIN'
        self.files[target] = self.files.pop(source)
        self.trace.append(['publish', target])
        return 0

    def unlink(self, ap):
        assert ap.arg(0) == 9
        name = ap.string(ap.arg(1))
        assert name in self.storage_names()
        if name not in self.files:
            return self.error(2)
        del self.files[name]
        return 0

    def selected(self):
        import zlib
        sidecar = self.files.get('R5FILTER.BIN')
        file_slot = None
        if sidecar:
            assert len(sidecar) == 24 and sidecar[:8] in (b'R5SEL4\0\0', b'R5SEL5\0\0', b'R5SEL6\0\0')
            assert struct.unpack_from('<I', sidecar, 20)[0] == zlib.crc32(sidecar[:20] + bytes(4))
            file_slot = struct.unpack_from('<I', sidecar, 12)[0]
        cp_slot = self.cp.words(0x1a39464, 1)[0]
        view = self.cp.words(0x1a39458, 1)[0]
        assert (not view and not cp_slot) or (view and self.cp.words(view + 8, 1)[0] == cp_slot)
        return self.ap.call('r5_filter_selected') & 0xffffffff, cp_slot, file_slot

    def record(self, name):
        self.observe(name)
        folder = os.environ.get('A7R5_NATIVE24_EVIDENCE')
        if folder:
            target = Path(folder)
            target.mkdir(parents=True, exist_ok=True)
            (target / (name + '.json')).write_text(json.dumps({
                'AP_sha256': receipt['AP_sha256'], 'CP_sha256': receipt['CP_sha256'],
                'trace': self.trace, 'selected': self.selected(), 'open_handles': len(self.handles),
                'CP_heap_allocations': self.cp.heap_allocations,
                'files': {name: raw.hex() for name, raw in self.files.items()},
                'boundary': '真实新AP／CP；时钟／OS／原厂UI和E4外部执行为夹具，非实机成功',
            }, ensure_ascii=False, indent=2) + '\n')


def old_cp():
    original = runtime_support.BASELINE
    try:
        runtime_support.BASELINE = HERE.parents[1] / '.local/native12-combined-baseline-01'
        raw = (FEATURE / 'verification/2026-11-03-unified-rapid/components/cpapp-b.bin').read_bytes()
        return CP(raw)
    finally:
        runtime_support.BASELINE = original
