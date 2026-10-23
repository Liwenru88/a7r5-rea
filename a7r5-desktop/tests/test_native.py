"""在普通文件上执行同一扇区核心；不使用QEMU或设备节点。"""
import base64
import hashlib
from pathlib import Path
import subprocess
import pytest
from conftest import ROOT
import common


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    folder=tmp_path_factory.mktemp('desktop-native').resolve()
    sectors=common.load(ROOT/'prepared/engine/trust-sectors.json')
    plan=common.load(ROOT/'prepared/engine/write-plan.json')
    (folder/'jit_config.h').write_text('#define RUN_ID "'+'7'*32+'"\n')
    values=dict(ORIGINAL_SHA=common.SOURCE_SHA,CANDIDATE_SHA=common.TARGET_SHA)
    arrays={name:b''.join(base64.b64decode(r[key]) for r in sectors['rows']) for name,key in [('BEFORE_SECTORS','before'),('AFTER_SECTORS','after')]}
    values.update(BEFORE_PATCH_SHA=hashlib.sha256(arrays['BEFORE_SECTORS']).hexdigest(),AFTER_PATCH_SHA=hashlib.sha256(arrays['AFTER_SECTORS']).hexdigest())
    header=''.join('#define '+key+' "'+value+'"\n' for key,value in values.items())
    header+='#define PARTITION_BYTES 25100288UL\n#define PATCH_COUNT 258U\n'
    header+='static const unsigned long PATCH_OFFSETS[]={'+','.join(str(r['offset']) for r in sectors['rows'])+'};\n'
    header+='static const unsigned char PATCH_CHECKSUM[]={'+','.join(str(int(r['phase']=='checksum')) for r in plan['rows'])+'};\n'
    for name,raw in arrays.items():header+='static const unsigned char '+name+'[]={'+','.join(map(str,raw))+'};\n'
    (folder/'trust_config.h').write_text(header)
    source=ROOT.parent/'a7r5-updater-trust/deploy/tests/host_core.c'
    binary=folder/'native-test'
    subprocess.run(['/usr/bin/clang','-O2','-Wall','-Wextra','-Werror','-Wno-unused-const-variable','-I',str(folder),'-I',str(ROOT/'sources/trust'),str(source),'-o',str(binary)],capture_output=True,check=True)
    original=(ROOT.parent/'a7r5-firmware-images/标准固件_19项/明文分区_17项/cnflasha1.img').read_bytes()
    assert hashlib.sha256(original).hexdigest()==common.SOURCE_SHA
    return binary,original,plan


@pytest.mark.parametrize('fault,code',[(0,0),(1,14),(2,17),(4,19),(5,20),(7,15),(8,18)])
def test_real_sector_core_success_partial_write_and_journal(native,tmp_path,fault,code):
    binary,original,plan=native;disk=tmp_path/'disk.img';journal=tmp_path/'journal';disk.write_bytes(original)
    result=subprocess.run([str(binary),str(disk),str(journal),str(fault)],capture_output=True,text=True,check=True)
    assert result.stdout.startswith(f'code={code} ')
    raw=disk.read_bytes();log=journal.read_text()
    if fault in (0,5):assert hashlib.sha256(raw).hexdigest()==common.TARGET_SHA
    if fault in (1,7):assert raw==original
    if fault in (2,8):
        at=plan['rows'][0]['offset'];assert raw[:at]==original[:at] and raw[at+512:]==original[at+512:] and raw!=original
        assert log.count('WRITE_BEGIN')==1
    if fault==4:
        row=plan['rows'][-1];assert raw[row['offset']:row['offset']+512]==original[row['offset']:row['offset']+512]
        assert log.count('WRITE_BEGIN')==257


def test_wrong_full_preimage_is_never_written(native,tmp_path):
    binary,original,_=native;raw=bytearray(original);raw[0]^=1;disk=tmp_path/'wrong.img';disk.write_bytes(raw)
    result=subprocess.run([str(binary),str(disk),str(tmp_path/'journal'),'0'],capture_output=True,text=True,check=True)
    assert result.stdout.startswith('code=14 ') and disk.read_bytes()==raw
