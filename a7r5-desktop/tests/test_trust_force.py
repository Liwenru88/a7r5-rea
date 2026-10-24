"""强制安装跳过历史前像限制，仍只覆盖固定扇区；全部测试离线。"""
import hashlib
import json
import subprocess

import pytest
import common
import device
from conftest import ROOT
from test_native import native


def test_force_package_does_not_require_backup_and_normal_mode_keeps_gate(tmp_path,baseline,ram_runtime):
    force=tmp_path/'force';force.mkdir()
    package,op=device.prepare_update(force,'3'*32,baseline,None,force=True)
    cfg=common.load(package/'config.json')
    assert cfg['force_install'] is True and op.packet_limit==512
    assert op.usb_read_size==8192 and op.strict_usb_reads
    assert cfg['trust_readback_format']=='planned-sectors-v2'
    assert len(op.readback_parts)==9 and [size for _,size in op.readback_parts]==[16384]*8+[1024]
    assert not (package/'materials/candidate.logical.img').exists()
    with pytest.raises((ValueError,TypeError)):
        normal=tmp_path/'normal';normal.mkdir()
        device.prepare_update(normal,'4'*32,baseline,None)


@pytest.fixture(scope='module')
def force_native(native,tmp_path_factory):
    binary,original,plan=native;folder=tmp_path_factory.mktemp('force-native')
    (folder/'jit_config.h').write_bytes((binary.parent/'jit_config.h').read_bytes())
    (folder/'trust_config.h').write_text('#define TRUST_FORCE_MODE 1\n'+(binary.parent/'trust_config.h').read_text())
    output=folder/'force-core'
    subprocess.run(['/usr/bin/clang','-O2','-Wall','-Wextra','-Werror','-Wno-unused-const-variable',
        '-I',str(folder),'-I',str(ROOT/'sources/trust'),
        str(ROOT.parent/'a7r5-updater-trust/deploy/tests/host_core.c'),'-o',str(output)],capture_output=True,check=True)
    return output,original,plan


@pytest.mark.parametrize('fault,code',[(0,0),(2,17),(4,19),(5,20),(7,15),(8,18)])
def test_force_native_preserves_unselected_bytes_and_stops_on_uncertain_write(force_native,tmp_path,fault,code):
    import base64
    binary,original,plan=force_native
    before=bytearray(original);before[0]^=1;before[plan['rows'][0]['offset']]^=1
    image=tmp_path/'image';image.write_bytes(before);journal=tmp_path/'journal'
    result=subprocess.run([str(binary),str(image),str(journal),str(fault)],capture_output=True,text=True,check=True)
    assert result.stdout.startswith(f'code={code} ')
    actual=image.read_bytes();log=journal.read_text()
    assert actual[0]==before[0]
    if fault in (0,5):
        expected=bytearray(before)
        for row in common.load(ROOT/'prepared/engine/trust-sectors.json')['rows']:
            expected[row['offset']:row['offset']+512]=base64.b64decode(row['after'])
        assert actual==expected
        assert hashlib.sha256(actual).hexdigest()!=common.TARGET_SHA
    if fault==7:assert actual==before
    if fault in (2,8):assert log.count('WRITE_BEGIN')==1
    assert log.startswith('A7R5_TRUST '+'7'*32+' FORCE_PREIMAGE_CAPTURED ')


@pytest.mark.parametrize('sector_readback,readback_fault,resource_fault,code',[
    (False,0,0,0),(True,0,0,0),(True,1,0,65),(True,2,0,64),(True,3,0,64),
    (True,0,1,43),(True,0,2,43),(True,0,3,43),(True,0,4,44),(True,0,5,44)])
