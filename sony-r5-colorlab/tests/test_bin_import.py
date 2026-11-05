"""通过真实本机HTTP约束BIN导入、来源绑定与再次导出。"""
import copy
import http.client
import io
import json
import subprocess
import zipfile

import pytest

from test_native24_web import ROOT, http_server, project, request
import core
import server


def upload(service, data, token=None):
    conn=http.client.HTTPConnection('127.0.0.1',service.server_port,timeout=20)
    conn.request('POST','/api/import-bin',data,headers={
        'Host':f'127.0.0.1:{service.server_port}',
        'X-R5-Token':server.TOKEN if token is None else token,
        'Content-Type':'application/octet-stream'})
    response=conn.getresponse();status,raw=response.status,response.read();conn.close()
    return status,raw


@pytest.mark.parametrize('slots,version',[(list(range(1,13)),4),([1,12],5),([1,12,24],5),(list(range(1,25)),5),([],4),([],5)])
def test_import_roundtrip_and_rename(http_server,slots,version):
    original=project(slots);original.pop('export_sources')
    original['schema']=core.compiler.SCHEMAS[version]
    binary=core.compiler.pack(original)
    status,raw=upload(http_server,binary)
    assert status==200,raw
    value=json.loads(raw);cfg=value['project']
    assert value['audit']['format_version']==version
    assert value['audit']['slots']==slots
    assert core.compiler.pack({k:v for k,v in cfg.items() if k!='export_sources'})==binary
    # JSON保存再加载、服务内部状态重建均使用落盘来源，不依赖内存登记表。
    cfg=json.loads(json.dumps(cfg))
    status,raw=request(http_server,'POST','/api/export',cfg)
    assert status==200,raw
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read('R5NATIVE.BIN')==binary
        audit=json.loads(archive.read('export_audit.json'))
        assert all(r['kind']=='imported-bin' for r in audit['grid_sources'])
    if slots:
        cfg['entries'][0].update(short_name='RENAME',full_name='导入改名')
        status,raw=request(http_server,'POST','/api/export',cfg)
        assert status==200,raw
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            decoded=core.compiler.unpack(archive.read('R5NATIVE.BIN'))
        assert decoded['entries'][0]['full_name']=='导入改名'


def test_relocation_to_slot24_and_color_binding(http_server):
    original=project([1]);original.pop('export_sources')
    status,raw=upload(http_server,core.compiler.pack(original));assert status==200,raw
    cfg=json.loads(raw)['project']
    cfg['entries'][0]['number']=24
    cfg['schema']=core.compiler.SCHEMAS[5]
    cfg['export_sources']['24']=cfg['export_sources'].pop('1')
    status,raw=request(http_server,'POST','/api/export',cfg);assert status==200,raw
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert core.compiler.unpack(archive.read('R5NATIVE.BIN'))['entries'][0]['number']==24
    for field in ('cc1_delta','block13','gamma_native_129','grid_5x9x9'):
        changed=copy.deepcopy(cfg);entry=changed['entries'][0]
        if field=='cc1_delta':entry[field][0][0]+=1
        elif field=='block13':entry[field][0][0][0]+=1
        elif field=='gamma_native_129':entry[field][64]+=1
        else:entry[field]['coefficients'][0][0][0][0]+=1
        status,_=request(http_server,'POST','/api/export',changed)
        assert status==400,field
    source=cfg['export_sources']['24']
    for forged in (dict(source,sha256='../bad'),dict(source,source_number=True),dict(source,source_number=2)):
        changed=copy.deepcopy(cfg);changed['export_sources']['24']=forged
        status,_=request(http_server,'POST','/api/export',changed);assert status==400
    cache=server.RUNS/'_bin_imports'/f"{source['sha256']}.bin"
    saved=cache.read_bytes();cache.write_bytes(saved[:-1])
    status,_=request(http_server,'POST','/api/export',cfg);assert status==400


@pytest.mark.parametrize('damage',['empty','crc','truncated','oversize','model','v4_high_slot'])
def test_reject_invalid_without_storing(http_server,damage):
    import struct,zlib
    cfg=project([24]);cfg.pop('export_sources');data=bytearray(core.compiler.pack(cfg))
    if damage=='empty':data=bytearray()
    elif damage=='crc':data[220]^=1
    elif damage=='truncated':data.pop()
    elif damage=='oversize':data=bytearray(core.compiler.MAXIMUM+1)
    else:
        if damage=='model':data[32]^=1
        else:data[:8]=b'R5CUST4\0';struct.pack_into('<I',data,8,4)
        struct.pack_into('<I',data,112,0);struct.pack_into('<I',data,112,zlib.crc32(data))
    status,_=upload(http_server,bytes(data));assert status==400
    assert not (server.RUNS/'_bin_imports').exists()


def test_upload_requires_existing_session_guard(http_server):
    status,_=upload(http_server,b'fixture',token='invalid');assert status==403
    assert not (server.RUNS/'_bin_imports').exists()


def test_slot_states_and_import_atomicity():
    result=subprocess.run(['node',str(ROOT/'tests/bin_import_ui.cjs'),str(ROOT/'R5ColorLab/web/static')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
