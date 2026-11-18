"""AJR1原表快照适配的宿主测试；地址/模型均为明确契约夹具，不执行CP。"""
import ctypes as c
import hashlib
from pathlib import Path
import struct
import subprocess

import pytest

HOME=Path(__file__).resolve().parents[1]
ROOT=HOME.parent.parent
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'
STATE=0x18a
CONTEXT=0x6b4
CP=bytes.fromhex('18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97')
MODEL=hashlib.sha256(b'HOST_CONTRACT_ONLY_NOT_NATIVE_MODEL').digest()

class Preset(c.Structure):
    _fields_=[('base',c.c_uint8),('kind',c.c_uint8),('params',c.c_int8*8),
              ('payload_sha256',c.c_uint8*32),('lut_sha256',c.c_uint8*32)]
class Recipe(c.Structure):
    _fields_=[('gamma',c.c_uint32*129),('matrix',c.c_int16*18),
              ('cc1',c.c_int16*24),('grid',c.c_int8*1215)]
class Asset(c.Structure):
    _fields_=[('base',c.c_uint32),('model_sha256',c.c_uint8*32),('recipe',Recipe),
              ('native_mode',c.c_uint32),('native_tone',c.c_int16*3),('native_seed',c.c_uint32*129),
              ('matrix_mode',c.c_uint32),('sector_matrix',c.c_int16*288)]
class Table(c.Structure):
    _fields_=[('asset',Asset),('payload_sha256',c.c_uint8*32),
              ('slot',c.c_uint32),('level',c.c_uint32),('grid_address',c.c_uint32)]
class Key(c.Structure):
    _fields_=[('snapshot',c.c_uint64),('root',c.c_uint32),('c4',c.c_uint32),('source',c.c_uint32)]
class Token(c.Structure):
    _fields_=[('table',Table),('key',Key),('active',c.c_uint32)]

