"""固定分块捕获核心在普通文件上运行，不访问设备。"""
import hashlib
import json
import os
from collections import deque
from pathlib import Path
import struct
import subprocess

import pytest


@pytest.fixture(scope='module')
def capture_core(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    folder = tmp_path_factory.mktemp('capture-core')
    values = dict(CAPTURE_TARGET='capture_target', CAPTURE_RAM_PARENT='capture_parent',
                  CAPTURE_RAM_DIR='capture_directory', CAPTURE_PATH='capture_path')
    header = ''.join(f'#define {key} {value}\n' for key, value in values.items())
    header += '#define CAPTURE_PART_BYTES 16384\n#define CAPTURE_PART_COUNT 1532\n#define CAPTURE_SUMMARY " bytes=25100288 twice=1 chunks=1532 chunk_bytes=16384\\n"\n'
    header += '#define CAPTURE_BEGIN "BEGIN\\n"\n#define CAPTURE_END "END\\n"\n'
    header += '#define PRELOAD_A "' + '\\n'*512 + '"\n#define PRELOAD_B PRELOAD_A\n'
    (folder/'capture_config.h').write_text(header)
    binary = folder/'capture-core'
    built = subprocess.run(['/usr/bin/clang', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                    '-I', str(folder), '-I', str(root/'sources/trust'),
                    str(root/'tests/host_capture.c'), '-o', str(binary)], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    return binary


@pytest.mark.parametrize('fault', [0, 1, 7], ids=['complete', 'existing-part', 'memory-boundary'])
def test_native_capture_is_chunked_exact_and_never_overwrites(capture_core, tmp_path, fault):
    raw = bytes(range(256))*(25100288//256)
    source = tmp_path/'input.img'; source.write_bytes(raw)
    result = subprocess.run([str(capture_core), str(source), str(tmp_path), str(int(fault))],
                            capture_output=True, text=True, check=True)
    assert source.read_bytes() == raw and 'source_writes=0' in result.stdout
    if fault == 1:
        assert 'code=66 ' in result.stdout
        assert (tmp_path/'capture/partition.bin.part-0').read_bytes() == b'sentinel'
    else:
        assert 'code=0 ' in result.stdout
        pieces = [tmp_path/f'capture/partition.bin.part-{i}' for i in range(1532)]
        assert all(p.is_file() and p.stat().st_size <= 16384 for p in pieces)
        assert b''.join(p.read_bytes() for p in pieces) == raw
        assert hashlib.sha256(raw).hexdigest() in result.stdout
        assert 'chunks=1532 chunk_bytes=16384' in result.stdout


@pytest.mark.parametrize('fault', [2, 3, 4, 5, 6], ids=['low', 'unreadable', 'missing', 'wrong-unit', 'overflow'])
def test_capture_memory_guard_stops_before_directory_and_partition_reads(capture_core, tmp_path, fault):
    source = tmp_path/'input.img';source.write_bytes(b'sentinel')
    result = subprocess.run([str(capture_core), str(source), str(tmp_path), str(fault)],
                            capture_output=True, text=True, check=True)
    assert 'code=46 source_writes=0 source_reads=0' in result.stdout
    assert not (tmp_path/'capture').exists() and source.read_bytes() == b'sentinel'


@pytest.mark.parametrize('failed_upload', ['ticket', 'loader'])
def test_upload_open_failure_stops_before_next_stage_and_stop(tmp_path, baseline, failed_upload, ram_runtime):
    import device
    from capture_operation import Operation
    from transport import FileResultError
    package, _ = device.prepare_capture(tmp_path, 'c'*32, baseline)
    cfg = json.loads((package/'config.json').read_text())
    cfg.update(version_sha256=hashlib.sha256(b'version').hexdigest(),
               loader_sha256=hashlib.sha256(b'loader').hexdigest())
    (package/'config.json').write_text(json.dumps(cfg))
    uploaded = []
    class Files:
        def __init__(self, driver, operation, log):self.op = operation
        def read(self, path, limit):
            if path == '/version.txt':return b'version'
            if path == '/usr/lib/libJiritsu.so':return b'loader'
            if path == '/etc/ld.so.preload':return b'\n'*512
            if path.endswith('.ticket') and path in uploaded:return self.op.ticket
            raise FileResultError(0x10000006)
        def put(self, path, data):
            uploaded.append(path)
            if (failed_upload == 'ticket') == path.endswith('.ticket'):
                raise FileResultError(0x10000008)
    op = Operation(package, channel_factory=Files)
    destination = tmp_path/'session';destination.mkdir()
    report = {}
    with pytest.raises(FileResultError):op(None, destination, lambda *a, **k: None, report)
    expected = op.ticket_path if failed_upload == 'ticket' else '/tmp/jiritsu/libJit.so'
    assert report['upload_stage'] == failed_upload and report['upload_path'] == expected
    assert report['upload_complete'] is False and report['loader_execution_observed'] is False
    assert report['upload_failure']['result'] == '0x10000008'
    assert uploaded == [op.ticket_path] + ([] if failed_upload == 'ticket' else ['/tmp/jiritsu/libJit.so'])
    assert report['partition_writes'] == 0 and not op.safe_to_stop
    assert report['loader_upload_attempted'] is (failed_upload == 'loader')
    assert not (destination/'partition1.logical.bin').exists()


@pytest.mark.parametrize('fault', [None, 'missing', 'short', 'corrupt'])
def test_host_download_requires_all_parts_and_complete_digest(tmp_path, baseline, fault, ram_runtime):
    import device
    from capture_operation import Operation
    from transport import FileResultError
    package, _ = device.prepare_capture(tmp_path, 'b'*32, baseline)
    cfg = json.loads((package/'config.json').read_text())
    cfg.update(version_sha256=hashlib.sha256(b'version').hexdigest(),
               loader_sha256=hashlib.sha256(b'L'*233416).hexdigest())
    (package/'config.json').write_text(json.dumps(cfg))
    image = bytes(range(256))*(25100288//256)
    digest = hashlib.sha256(image).hexdigest()
    downloaded, uploaded = [], []
    class Files:
        def __init__(self, driver, operation, log):
            self.op = operation
        def read(self, path, limit):
            if path == '/version.txt':return b'version'
            if path == '/usr/lib/libJiritsu.so':return b'L'*233416
            if path == '/etc/ld.so.preload':return b'\n'*512
            if path.endswith('.ticket') and path in uploaded:return self.op.ticket
            if path == self.op.prefix+'.state' and '/tmp/jiritsu/libJit.so' in uploaded:
                return f'A7R5-JIT-1 {self.op.run} DONE 0 uid=0 euid=0 bytes={len(output)} disarmed=1 children=0\n'.encode()
            if path == self.op.prefix+'.output' and '/tmp/jiritsu/libJit.so' in uploaded:return output
            if path == self.op.cleanup_prefix+'.state' and len(uploaded)==4:
                return f'A7R5-JIT-1 {self.op.run} DONE 0 uid=0 euid=0 bytes={len(cleaned)} disarmed=1 children=0\n'.encode()
            if path == self.op.cleanup_prefix+'.output' and len(uploaded)==4:return cleaned
            if path.startswith(cfg['capture_path']+'.part-'):
                index = int(path.rsplit('-', 1)[1]);downloaded.append((index, limit))
                if fault == 'missing' and index == 1531:raise FileResultError(0x10000006)
                raw = image[index*16384:(index+1)*16384]
                if fault == 'short' and index == 1531:return raw[:-1]
                if fault == 'corrupt' and index == 42:return b'!'+raw[1:]
                return raw
            raise FileResultError(0x10000006)
        def put(self, path, data):
            assert self.op.writes[path] == data
            uploaded.append(path)
    operation = Operation(package, channel_factory=Files)
    output = (cfg['expected_output_begin']+f'A7R5_CAPTURE_COMPLETE {digest} bytes=25100288 twice=1 chunks=1532 chunk_bytes=16384\n'+cfg['expected_output_end']).encode()
    cleaned = f'A7R5_CAPTURE_CLEANUP {operation.run} sha256={digest} deleted=1532 bytes=25100288 directory_removed=1\n'.encode()
    destination = tmp_path/'session';destination.mkdir()
    report = {}
    if fault is None:
        operation(None, destination, lambda *a, **k: None, report)
        assert operation.safe_to_stop and report['capture_verified']
        assert (destination/'partition1.logical.bin').read_bytes() == image
        assert len(downloaded) == 1532 and max(size for _, size in downloaded) == 16384
        assert downloaded[-1] == (1531, 16384)
    else:
        with pytest.raises((ValueError, FileResultError)):
            operation(None, destination, lambda *a, **k: None, report)
        assert not operation.safe_to_stop and not report.get('capture_verified')
        assert not (destination/'partition1.logical.bin').exists()
        assert len(downloaded) == 1532
    assert report['partition_writes'] == 0 and len(uploaded) == (4 if fault is None else 2)


@pytest.mark.parametrize('fault', [None, 'absent', 'foreign-state', 'corrupt', 'preload-change'])
def test_existing_capture_uses_real_channel_without_any_file_upload(tmp_path, baseline, fault, ram_runtime, legacy_capture_payload):
    import device
    from capture_operation import ExistingCaptureOperation
    from transport import FileResultError, HEADER
    package, _ = device.prepare_capture(tmp_path, 'd'*32, baseline)
    (package/'materials/libJit.so').write_bytes(legacy_capture_payload.replace(b'd9a7216bc84f305e92a16bd4c7e038f5',b'd'*32))
    cfg = json.loads((package/'config.json').read_text())
    cfg.update(version_sha256=hashlib.sha256(b'version').hexdigest(),
               loader_sha256=hashlib.sha256(b'loader').hexdigest())
    (package/'config.json').write_text(json.dumps(cfg))
    cfg.pop('capture_format');(package/'config.json').write_text(json.dumps(cfg))
    image = bytes(range(256))*(25100288//256)
    digest = hashlib.sha256(image).hexdigest()
    output = (cfg['expected_output_begin']+f'A7R5_CAPTURE_COMPLETE {digest} bytes=25100288 twice=1 chunks=96 chunk_bytes=262144\n'+cfg['expected_output_end']).encode()
    op = ExistingCaptureOperation(package, sleep=lambda seconds: None)
    queue, commands = deque(), []
    selected, preload_reads = None, 0
    def write(packet):
        nonlocal selected, preload_reads
        op.guard_packet(packet)
        size, function, sequence, *meta = HEADER.unpack_from(packet)
        assert size == len(packet)-12 and function == 64 and not any(meta)
        group, cmd = struct.unpack_from('<HH', packet, 12)
        assert group == 0x1001 and cmd in (15, 17)
        commands.append(cmd);data=b'';result=0
        if cmd == 15:selected=packet[17:-1].decode().replace('/tmp/jiritsu/../..', '', 1)
        elif selected == '/version.txt':data=b'version'
        elif selected == '/usr/lib/libJiritsu.so':data=b'loader'
        elif selected == '/etc/ld.so.preload':
            preload_reads+=1;data=b'changed' if fault == 'preload-change' and preload_reads>1 else b'\n'*512
        elif selected == op.prefix+'.state':
            if fault == 'absent':result=0x10000008
            else:
                run='e'*32 if fault == 'foreign-state' else op.run
                data=f'A7R5-JIT-1 {run} DONE 0 uid=0 euid=0 bytes={len(output)} disarmed=1 children=0\n'.encode()
        elif selected == op.prefix+'.output':data=output
        else:
            assert selected in dict(op.parts)
            index=int(selected.rsplit('-', 1)[1]);data=image[index*262144:(index+1)*262144]
            if fault == 'corrupt' and index == 42:data=b'!'+data[1:]
        raw=struct.pack('<I', result)+data
        queue.append(HEADER.pack(len(raw), 64, sequence, 0, 0, 0, 0))
        for at in range(0, len(raw), 32768):
            block=raw[at:at+32768];queue.append(block)
            if len(block)%512 == 0:queue.append(b'')
        return len(packet)
    class Driver:
        def write(self, packet):return write(packet)
        def read(self, size):
            raw=queue.popleft();assert len(raw)<=size;return raw
    destination=tmp_path/'session';destination.mkdir();report={}
    if fault is None:
        op(Driver(), destination, lambda *a, **k: None, report)
        assert op.safe_to_stop and report['capture_verified']
        assert (destination/'partition1.logical.bin').read_bytes() == image
    else:
        with pytest.raises((ValueError, FileResultError)):
            op(Driver(), destination, lambda *a, **k: None, report)
        assert not op.safe_to_stop and not report.get('capture_verified')
    assert not op.writes and set(commands) == {15, 17} and not queue
    assert report['fixed_writes_attempted'] == report['trigger_attempts'] == report['partition_writes'] == 0
    assert report['existing_capture_read_only']
    # 即使赋予本次报文令牌，操作白名单仍拒绝文件上传。
    body=struct.pack('<HH', 0x1001, 16)+b'\0\xff\0payload'
    packet=HEADER.pack(len(body), 64, 1, 0, 0, 0, 0)+body
    op.permitted_packet=packet
    with pytest.raises(PermissionError):op.guard_packet(packet)


def test_new_capture_keeps_only_required_loader_in_work_root(tmp_path, baseline, ram_runtime):
    import device
    package, op=device.prepare_capture(tmp_path,'f'*32,baseline)
    prefix='/tmp_wbshd/a7r5-control-'+'f'*32+'/task'
    assert op.prefix==prefix
    assert set(op.writes)=={op.ticket_path,'/tmp/jiritsu/libJit.so'}
    assert op.config['capture_control_layout']=='ram-v2'
    assert b'A7R5_CAPTURE_READONLY_V5_RAM_16K' in op.payload
    assert op.ticket_path=='/tmp_wbshd/a7r5-control-'+'f'*32+'.ticket'
    assert op.ticket_path.encode() in op.payload and op.ticket_path in op.reads
    for suffix in ('.claim','.state','.state.new','.output'):
        assert (prefix+suffix).encode() in op.payload
        assert prefix+suffix in op.reads
    assert not any(path.startswith('/tmp/jiritsu/a7r5-jit-') for path in op.reads)
    # 旧任务仍按原路径读取；不改旧记录，也不把旧载荷误认为新捕获。
    cfg=json.loads((package/'config.json').read_text());cfg.pop('capture_control_layout');cfg.pop('capture_format')
    (package/'config.json').write_text(json.dumps(cfg))
    from capture_operation import ExistingCaptureOperation
    legacy=ExistingCaptureOperation(package)
    assert legacy.prefix=='/tmp/jiritsu/a7r5-jit-'+'f'*32 and not legacy.writes


def test_new_capture_refuses_legacy_template_before_upload(tmp_path, baseline):
    import device
    with pytest.raises(ValueError,match='模板'):
        device.prepare_capture(tmp_path,'f'*32,baseline)
    assert not (tmp_path/'package/materials/libJit.so').exists()


def test_bootstrap_ticket_can_be_created_without_service_mkdir(tmp_path,baseline,ram_runtime):
    import device
    job=tmp_path/'job';job.mkdir();_,op=device.prepare_capture(job,'a'*32,baseline)
    ticket=next(path for path in op.writes if path!='/tmp/jiritsu/libJit.so')
    ram=tmp_path/'existing-tmpfs';ram.mkdir()
    target=ram/Path(ticket).relative_to('/tmp_wbshd')
    # 固件CFileAccess对非/mnt路径调用open(O_CREAT)，不会创建父目录。
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(op.ticket)
    assert target.read_bytes()==op.ticket and target.parent==ram
