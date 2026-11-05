"""纯宿主快照/完整载荷校验；运行时数值是显式夹具，不是个人相机设置。"""
import base64
import ctypes as c
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import pytest

HERE=Path(__file__).resolve().parents[1]
ROOT=next(p for p in (HERE,*HERE.parents) if (p/'a7r5-firmware-features/custom-filters/baseline.json').is_file())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'
MATERIALS=ROOT/'a7r5-firmware-features/materials'


class Frame(c.Structure):
    _fields_=[('ap',c.c_uint8*32),('cp',c.c_uint8*32),('ready',c.c_uint32),('photo',c.c_uint32),
              ('live',(c.c_int32*18)*11),('shadow',(c.c_int32*18)*11),('mask',c.c_uint32*18)]


class Asset(c.Structure):
    _fields_=[('slot',c.c_uint32),('name_bytes',c.c_uint32),('name',c.c_char*64),
              ('tone',c.c_int16*3),('matrix',c.c_int16*27),('cc1',c.c_int16*24),('grid',c.c_int8*1215)]


class Slot(c.Structure):
    _fields_=[('slot',c.c_uint32),('selector',c.c_uint32),('wire',c.c_uint32),('mask',c.c_uint32),
              ('live',c.c_int32*11),('shadow',c.c_int32*11),('asset',Asset)]


class Snapshot(c.Structure):
    _fields_=[('ap',c.c_uint8*32),('cp',c.c_uint8*32),('photo',c.c_uint32),('slots',Slot*6)]


class Basis(c.Structure):
    _fields_=[('tone',c.c_int16*3),('matrix',c.c_int16*18),('cc1',c.c_int16*24),('grid',c.c_int8*1215)]


def materials():
    assets=(Asset*6)();documents=[]
    layout=json.loads((MATERIALS/'joint-layout.json').read_text())
    payload=bytes.fromhex(next(p['after']for p in layout['patches']if p['offset']==0x10cb000))
    for i,path in enumerate(sorted((MATERIALS/'upstream-default-six').glob('*.a7look'))):
        doc=json.loads(path.read_text());documents.append(doc);basis=doc['native_photo']['runtime_basis'];a=assets[i]
        a.slot=i+1;a.name=doc['name'].encode();a.name_bytes=len(a.name);a.tone[:]=basis['tone_q10']
        expanded=[]
        for x,y,z,u,v,w in basis['matrix_planes']:expanded.extend((x+y,-x,-y,-z,z+u,-u,-v,-w,v+w))
        a.matrix[:]=expanded;a.cc1[:]=[x for row in basis['chroma_planes']for x in row]
        a.grid[:]=struct.unpack('1215b',base64.b64decode(doc['table_base64']))
        # 独立既有CP补丁后像约束，不能只用JSON重新生成自身期望。
        assert struct.pack('<54h',*a.tone,*a.matrix,*a.cc1)==payload[i*108:(i+1)*108]
    return assets,documents


def frame():
    f=Frame();f.ap[:]=bytes.fromhex('d15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9')
    f.cp[:]=bytes.fromhex('18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97');f.ready=f.photo=1
    for slot in range(6):
        index=slot+10
        for field,value in enumerate([slot,10,11,-9,-8,7,6,-5,4,3,2]):
            f.live[field][index]=f.shadow[field][index]=value
        f.mask[index]=(1<<0)|(1<<3)|(1<<9)
    return f


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    out=tmp_path_factory.mktemp('legacy406')/'legacy.so'
    command=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        '-I'+str(NATIVE),'-I'+str(HERE/'native'),str(HERE/'native/af_legacy406.c'),
        *[str(NATIVE/n)for n in ['af_joint.c','af_sha256.c','af_slots.c']],'-o',str(out)]
    result=subprocess.run(command,capture_output=True,text=True);assert result.returncode==0,result.stderr
    x=c.CDLL(str(out))
    x.af_legacy406_asset_valid.argtypes=[c.POINTER(Asset)]
    x.af_legacy406_capture.argtypes=[c.POINTER(Frame),c.POINTER(Frame),c.POINTER(Asset),c.POINTER(Snapshot)]
    x.af_legacy406_basis.argtypes=[c.POINTER(Asset),c.POINTER(Basis)]
    x.af_legacy406_gamma.argtypes=[c.POINTER(Asset),c.POINTER(c.c_uint32),c.POINTER(c.c_uint32)]
    x.af_legacy406_to_ajr1.argtypes=[c.POINTER(Snapshot),c.c_uint32,c.c_void_p]
    return x