def test_native_force_transaction_reopens_and_emits_complete_small_readback(force_native,tmp_path,sector_readback,readback_fault,resource_fault,code):
    import base64
    import os
    from trust_operation import validate_journal
    binary,original,plan=force_native
    folder=tmp_path/'build';folder.mkdir()
    (folder/'jit_config.h').write_bytes((binary.parent/'jit_config.h').read_bytes()+b'\n#define TRUST_RESOURCE_CHECK_DIAGNOSTICS 1\n')
    header=(binary.parent/'trust_config.h').read_text()
    if sector_readback:header+='\n#define TRUST_FORCE_SECTOR_READBACK 1\n'
    header+='\n#define TARGET_PATH target_path\n#define RAM_DIR ram_path\n#define JOURNAL_PATH journal_path\n#define READBACK_PATH readback_path\n'
    header+='#define FORCE_PRELOAD_A '+json.dumps('\n'*512)+'\n#define FORCE_PRELOAD_B FORCE_PRELOAD_A\n'
    header+='#define OUTPUT_BEGIN "BEGIN\\n"\n#define OUTPUT_END "END\\n"\n'
    (folder/'trust_config.h').write_text(header)
    compiled=subprocess.run(['/usr/bin/clang','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-const-variable',
        '-I',str(folder),'-I',str(ROOT/'sources/trust'),str(ROOT/'tests/host_trust_force.c'),'-o',str(folder/'transaction')],capture_output=True,text=True)
    assert compiled.returncode==0,compiled.stderr
    before=bytearray(original);before[0]^=1;before[plan['rows'][0]['offset']]^=1
    image=tmp_path/'image';image.write_bytes(before)
    work=tmp_path/'work';work.mkdir()
    result=subprocess.run([str(folder/'transaction'),str(image),str(work)],capture_output=True,text=True,check=True,
        env=dict(os.environ,A7R5_NATIVE_RB_FAULT=str(readback_fault),A7R5_NATIVE_RESOURCE_FAULT=str(resource_fault)))
    if resource_fault:
        assert f'code={code} target_writes=0' in result.stdout
        assert image.read_bytes()==before and not (work/'ram').exists()
        assert f'resource_reason={resource_fault}' in result.stdout
        assert 'memory_required_kib=65536' in result.stdout and 'partition_writes=0' in result.stdout
        if resource_fault==2:assert 'memory_available_kib=65535' in result.stdout
        return
    assert f'code={code} target_writes=258' in result.stdout
    if readback_fault:
        assert 'A7R5_TRUST_FORCE_COMPLETE' not in result.stdout
        assert 'REOPENED_FULL_CAPTURE_MATCH' not in (work/'ram/journal').read_text()
        return
    expected=bytearray(before)
    for row in common.load(ROOT/'prepared/engine/trust-sectors.json')['rows']:
        expected[row['offset']:row['offset']+512]=base64.b64decode(row['after'])
    if sector_readback:
        pieces=[work/f'ram/partition.logical.sectors-{i}' for i in range(9)]
        expected_readback=b''.join(expected[row['offset']:row['offset']+512] for row in plan['rows'])
        assert [p.stat().st_size for p in pieces]==[16384]*8+[1024]
        assert not list((work/'ram').glob('partition.logical.part-*'))
        assert 'chunks=9 chunk_bytes=16384 readback=planned-sectors-v2' in result.stdout
    else:
        pieces=[work/f'ram/partition.logical.part-{i}' for i in range(1532)]
        expected_readback=expected
        assert all(p.stat().st_size==16384 for p in pieces)
    assert image.read_bytes()==expected and expected_readback==b''.join(p.read_bytes() for p in pieces)
    assert f'A7R5_TRUST_FORCE_COMPLETE {hashlib.sha256(expected).hexdigest()} source_sha256={hashlib.sha256(before).hexdigest()}' in result.stdout
    validate_journal((work/'ram/journal').read_bytes(),'7'*32,plan,force=True)