@pytest.fixture(scope='module')
def api(tmp_path_factory):
    output=tmp_path_factory.mktemp('grid406')/'source.so'
    cmd=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
         '-I'+str(NATIVE),str(HOME/'native/af_grid406_source.c'),
         *[str(NATIVE/name) for name in ('af_joint_asset.c','af_joint.c','af_sha256.c','af_slots.c','af_grid.c')],'-o',str(output)]
    run=subprocess.run(cmd,capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    lib=c.CDLL(str(output))
    lib.af_grid406_prepare.argtypes=[c.c_void_p,c.c_void_p,c.c_size_t,c.c_void_p,
                                     c.c_uint32,c.c_uint32,c.c_uint32,c.c_void_p]
    lib.af_grid406_capture.argtypes=[c.c_void_p]*3
    lib.af_grid406_overlay.argtypes=[c.c_void_p]*2+[c.c_uint32]*4+[c.c_void_p]*7
    lib.af_grid406_finish.argtypes=[c.c_void_p]*2
    lib.af_grid_pack.argtypes=[c.c_void_p,c.c_void_p,c.c_uint,c.c_void_p]
    return lib

def payload(seed=0):
    # 明确非零、独立变化四组件；这里只测试序列化与路由，不标成标定配方。
    gamma=[i*(700+seed) for i in range(129)]
    matrix=[(i*7+seed)%65-32 for i in range(18)]
    cc1=[(i*11+seed)%63-31 for i in range(24)]
    grid=[(i*29+17+seed)%128-64 for i in range(1215)]
    body=struct.pack('<129I18h24h1215b',*gamma,*matrix,*cc1,*grid)
    header=bytearray(128);header[:4]=b'AJR1'
    struct.pack_into('<HH6I',header,4,1,128,len(body),3,17,1,15,0)
    header[32:64]=CP;header[64:96]=MODEL
    result=header+body;result[96:128]=hashlib.sha256(result).digest()
    p=Preset(17,1,(c.c_int8*8)(0,0,0,0,0,0,3,0))
    p.payload_sha256[:]=hashlib.sha256(result).digest()
    p.lut_sha256[:]=hashlib.sha256(b'HOST_TEST_CUBE').digest()
    return p,bytes(result),bytes((x&255) for x in grid)

def prepare(api,seed=0,address=0x72000000,slot=7):
    preset,raw,grid=payload(seed);t=Table()
    assert api.af_grid406_prepare(c.byref(preset),raw,len(raw),MODEL,slot,8,address,c.byref(t))==0
    return t,grid

def buffers(key=None):
    a=(c.c_uint8*STATE)(*[i%256 for i in range(STATE)])
    b=(c.c_uint8*CONTEXT)(*[i*7%256 for i in range(CONTEXT)])
    struct.pack_into('<I',b,0x6b0,0x73000000)
    a[4]=255
    return a,b,(c.c_uint8*STATE)(*[165]*STATE),(c.c_uint8*CONTEXT)(*[165]*CONTEXT)

def overlay(api,t,k,a,b,o,q,mode=0,profile=0,level=8,query=0,source=None,raw_grid=None,state_c4=None):
    c4=(c.c_uint8*0xc4)()
    operation=(c.c_uint8*8)()
    struct.pack_into('<I',operation,4,k.c4 if state_c4 is None else state_c4)
    struct.pack_into('<I',c4,0,k.source if source is None else source)
    data=bytes(t.table.asset.recipe.grid) if raw_grid is None else raw_grid
    return api.af_grid406_overlay(c.byref(t),c.byref(k),mode,profile,level,query,data,operation,c4,a,b,o,q)

def test_complete_ajr1_nonzero_source_and_exact_native_field_overlay(api):
    table,grid=prepare(api);key=Key(41,0x71000100,0x71000200,0x71001000);token=Token()
    assert api.af_grid406_capture(c.byref(table),c.byref(key),c.byref(token))==0
    assert bytes(table.asset.recipe.grid)==grid
    assert list(table.asset.recipe.matrix)!=[0]*18 and list(table.asset.recipe.cc1)!=[0]*24
    a,b,o,q=buffers();before=(bytes(a),bytes(b))
    assert overlay(api,token,key,a,b,o,q)==0
    expected=bytearray(a);struct.pack_into('<I',expected,0x184,table.grid_address);expected[0x188:]=b'\x01\x02'
    expected_context=bytearray(b);expected_context[0x54]=255
    assert bytes(o)==expected and bytes(q)==expected_context and before==(bytes(a),bytes(b))
    assert bytes(o)[4:8]==bytes(a)[4:8] and struct.unpack_from('<I',o,4)[0]!=key.c4
    # 当前CP已证405项八银行排列的独立数学对照，不执行原CP或硬件。
    prefix=[0,75,135,195,243,293,333,373];permutation=[]
    for x in range(5):
        for y in range(9):
            for z in range(9):
                bank=4*(x&1)+2*(y&1)+(z&1)
                local=((x//2)*(5-(y&1))+y//2)*(5-(z&1))+z//2
                permutation.append(prefix[bank]+local)
    assert sorted(permutation)==list(range(405))
    p=(c.c_uint16*405)(*permutation);packed=(c.c_uint32*405)()
    assert api.af_grid_pack(table.asset.recipe.grid,p,8,packed)==0
    raw=struct.unpack('1215b',grid);expected_words=[0]*405
    for i,dest in enumerate(permutation):
        expected_words[dest]=sum(((raw[ch*405+i]&127)<<(22-10*ch)) for ch in range(3))
    assert list(packed)==expected_words
    # 结束token不伪造解引用清除或释放原表，也不改packed银行。
    retained=bytes(o),bytes(table),bytes(packed)
    assert api.af_grid406_finish(c.byref(token),c.byref(key))==0
    assert retained==(bytes(o),bytes(table),bytes(packed))
    assert overlay(api,token,key,a,b,o,q)==-5

def test_parallel_producer_same_controls_different_recipes_and_stale_root_reject(api):
    t1,g1=prepare(api,0,0x72000000);t2,g2=prepare(api,1,0x72001000,20)
    p1,_,_=payload(0);p2,_,_=payload(1)
    assert p1.base==p2.base and bytes(p1.params)==bytes(p2.params) and g1!=g2
    k1=Key(11,0x71000100,0x71000200,0x71001000)
    k2=Key(12,0x71010100,0x71010200,0x71011000)
    a1=Token();a2=Token()
    assert api.af_grid406_capture(c.byref(t1),c.byref(k1),c.byref(a1))==0
    assert api.af_grid406_capture(c.byref(t2),c.byref(k2),c.byref(a2))==0
    for token,key,address in ((a1,k1,t1.grid_address),(a2,k2,t2.grid_address)):
        state,context,out,ctx=buffers(key)
        assert overlay(api,token,key,state,context,out,ctx)==0
        assert struct.unpack_from('<I',out,0x184)[0]==address
    for changed in (k2,Key(13,k1.root,k1.c4,k1.source),Key(k1.snapshot,k1.root+4,k1.c4,k1.source),
                    Key(k1.snapshot,k1.root,k1.c4+4,k1.source),Key(k1.snapshot,k1.root,k1.c4,k1.source+4)):
        state,context,out,ctx=buffers();before=bytes(out),bytes(ctx)
        assert overlay(api,a1,changed,state,context,out,ctx)==-5
        assert before==(bytes(out),bytes(ctx))
    # 原table被下一配方替换后，旧token深拷贝仍稳定；同地址真实源若已被覆盖则拒绝。
    token_before=bytes(a1)
    replacement,_,_=payload(1)
    _,raw,_=payload(1)
    assert api.af_grid406_prepare(c.byref(replacement),raw,len(raw),MODEL,7,8,0x72000000,c.byref(t1))==0
    assert bytes(a1)==token_before
    state,context,out,ctx=buffers();before=bytes(out),bytes(ctx)
    assert overlay(api,a1,k1,state,context,out,ctx,raw_grid=bytes(t1.asset.recipe.grid))==-5
    assert before==(bytes(out),bytes(ctx))
    assert overlay(api,a1,k1,state,context,out,ctx,raw_grid=g1)==0
    # 只改recipe不更新摘要，capture不得接受旁边保留的旧payload_sha256。
    forged=Table.from_buffer_copy(t2);forged.asset.recipe.grid[-1]^=1
    fresh=Token.from_buffer_copy(b'\xa5'*c.sizeof(Token));untouched=bytes(fresh)
    assert api.af_grid406_capture(c.byref(forged),c.byref(k2),c.byref(fresh))==-1
    assert bytes(fresh)==untouched
    # 函数实读原operation→C4和C4→source两级字段，不能混用grid_state+4。
    state,context,out,ctx=buffers(k2);before=bytes(out),bytes(ctx)
    assert overlay(api,a2,k2,state,context,out,ctx,state_c4=k1.c4)==-5 and before==(bytes(out),bytes(ctx))
    state,context,out,ctx=buffers(k2);before=bytes(out),bytes(ctx)
    assert overlay(api,a2,k2,state,context,out,ctx,source=k1.source)==-5 and before==(bytes(out),bytes(ctx))

def test_legacy_grid_adapter_rejects_sector_asset_before_publishing(api):
    from test_recipe_file_tool import asset
    legacy=asset();body=legacy[128:128+516]+bytes(576)+legacy[128+552:]
    raw=bytearray(legacy[:128]+body);raw[:5]=b'AJR3\x03'
    struct.pack_into('<2I',raw,8,2355,15);raw[96:128]=bytes(32)
    raw[96:128]=hashlib.sha256(raw).digest()
    preset=Preset(base=0,kind=1);preset.params[6]=3
    preset.payload_sha256[:]=hashlib.sha256(raw).digest();preset.lut_sha256[0]=1
    out=Table.from_buffer_copy(b'\xa5'*c.sizeof(Table));before=bytes(out)
    assert api.af_grid406_prepare(c.byref(preset),bytes(raw),len(raw),bytes(raw[64:96]),7,8,
                                  0x72000000,c.byref(out))==-30
    assert bytes(out)==before


def test_reject_old_slots_damaged_payload_unknown_model_mode_query_and_alias(api):
    preset,raw,_=payload();out=Table.from_buffer_copy(b'\xa5'*c.sizeof(Table));before=bytes(out)
    for slot in (0,1,6,21):
        assert api.af_grid406_prepare(c.byref(preset),raw,len(raw),MODEL,slot,8,0x72000000,c.byref(out))==-1
        assert bytes(out)==before
    bad=bytearray(raw);bad[-1]^=1
    assert api.af_grid406_prepare(c.byref(preset),bytes(bad),len(bad),MODEL,7,8,0x72000000,c.byref(out))==-1
    assert bytes(out)==before
    assert api.af_grid406_prepare(c.byref(preset),raw,len(raw),b'\0'*32,7,8,0x72000000,c.byref(out))==-5
    assert bytes(out)==before
    table,_=prepare(api);key=Key(1,0x71000100,0x71000200,0x71001000);token=Token()
    assert api.af_grid406_capture(c.byref(table),c.byref(key),c.byref(token))==0
    for kwargs in ({'mode':1},{'profile':1},{'query':4},{'level':7}):
        state,context,out,ctx=buffers();before=bytes(out),bytes(ctx)
        assert overlay(api,token,key,state,context,out,ctx,**kwargs) in (-21,-5)
        assert before==(bytes(out),bytes(ctx))
    state,context,out,ctx=buffers();before=bytes(out),bytes(ctx)
    struct.pack_into('<I',context,0x6b0,0)
    assert overlay(api,token,key,state,context,out,ctx)==-21 and before==(bytes(out),bytes(ctx))
    state,context,out,ctx=buffers();before=bytes(state),bytes(ctx)
    assert overlay(api,token,key,state,context,state,ctx)==-1 and before==(bytes(state),bytes(ctx))
