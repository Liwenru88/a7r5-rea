"""相对原生参数的零点、发送、持久化和原厂界面隔离。"""
import struct
import zlib

from test_native_e4_parameters import NativeE4Replay
from test_parameters import BASE, display_custom
from replay import recipe


def offsets(r, slot):
    at=r.ap.DATA+0x90000
    result=[]
    for p in range(8):
        assert r.ap.call('r5_tune_offset',slot,p,at)==0
        result.append(struct.unpack('<i',r.ap.read(at,4))[0])
    return tuple(result)


def edit(r,slot,values):
    for p,value in enumerate(values):
        assert r.ap.call('r5_tune_offset_edit',slot,p,value)==0


def test_all_twenty_four_display_zero_and_signed_native_ranges_preserve_registers():
    r=NativeE4Replay()
    r.boot()
    for slot in range(1,25):
        values,ids=display_custom(r,slot)
        assert values==(0,)*8 and ids==tuple(range(8)), '自定义八项初始显示必须全为零'
    table=r.ap.call('n12_parameter_table')
    for p,span in enumerate((18,18,18,9,18,9,4,9),1):
        row=struct.unpack('<12i',r.ap.read(table+p*48,48))
        assert row[8:11]==(span,-span,0)
    # 执行原生数值更新体，避免只核对表数据而遗漏独立的格式读取点。
    obj,records,widget,generic=(r.ap.DATA+v for v in (0x83000,0x85000,0x87000,0x88000))
    r.ap.write(obj+8,struct.pack('<I',3))
    r.ap.write(obj+0x90,struct.pack('<Q',records))
    r.ap.write(obj+0x3b18,struct.pack('<I',r.mid))
    option=[1]
    r.ap.stub(0x220b4e0,lambda a:option[0])
    r.ap.stub(0x220b868,lambda a:1)
    for at in (0x1afe958,0x1b2a5e4,0x21f7e40,0x20e3178):
        r.ap.stub(at,lambda a:generic)
    r.ap.stub(0x220b490,lambda a:widget)
    for p,span in enumerate((18,18,18,9,18,9,4,9)):
        option[0]=p+1
        for value in (-span,0,span):
            assert r.ap.call('r5_tune_offset_edit',24,p,value)==0
            r.ap.call(0x220ba00,obj)
            assert struct.unpack('<3i',r.ap.read(widget+0x30,12))==(0,value,0), '原生数字控件必须使用带符号偏移格式'
    event=r.ap.DATA+0x89000
    r.ap.write(event+0xc,struct.pack('<I',0xd))
    r.ap.stub(0x1af11f0,lambda a:0x16)
    r.ap.stub(0x220929c,lambda a:option[0])
    for p in range(8):
        option[0]=p+1
        r.ap.write(event+0x30,b'\xff')
        assert r.ap.call('n12_direct',obj,event)==1
        assert offsets(r,24)[p]==-1
        r.ap.call('n12_step_'+str(p),obj,0)
        assert offsets(r,24)[p]==0
    from unicorn import arm64_const as A
    for name in ('n12_parameter_table_x27','n12_parameter_table_x0','n12_parameter_table_x1'):
        for p in range(1,19):
            r.ap.cpu.reg_write(getattr(A,'UC_ARM64_REG_X'+str(p)),0x100+p)
        r.ap.cpu.reg_write(A.UC_ARM64_REG_NZCV,0xa0000000)
        result=r.ap.call(name,0x1234)
        assert result==(table if name.endswith('x0') else 0x1234)
        assert r.ap.cpu.reg_read(A.UC_ARM64_REG_NZCV)==0xa0000000
        for p in range(1,19):
            expected=table if name.endswith('x1') and p==1 else 0x100+p
            assert r.ap.cpu.reg_read(getattr(A,'UC_ARM64_REG_X'+str(p)))==expected
    r.mid=0x84c
    assert r.ap.call('n12_parameter_table')==0x4284050
    r.record('relative-zero-and-native-range-shims')