def old_force_payload(tmp_path_factory,*,sector_readback):
    import base64,importlib.util
    spec=importlib.util.spec_from_file_location('legacy_force_builder',ROOT/'scripts/prepare.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    sectors=common.load(ROOT/'prepared/engine/trust-sectors.json');plan=common.load(ROOT/'prepared/engine/write-plan.json')
    old=b''.join(base64.b64decode(row['before']) for row in sectors['rows'])
    new=b''.join(base64.b64decode(row['after']) for row in sectors['rows'])
    preload=bytes.fromhex(common.load(ROOT/'engine/profile.json')['preload_baselines'][0][1]).decode()
    return builder.trust_sector_library(tmp_path_factory.mktemp('legacy-force')/'build','5'*32,preload,
        sectors['source_sha256'],sectors['target_sha256'],old,new,plan,force=True,sector_readback=sector_readback,planned_resource_budget=False)


@pytest.fixture(scope='module')
def legacy_force_payload(tmp_path_factory):return old_force_payload(tmp_path_factory,sector_readback=False)


@pytest.fixture(scope='module')
def legacy_planned_force_payload(tmp_path_factory):return old_force_payload(tmp_path_factory,sector_readback=True)


@pytest.mark.parametrize('fault',['legacy-config','unknown-config','legacy-payload'])
def test_force_readback_rejects_mixed_format_before_channel(tmp_path,baseline,ram_runtime,legacy_force_payload,fault):
    from trust_operation import Operation
    package,_=device.prepare_update(tmp_path,'5'*32,baseline,None,force=True)
    cfg=common.load(package/'config.json')
    if fault=='legacy-payload':(package/'materials/libJit.so').write_bytes(legacy_force_payload)
    else:
        cfg['trust_readback_format']='full-16k-v1' if fault=='legacy-config' else 'unknown'
        (package/'config.json').write_text(json.dumps(cfg))
    with pytest.raises(ValueError):Operation(package,channel_factory=lambda *a:pytest.fail('混用格式不得建立USB通道'))


@pytest.mark.parametrize('sector_readback,fault',[(False,None),(False,'corrupt'),(False,'wrong-patch'),
    (True,None),(True,'corrupt'),(True,'wrong-patch'),(True,'timeout'),(True,'state-change'),(True,'resource-budget'),(True,'resource-mixed')])
def test_force_channel_keeps_digest_and_exact_patch_readback_gates(tmp_path,baseline,ram_runtime,monkeypatch,legacy_force_payload,sector_readback,fault):
    import base64
    from trust_operation import Operation
    from test_device import Wire,install_session
    from system_dump import session
    package,_=device.prepare_update(tmp_path,'5'*32,baseline,None,force=True)
    cfg=common.load(package/'config.json')
    cfg.update(version_sha256=hashlib.sha256(b'fixture-version').hexdigest(),loader_sha256=hashlib.sha256(b'L'*233416).hexdigest())
    if not sector_readback:
        cfg.pop('trust_readback_format');cfg.pop('trust_resource_policy');(package/'materials/libJit.so').write_bytes(legacy_force_payload)
    (package/'config.json').write_text(json.dumps(cfg))
    op=Operation(package,sleep=lambda _:None);op.start=op;op.output=tmp_path/'session'
    image=bytearray(b'x'*25100288)
    for row in op.patch:image[row['offset']:row['offset']+512]=base64.b64decode(row['after'])
    if fault=='wrong-patch':image[op.patch[0]['offset']]^=1
    digest=hashlib.sha256(image).hexdigest()
    packed=b''.join(image[row['offset']:row['offset']+512] for row in op.patch) if sector_readback else image
    layout='chunks=9 chunk_bytes=16384 readback=planned-sectors-v2' if sector_readback else 'chunks=1532 chunk_bytes=16384'
    native=(cfg['expected_output_begin']+f'A7R5_TRUST_FORCE_COMPLETE {digest} source_sha256='+('f'*64)+
        ' sectors=258 bytes=132096 reopened=1 '+layout+'\n'+cfg['expected_output_end']).encode()
    entries=[('FORCE_PREIMAGE_CAPTURED',0,-1,0)]
    rows=op.plan['rows']
    for i,row in enumerate(rows):
        entries.extend([('WRITE_BEGIN',i,row['offset'],0),('WRITE_RETURNED',i+1,row['offset'],0)])
        if i==len(rows)-1 or row['phase']!=rows[i+1]['phase']:entries.append(('PHASE_SYNC_RETURNED',i+1,row['offset'],0))
    entries.extend([('FULL_LOGICAL_READBACK_MATCH',258,-1,0),('REOPENED_FULL_CAPTURE_MATCH',258,-1,0),('COMPLETED',258,-1,0)])
    journal=''.join(f'A7R5_TRUST {op.run} {p} completed={c} offset={o} code={v}\n' for p,c,o,v in entries).encode()
    class ForceWire(Wire):
        state_reads=0
        def contents(self,path):
            if self.triggers:
                if path==op.prefix+'.state':
                    if fault in ('resource-budget','resource-mixed'):
                        required=32768 if fault=='resource-budget' else 65536
                        return f'A7R5-JIT-1 {op.run} FAILED 43 uid=0 euid=0 bytes=0 disarmed=1 children=0 resource_reason=2 resource_error=0 memory_available_kib=32767 memory_required_kib={required} ram_available_bytes=-1 partition_writes=0\n'.encode()
                    self.state_reads+=1;children=-1 if fault=='state-change' and self.state_reads>1 else 0
                    return f'A7R5-JIT-1 {op.run} DONE 0 uid=0 euid=0 bytes={len(native)} disarmed=1 children={children}\n'.encode()
                if path==op.prefix+'.output':return native
                if path==cfg['journal_path']:return journal
                if path in dict(op.readback_parts):
                    index=int(path.rsplit('-',1)[1]);part=bytes(packed[index*16384:(index+1)*16384])
                    return b'!'+part[1:] if fault=='corrupt' and index==8 else part
            return super().contents(path) if not self.triggers else self.files.get(path)
        def read(self,size):
            if fault=='timeout' and self.selected==op.readback_parts[2][0]:
                import usb.core
                raise usb.core.USBTimeoutError('模拟选择第3块后响应头超时',-7)
            return super().read(size)
    camera=ForceWire(op,None);controls,_=install_session(monkeypatch,op,camera)
    # 版本、加载库和预加载在上传前后均保持一致。
    original_contents=camera.contents
    def contents(path):
        if path=='/version.txt':return b'fixture-version'
        if path=='/usr/lib/libJiritsu.so':return b'L'*233416
        if path=='/etc/ld.so.preload':return bytes.fromhex(cfg['preload_baselines'][0][1])
        return original_contents(path)
    camera.contents=contents
    report=session.run_session(op.output,'libusb',_operation=op)
    assert camera.sequences==list(range(1,len(camera.sequences)+1))
    assert max(camera.sequences)<512 if sector_readback else max(camera.sequences)>512
    assert camera.triggers==1 and len(camera.puts)==2
    assert sum(c[1:4]==session.STOP for c in controls)==int(fault is None)
    assert op.safe_to_stop is (fault is None)
    if fault in ('resource-budget','resource-mixed'):
        assert report['failure'] and not report['native_write_complete']
        assert report['trust_resource_policy']=='planned-sectors-32m-v1'
        assert report.get('trust_resource_check_failed',False) is (fault=='resource-budget')
        assert not (op.output/'trust-readback-checkpoint.json').exists()
        return
    if fault is None:
        assert report['complete_partition_readback_verified'] is not sector_readback
        if sector_readback:
            assert report['planned_sector_readback_verified'] and report['native_logical_partition_sha256']==digest
            assert report['trust_readback_bytes']==132096
            assert (op.output/'planned-sector-readback.bin').read_bytes()==packed
            assert not (op.output/'partition1.logical.bin').exists()
        else:
            assert report['logical_partition_sha256']==digest and (op.output/'partition1.logical.bin').read_bytes()==image
    else:
        assert report['failure'] and not report['complete_partition_readback_verified']
        assert not (op.output/'partition1.logical.bin').exists()
        assert report['native_write_complete'] and not report['planned_sector_readback_verified']
    checkpoint=common.load(op.output/'trust-readback-checkpoint.json')
    assert checkpoint['host_verified'] is (fault is None)
    if fault=='timeout':
        assert report['trust_readback_completed_chunks']==checkpoint['completed_chunks']==2
        assert checkpoint['completed_bytes']==32768 and report['service_stop_attempts']==0