def test_capture_keeps_fixed_identity_all_runtime_values_and_complete_payload(api):
    assets,_=materials();before=frame();after=Frame.from_buffer_copy(before);out=Snapshot()
    original=(bytes(before),bytes(after),bytes(assets))
    assert api.af_legacy406_capture(c.byref(before),c.byref(after),assets,c.byref(out))==0
    for i,s in enumerate(out.slots):
        assert (s.slot,s.selector,s.wire)==(i+1,i+10,i+249)
        assert list(s.live)==[i,10,11,-9,-8,7,6,-5,4,3,2]
        assert list(s.shadow)==list(s.live) and s.mask==before.mask[i+10]
        assert bytes(s.asset)==bytes(assets[i])
    assert original==(bytes(before),bytes(after),bytes(assets))
    # 与旧六槽无关的原厂行不是迁移输入，不增加修改或读取要求。
    after.live[3][0]=99
    assert api.af_legacy406_capture(c.byref(before),c.byref(after),assets,c.byref(out))==0


@pytest.mark.parametrize('case',['changed','not-ready','unknown-source','range','shadow-conflict','grid','joint','wrong-base','wrong-slot'])
def test_invalid_or_unstable_inputs_do_not_publish_snapshot(api,case):
    assets,_=materials();before=frame();after=Frame.from_buffer_copy(before)
    out=Snapshot.from_buffer_copy(b'\xa5'*c.sizeof(Snapshot));untouched=bytes(out)
    if case=='changed':after.live[3][10]+=1
    elif case=='not-ready':before.ready=after.ready=0
    elif case=='unknown-source':after.ap[0]^=1
    elif case=='range':before.live[9][10]=after.live[9][10]=0
    elif case=='shadow-conflict':before.shadow[3][10]=after.shadow[3][10]=1
    elif case=='grid':assets[0].grid[0]^=1
    elif case=='joint':assets[0].cc1[0]+=1
    elif case=='wrong-base':before.live[0][10]=after.live[0][10]=12
    else:assets[0].slot=2
    assert api.af_legacy406_capture(c.byref(before),c.byref(after),assets,c.byref(out))<0
    assert bytes(out)==untouched


@pytest.mark.parametrize('index',range(6))
def test_lossless_basis_and_conditional_gamma_keep_all_legacy_components(api,index):
    assets,docs=materials();a=assets[index];basis=Basis();raw=docs[index]['native_photo']['runtime_basis']
    assert api.af_legacy406_asset_valid(c.byref(a))==0
    assert api.af_legacy406_basis(c.byref(a),c.byref(basis))==0
    assert list(basis.matrix)==[x for row in raw['matrix_planes']for x in row]
    assert list(basis.tone)==list(a.tone) and list(basis.cc1)==list(a.cc1) and bytes(basis.grid)==bytes(a.grid)
    stock=(c.c_uint32*129)(*[i*0x3ffff//128 for i in range(129)]);output=(c.c_uint32*129)()
    assert api.af_legacy406_gamma(c.byref(a),stock,output)==0
    expected=[]
    for y in stock:
        x=y*4096//stock[-1];v=4096-x
        value=y+(y*a.tone[0]//1024)
        value+=((y*a.tone[1]//1024)*v//4096)*v//4096
        value+=((y*a.tone[2]//1024)*x//4096)*v//4096
        expected.append(max(0,min(0x3ffff,value)))
    assert list(output)==expected  # 显式数值曲线夹具，不声称是相机当前ST。
    before=frame();after=Frame.from_buffer_copy(before);snapshot=Snapshot()
    assert api.af_legacy406_capture(c.byref(before),c.byref(after),assets,c.byref(snapshot))==0
    joint=c.create_string_buffer(b'\x5a'*4096);untouched=joint.raw
    assert api.af_legacy406_to_ajr1(c.byref(snapshot),index+1,joint)==-40 and joint.raw==untouched


def test_output_aliases_and_invalid_gamma_leave_inputs_unchanged(api):
    assets,_=materials();before=frame();after=Frame.from_buffer_copy(before);original=bytes(before)
    assert api.af_legacy406_capture(c.byref(before),c.byref(after),assets,c.cast(c.byref(before),c.POINTER(Snapshot)))==-1
    assert bytes(before)==original
    output=(c.c_uint32*129)(*[123]*129);untouched=bytes(output);missing=(c.c_uint32*129)()
    assert api.af_legacy406_gamma(c.byref(assets[0]),missing,output)==-1 and bytes(output)==untouched