def test_offsets_follow_native_changes_clamp_without_losing_intent_and_reset():
    r=NativeE4Replay()
    r.native_source_values=(2,-1,3,1,-2,6,2,4)
    r.boot()
    display_custom(r,1)
    r.choose(1);r.service()
    assert offsets(r,1)==(0,)*8 and r.cp_values()==r.native_source_values
    delta=(1,-2,2,-1,2,1,-1,-2)
    edit(r,1,delta)
    r.choose(1);r.service()
    assert r.cp_values()==(3,-3,5,0,0,7,1,2)
    assert offsets(r,1)==delta
    r.native_target(0x84c);r.service()
    r.native_source_values=(-3,2,-2,0,4,2,4,1)
    r.choose(1);r.service()
    assert r.cp_values()==(-2,0,0,0,6,3,3,0)
    assert offsets(r,1)==delta
    assert r.ap.call('r5_tune_offset_edit',1,6,4)==0
    r.choose(1);r.service()
    assert r.cp_values()[6]==5 and offsets(r,1)[6]==4
    assert r.ap.call('r5_tune_reset',1)==0
    r.choose(1);r.service()
    assert offsets(r,1)==(0,)*8 and r.cp_values()==r.native_source_values
    assert r.files['R5NATIVE.BIN']==recipe()
    r.record('relative-native-change-clamp-reset')


def test_legacy_absolute_file_converts_to_offsets_and_same_identity_survives_restart():
    r=NativeE4Replay()
    r.boot();display_custom(r,1)
    edit(r,1,(1,1,1,1,1,1,1,1))
    r.choose(1);r.service()
    old=bytearray(r.files['R5TUNE.BIN'])
    assert old[:8]==b'R5TUNE2\0'
    old[6]=ord('1');struct.pack_into('<I',old,8,1)
    for at in range(64,len(old),48):
        initial=struct.unpack_from('8b',old,at+32)
        delta=struct.unpack_from('8b',old,at+40)
        struct.pack_into('8b',old,at+40,*(a+d for a,d in zip(initial,delta)))
    struct.pack_into('<I',old,24,0)
    struct.pack_into('<I',old,24,zlib.crc32(old))
    files=dict(r.files);files['R5TUNE.BIN']=bytes(old)
    restored=NativeE4Replay(files=files)
    restored.boot()
    assert offsets(restored,1)==(1,)*8
    assert restored.cp_values()==tuple(v+1 for v in BASE)
    assert restored.ap.call('r5_tune_offset_edit',1,0,2)==0
    restored.choose(1);restored.service()
    assert restored.files['R5TUNE.BIN'][:8]==b'R5TUNE2\0'
    restarted=NativeE4Replay(files=restored.files)
    restarted.boot()
    assert offsets(restarted,1)==(2,1,1,1,1,1,1,1)
    assert restarted.cp_values()==(2,1,1,1,1,5,4,2)
    restarted.record('relative-legacy-migration-and-restart')


def test_first_capture_keeps_concurrent_offset_and_failed_publish_rolls_back():
    r=NativeE4Replay()
    r.native_source_values=(2,-1,3,1,-2,6,2,4)
    r.boot();display_custom(r,1)
    r.fail_tune_publish=True
    r.choose(1);r.service()
    assert r.selected()==(0,0,0) and 'R5TUNE.BIN' not in r.files
    injected=[]
    original=r.native_transport
    def concurrent(ap):
        packet=ap.read(ap.arg(1),12)
        result=original(ap)
        if not injected and struct.unpack_from('<H',packet,2)[0]==0x4030:
            injected.append(True)
            context=ap.cpu.context_save()
            try:assert ap.call('r5_tune_offset_edit',1,0,1)==0
            finally:ap.cpu.context_restore(context)
        return result
    r.ap.stub(0x16dafc0,concurrent)
    r.choose(1);r.service()
    assert injected and offsets(r,1)==(1,0,0,0,0,0,0,0)
    assert r.cp_values()==r.native_source_values
    r.choose(1);r.service()
    assert r.cp_values()==(3,*r.native_source_values[1:])
    assert 'R5RECOV.BIN' not in r.files and 'R5TREC.BIN' not in r.files
    r.record('relative-first-capture-concurrency')


def test_full_history_reports_capacity_without_losing_old_offsets_or_blocking_look():
    import hashlib
    from test_parameters import BASE

    history = bytearray(64)
    history[:8] = b'R5TUNE2\0'
    struct.pack_into('<III', history, 8, 2, 128, 1)
    for identity in range(128):
        history += hashlib.sha256(f'old-recipe-{identity}'.encode()).digest() + bytes(BASE) + bytes(8)
    struct.pack_into('<I', history, 24, zlib.crc32(history))
    r = NativeE4Replay(files={'R5NATIVE.BIN': recipe(), 'R5TUNE.BIN': bytes(history)})
    r.boot()
    r.choose(13)
    r.service()
    assert r.selected() == (13, 13, 13)
    title = r.ap.call('n12_title_name', r.mid)
    assert r.ap.string(r.ap.call('n12_text', title)).startswith('[微调已满]')
    assert r.files['R5TUNE.BIN'] == history
