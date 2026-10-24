"""信任更新控制文件必须留在RAM；只在本机文件与协议替身上验证。"""
import hashlib
import json
from pathlib import Path

import pytest

import common
import device
from transport import FileResultError


def update_package(tmp_path, baseline):
    source=Path(__file__).resolve().parents[2]/'a7r5-firmware-images/标准固件_19项/明文分区_17项/cnflasha1.img'
    assert common.sha(source)==common.SOURCE_SHA
    preload=common.load(common.ROOT/'profile.json')['preload_baselines'][0][0]
    record=tmp_path/'backup.json'
    record.write_text(json.dumps(dict(kind='backup',task_complete=True,device_IO=True,simulation=False,
        backup_sha256=common.SOURCE_SHA,backup_file=str(source),preload_name=preload)))
    return device.prepare_update(tmp_path,'8'*32,baseline,record)


@pytest.mark.parametrize('fault',[None,'loader-open','journal-truncated','readback-corrupt','precheck-legacy','precheck-detail','precheck-directory',
    'resource-detail','resource-legacy','resource-mismatch'])
def test_trust_ram_layout_keeps_complete_write_verification(tmp_path,baseline,ram_runtime,fault):
    package,op=update_package(tmp_path,baseline)
    assert op.config['trust_control_layout']=='ram-v2'
    assert op.ticket_path=='/tmp_wbshd/a7r5-control-'+'8'*32+'.ticket'
    assert op.prefix=='/tmp_wbshd/a7r5-control-'+'8'*32+'/task'
    assert set(op.writes)=={op.ticket_path,'/tmp/jiritsu/libJit.so'}
    assert not any(path.startswith('/tmp/jiritsu/a7r5-jit-') for path in op.reads)
    for path in (op.ticket_path,*[op.prefix+s for s in ('.claim','.state','.state.new','.output')]):
        assert path.encode() in op.payload and path in op.reads
    assert b'A7R5_TRUST_PRODUCTION_V3_RAM_BOOTSTRAP' in op.payload
    assert b'/tmp/jiritsu/a7r5-jit-' not in op.payload
    cfg=common.load(package/'config.json')
    cfg.update(version_sha256=hashlib.sha256(b'version').hexdigest(),loader_sha256=hashlib.sha256(b'loader').hexdigest())
    (package/'config.json').write_text(json.dumps(cfg))
    output=(cfg['expected_output_begin']+'A7R5_TRUST_COMPLETE '+cfg['candidate_sha256']+
        ' sectors=258 bytes=132096 reopened=1\n'+cfg['expected_output_end']).encode()
    entries=[('PREIMAGE_VERIFIED',0,-1,0)]
    rows=op.plan['rows']
    for index,row in enumerate(rows):
        entries.extend([('WRITE_BEGIN',index,row['offset'],0),('WRITE_RETURNED',index+1,row['offset'],0)])
        if index==len(rows)-1 or row['phase']!=rows[index+1]['phase']:
            entries.append(('PHASE_SYNC_RETURNED',index+1,row['offset'],0))
    entries.extend([('FULL_LOGICAL_READBACK_MATCH',258,-1,0),('REOPENED_FULL_CAPTURE_MATCH',258,-1,0),('COMPLETED',258,-1,0)])
    journal=''.join(f'A7R5_TRUST {op.run} {phase} completed={count} offset={offset} code={code}\n'
                    for phase,count,offset,code in entries).encode()
    uploads=[];reads=[]
    class Files:
        def __init__(self,driver,operation,log):self.op=operation
        def put(self,path,data):
            assert self.op.writes[path]==data;uploads.append(path)
            if fault=='loader-open' and path=='/tmp/jiritsu/libJit.so':
                raise FileResultError(0x10000008,action='write',path=path)
        def read(self,path,limit):
            reads.append(path)
            if path=='/version.txt':return b'version'
            if path=='/usr/lib/libJiritsu.so':return b'loader'
            if path=='/etc/ld.so.preload':return bytes.fromhex(cfg['expected_preload_hex'])
            if path==self.op.ticket_path and path in uploads:return self.op.ticket
            if '/tmp/jiritsu/libJit.so' in uploads:
                if path==self.op.prefix+'.state':
                    if fault and fault.startswith('resource'):
                        code=17 if fault=='resource-mismatch' else 43
                        suffix='' if fault=='resource-legacy' else ' resource_reason=2 resource_error=0 memory_available_kib=65535 memory_required_kib=65536 ram_available_bytes=-1 partition_writes=0'
                        return f'A7R5-JIT-1 {self.op.run} FAILED {code} uid=0 euid=0 bytes=0 disarmed=1 children=0{suffix}\n'.encode()
                    if fault and fault.startswith('precheck'):
                        reason=14 if fault=='precheck-directory' else 6
                        suffix=f' precheck_reason={reason} precheck_pid=101 precheck_fd=-1 precheck_error=-13 precheck_device=0 partition_writes=0' if fault!='precheck-legacy' else ''
                        return f'A7R5-JIT-1 {self.op.run} FAILED 47 uid=0 euid=0 bytes=0 disarmed=1 children=0{suffix}\n'.encode()
                    return f'A7R5-JIT-1 {self.op.run} DONE 0 uid=0 euid=0 bytes={len(output)} disarmed=1 children=0\n'.encode()
                if path==self.op.prefix+'.output':return output
                if path==cfg['journal_path']:return journal[:-1] if fault=='journal-truncated' else journal
                if path==cfg['readback_path']:
                    data=self.op.expected_candidate
                    return b'!'+data[1:] if fault=='readback-corrupt' else data
            raise FileResultError(0x10000006,action='read',path=path)
    from trust_operation import Operation
    op=Operation(package,channel_factory=Files,sleep=lambda seconds:None)
    dest=tmp_path/'session';dest.mkdir();report={}
    if fault is None:
        op(None,dest,lambda *a,**k:None,report)
        assert op.safe_to_stop and report['complete_partition_readback_verified']
        assert report['logical_partition_sha256']==common.TARGET_SHA
    else:
        with pytest.raises((ValueError,RuntimeError)):op(None,dest,lambda *a,**k:None,report)
        assert not op.safe_to_stop and not report['complete_partition_readback_verified']
        if fault.startswith('precheck'):
            assert report['partition_write_may_have_started'] is False and report['partition_writes']==0
            assert report['trust_precheck_failed'] and report['trust_native_exit_code']==47
            assert reads[-1]==op.prefix+'.state'
            if fault=='precheck-detail':assert report['trust_precheck']['error']==-13
            if fault=='precheck-directory':assert report['trust_precheck']['reason']==14
        if fault.startswith('resource') and fault!='resource-mismatch':
            assert report['partition_write_may_have_started'] is False and report['partition_writes']==0
            assert report['trust_resource_check_failed'] and reads[-1]==op.prefix+'.state'
            assert report['trust_native_exit_code']==43
            if fault=='resource-detail':assert report['trust_resources']['memory_available_kib']==65535
        if fault=='resource-mismatch':assert report['partition_write_may_have_started'] is True
    assert uploads==[op.ticket_path,'/tmp/jiritsu/libJit.so']


def test_new_trust_rejects_old_template_before_device_io(tmp_path,baseline):
    with pytest.raises(ValueError,match='模板'):
        update_package(tmp_path,baseline)
    assert not (tmp_path/'package/materials/libJit.so').exists()


@pytest.mark.parametrize('fault',['missing-layout','wrong-payload'])
def test_trust_refuses_mixed_runtime_and_template(tmp_path,baseline,ram_runtime,fault):
    package,_=update_package(tmp_path,baseline)
    if fault=='missing-layout':
        cfg=common.load(package/'config.json');cfg.pop('trust_control_layout')
        (package/'config.json').write_text(json.dumps(cfg))
    else:
        path=package/'materials/libJit.so';raw=path.read_bytes()
        marker=b'A7R5_TRUST_PRODUCTION_V3_RAM_BOOTSTRAP'
        path.write_bytes(raw.replace(marker,b'X'*len(marker)))
    from trust_operation import Operation
    with pytest.raises(ValueError,match='模板'):
        Operation(package,channel_factory=lambda *a:pytest.fail('材料不符时禁止设备通道'))
