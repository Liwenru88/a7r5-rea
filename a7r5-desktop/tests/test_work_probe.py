"""真实C核心产生诊断回执，再由主机解析；全程普通文件和内存协议替身。"""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest


@pytest.fixture(scope='module')
def probe_core(tmp_path_factory):
    root=Path(__file__).resolve().parents[1]
    folder=tmp_path_factory.mktemp('work-probe')
    (folder/'work_probe_config.h').write_text(
        '#define PROBE_SOURCE source_path\n#define PROBE_DATA_PATH snapshot_path\n'
        '#define PROBE_BEGIN "A7R5_WORK_PROBE_BEGIN '+ '1'*32 +'\\n"\n'
        '#define PROBE_END "A7R5_WORK_PROBE_END '+ '1'*32 +'\\n"\n')
    binary=folder/'work-probe'
    built=subprocess.run(['/usr/bin/clang','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
        '-I',str(folder),'-I',str(root/'sources/trust'),str(root/'tests/host_work_probe.c'),'-o',str(binary)],capture_output=True,text=True)
    assert built.returncode==0,built.stderr
    image=root.parent/'a7r5-firmware-images/标准固件_19项/明文分区_17项/cnflasha6.img'
    raw=image.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='190e13b02ecdc66bd6f563a4d9a0645210fba79986c9b31e06ef923f598aea7e'
    return binary,raw


@pytest.mark.parametrize('fault,code',[(0,0),(1,0),(2,116),(3,117),(4,118),(5,112),(6,115)])
def test_native_work_metadata_never_writes_source_or_overwrites(probe_core,tmp_path,fault,code):
    binary,raw=probe_core
    source=tmp_path/'work.img';source.write_bytes(raw)
    snapshot=tmp_path/'snapshot'
    if fault==4:snapshot.write_bytes(b'sentinel')
    result=subprocess.run([str(binary),str(source),str(snapshot),str(tmp_path),str(fault)],capture_output=True,text=True,check=True)
    assert f'code={code} source_writes=0 ' in result.stdout
    assert source.read_bytes()==raw
    if code==0:
        expected=raw[:512]+raw[3072:3072+16384]
        assert snapshot.read_bytes()==expected
        assert hashlib.sha256(expected).hexdigest() in result.stdout
        assert f'fs_flags={int(fault==1)} ' in result.stdout
        assert 'memory_available_kib=65536 root_slots=512 free_slots=410 ' in result.stdout
    elif fault==4:assert snapshot.read_bytes()==b'sentinel'
    else:assert not snapshot.exists()


@pytest.mark.parametrize('tamper',[False,True])
def test_host_accepts_only_complete_probe_and_keeps_STOP_withheld(probe_core,tmp_path,baseline,ram_runtime,tamper):
    import device
    from transport import FileResultError
    binary,raw=probe_core;source=tmp_path/'work.img';source.write_bytes(raw)
    snapshot=tmp_path/'snapshot'
    result=subprocess.run([str(binary),str(source),str(snapshot),str(tmp_path),'0'],capture_output=True,text=True,check=True)
    output=result.stdout.split('code=')[0].encode();data=snapshot.read_bytes()
    job=tmp_path/'job';job.mkdir();package,op=device.prepare_capture(job,'1'*32,baseline,probe=True)
    assert b'/dev/cnflasha1' not in op.payload and b'/dev/cnflasha6' in op.payload
    cfg=json.loads((package/'config.json').read_text())
    cfg.update(version_sha256=hashlib.sha256(b'version').hexdigest(),loader_sha256=hashlib.sha256(b'loader').hexdigest())
    (package/'config.json').write_text(json.dumps(cfg))
    uploads=[]
    class Files:
        def __init__(self,driver,operation,log):self.op=operation
        def put(self,path,content):assert self.op.writes[path]==content;uploads.append(path)
        def read(self,path,limit):
            if path=='/version.txt':return b'version'
            if path=='/usr/lib/libJiritsu.so':return b'loader'
            if path=='/etc/ld.so.preload':return b'\n'*512
            if path==self.op.ticket_path and path in uploads:return self.op.ticket
            if '/tmp/jiritsu/libJit.so' in uploads:
                if path==self.op.prefix+'.state':return f'A7R5-JIT-1 {self.op.run} DONE 0 uid=0 euid=0 bytes={len(output)} disarmed=1 children=0\n'.encode()
                if path==self.op.prefix+'.output':return output
                if path==self.op.prefix+'.work-root':return b'!'+data[1:] if tamper else data
            raise FileResultError(0x10000006)
    from work_probe import Operation
    op=Operation(package,channel_factory=Files);destination=job/'session';destination.mkdir();report={}
    if tamper:
        with pytest.raises(ValueError,match='摘要'):op(None,destination,lambda *a,**k:None,report)
        assert not report.get('work_probe_verified')
    else:
        op(None,destination,lambda *a,**k:None,report)
        assert report['work_probe_verified'] and report['root_free_slots']==410
        assert not report['work_read_only'] and report['partition_writes']==0
    assert not op.safe_to_stop and not op.parts
    assert uploads==[op.ticket_path,'/tmp/jiritsu/libJit.so']
