"""固定载荷在普通文件上验证资源准入，不读取相机。"""
import base64
import json
import os
import subprocess

import pytest

import common
import device
from conftest import ROOT
from test_trust_force import force_native
from test_native import native
from test_trust_force import legacy_planned_force_payload


@pytest.fixture(scope='module')
def resource_native(request,force_native,tmp_path_factory):
    binary,original,plan=force_native;folder=tmp_path_factory.mktemp('resource-'+request.param)
    mode=request.param
    (folder/'jit_config.h').write_bytes((binary.parent/'jit_config.h').read_bytes()+b'\n#define TRUST_RESOURCE_CHECK_DIAGNOSTICS 1\n')
    header=(binary.parent/'trust_config.h').read_text()
    header+='\n#define TRUST_FORCE_SECTOR_READBACK '+str(int(mode.startswith('planned')))+'\n'
    header+='#define TRUST_PLANNED_RESOURCE_BUDGET '+str(int(mode=='planned-32m'))+'\n'
    if mode=='normal-64m':header+='\n#undef TRUST_FORCE_MODE\n#define TRUST_FORCE_MODE 0\n'
    header+='\n#define TARGET_PATH target_path\n#define RAM_DIR ram_path\n#define JOURNAL_PATH journal_path\n#define READBACK_PATH readback_path\n'
    header+='#define EXPECTED_PRELOAD '+json.dumps('\n'*512)+'\n'
    header+='#define FORCE_PRELOAD_A EXPECTED_PRELOAD\n#define FORCE_PRELOAD_B EXPECTED_PRELOAD\n'
    header+='#define OUTPUT_BEGIN "BEGIN\\n"\n#define OUTPUT_END "END\\n"\n'
    (folder/'trust_config.h').write_text(header)
    subprocess.run(['/usr/bin/clang','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-const-variable',
        '-I',str(folder),'-I',str(ROOT/'sources/trust'),str(ROOT/'tests/host_trust_force.c'),'-o',str(folder/'transaction')],capture_output=True,check=True)
    return folder/'transaction',original,plan,mode


def execute(resource_native,tmp_path,extra):
    binary,original,plan,mode=resource_native
    image=tmp_path/'image';image.write_bytes(original);work=tmp_path/'work';work.mkdir()
    result=subprocess.run([str(binary),str(image),str(work)],env=dict(os.environ,**extra),capture_output=True,text=True,check=True)
    return result.stdout,image,original,plan,work,mode


@pytest.mark.parametrize('resource_native',['planned-32m','planned-old-64m','full-old-64m','normal-64m'],indirect=True)
def test_observed_memory_is_accepted_only_by_new_planned_budget(resource_native,tmp_path):
    output,image,original,plan,work,mode=execute(resource_native,tmp_path,{'A7R5_NATIVE_MEMINFO':'MemAvailable: 52820 kB\n'})
    if mode=='planned-32m':
        assert 'code=0 target_writes=258' in output
        expected=bytearray(original)
        for row in common.load(ROOT/'prepared/engine/trust-sectors.json')['rows']:
            expected[row['offset']:row['offset']+512]=base64.b64decode(row['after'])
        assert image.read_bytes()==expected
        assert sum(f.stat().st_size for f in (work/'ram').glob('partition.logical.sectors-*'))==132096
    else:
        assert 'code=43 target_writes=0' in output and 'memory_required_kib=65536' in output
        assert image.read_bytes()==original and not (work/'ram').exists()


@pytest.mark.parametrize('resource_native',['planned-32m'],indirect=True)
@pytest.mark.parametrize('extra,code',[
    ({'A7R5_NATIVE_MEMINFO':'MemAvailable: 32768 kB\n'},0),
    ({'A7R5_NATIVE_MEMINFO':'MemAvailable: 32767 kB\n'},43),
    ({'A7R5_NATIVE_MEMINFO':'MemAvailable:\t32768\tkB\n'},0),
    ({'A7R5_NATIVE_MEMINFO':'MemAvailable: 131072 MB\n'},43),
    ({'A7R5_NATIVE_MEMINFO':'MemAvailable: 184467440737095516160 kB\n'},43),
    ({'A7R5_NATIVE_MEMINFO':'MemTotal: 131072 kB\n'},43),
    ({'A7R5_NATIVE_MEMINFO':'MemAvailable: 65536 kB\nMemAvailable: 65536 kB\n'},43),
    ({'A7R5_NATIVE_RAM_AVAILABLE':'8684544'},44),
    ({'A7R5_NATIVE_RAM_AVAILABLE':'8684545'},0),
    ({'A7R5_NATIVE_RAM_OVERFLOW':'1'},44),
    ({'A7R5_NATIVE_FILE_LIMIT':'131071'},44),
    ({'A7R5_NATIVE_FILE_LIMIT':'131072'},0),
])
def test_new_budget_boundaries_and_invalid_resource_metadata(resource_native,tmp_path,extra,code):
    output,image,original,plan,work,mode=execute(resource_native,tmp_path,extra)
    assert f'code={code} target_writes={258 if code==0 else 0}' in output
    if code:
        assert image.read_bytes()==original and not (work/'ram').exists()
        assert 'memory_required_kib=32768' in output and 'partition_writes=0' in output
    else:
        assert all(f.stat().st_size<=131072 for f in (work/'ram').iterdir() if f.is_file())


def test_new_package_binds_resource_policy_and_loader_marker(tmp_path,baseline,ram_runtime):
    package,op=device.prepare_update(tmp_path,'2'*32,baseline,None,force=True)
    cfg=common.load(package/'config.json')
    assert cfg['trust_resource_policy']=='planned-sectors-32m-v1'
    assert op.memory_required_kib==32768
    assert b'A7R5_TRUST_FORCE_V3_RESOURCE_BUDGET' in op.payload


@pytest.mark.parametrize('fault',['old-policy','unknown-policy','old-loader','old-template-metadata'])
def test_resource_budget_policy_cannot_be_mixed_before_channel(tmp_path,baseline,ram_runtime,legacy_planned_force_payload,monkeypatch,fault):
    from trust_operation import Operation
    if fault=='old-template-metadata':
        templates=common.load(ram_runtime/'templates.json');templates['files']['trust-force.so'].pop('resource_policy')
        monkeypatch.setattr(device,'load',lambda path:templates if path==ram_runtime/'templates.json' else common.load(path))
        with pytest.raises(ValueError):device.prepare_update(tmp_path,'5'*32,baseline,None,force=True)
        return
    package,_=device.prepare_update(tmp_path,'5'*32,baseline,None,force=True)
    cfg=common.load(package/'config.json')
    if fault=='old-loader':(package/'materials/libJit.so').write_bytes(legacy_planned_force_payload)
    else:
        cfg['trust_resource_policy']='legacy-64m-v1' if fault=='old-policy' else 'unknown'
        (package/'config.json').write_text(json.dumps(cfg))
    with pytest.raises(ValueError):Operation(package,channel_factory=lambda *a:pytest.fail('预算混用不能创建通道'))


def test_legacy_planned_layout_remains_bound_to_old_budget(tmp_path,baseline,ram_runtime,legacy_planned_force_payload):
    from trust_operation import Operation
    package,_=device.prepare_update(tmp_path,'5'*32,baseline,None,force=True)
    cfg=common.load(package/'config.json');cfg.pop('trust_resource_policy')
    (package/'config.json').write_text(json.dumps(cfg));(package/'materials/libJit.so').write_bytes(legacy_planned_force_payload)
    op=Operation(package)
    assert op.sector_readback and op.memory_required_kib==65536 and op.resource_policy=='legacy-64m-v1'
