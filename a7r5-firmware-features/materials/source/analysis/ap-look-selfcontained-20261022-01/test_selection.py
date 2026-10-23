"""以本次真实设置和照片固定失败契约，不从新补丁生成期望值。"""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import pytest

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(ROOT/'analysis/fl23-candidates-20261021/reference/tools'))
import ap_patch
from offline_cpu import run
from sony_bk4 import find_banks

EVIDENCE=ROOT/'analysis/fl23-device-regression-20261022-01'


@pytest.fixture(scope='module')
def programs():
    old=ap_patch.SOURCE.read_bytes();new,receipt=ap_patch.build(old)
    return old,new,receipt


def settings_rows(ap,filename):
    banks=find_banks(filename.read_bytes());rows=[]
    for mode,api0,bind0 in [('current',0x163a,0x56648a4),('still',0x164c,0x5664ae4),('movie',0x165e,0x5664d24)]:
        for index in range(10,18):
            at=bind0+index*32;api=struct.unpack_from('<I',ap,at-12)[0];pid=struct.unpack_from('<I',ap,at)[0]
            assert api==api0+index
            props=[]
            for b in banks:
                try:props.append(b.property(pid))
                except KeyError:pass
            assert len(props)==1 and props[0].attributes==0x60 and len(props[0].data)==1
            rows.append((mode,index if index<16 else index+1,props[0].data[0]))
    return rows


@pytest.mark.parametrize('file',('device-settings-03/Backup.bin','device-readonly-02/settings-bak.bin'))
@pytest.mark.parametrize('route',('direct','bulk','notify'))
def test_real_camera_old_settings_need_no_separate_provisioning(programs,file,route):
    for mode,selector,base in settings_rows(programs[0],EVIDENCE/file):
        expected=249+selector-10 if selector<16 else {17:19,18:20}[selector]
        result=run(programs[1],selector,base,route)
        assert result['wire']==expected,(mode,selector,base,route,result)
        assert not result['diagnostic']
        if route=='notify':
            assert result['calls'][0]['id']==0x402f
            assert bytes.fromhex(result['calls'][1]['data'])[8:12]==bytes([expected,0,0,0])


def test_photos_are_the_original_failure_evidence_not_new_acceptance(programs):
    photos=json.loads((EVIDENCE/'photo-parameter-comparison.json').read_text())
    for name in ('ST','FL2','FL3'):
        row=photos['files'][name+'.ARW']
        assert row['MakerNote']=={'b020':'Standard','b029':0}
        assert row['SR2_current']['7770']['value']=='Standard'
    assert run(programs[0],17,0)['wire']==0 and run(programs[0],18,0)['wire']==0
    assert run(programs[1],17,0)['wire']==19 and run(programs[1],18,0)['wire']==20


def test_reset_defaults_cover_current_still_movie_and_preserve_other_looks(programs):
    old,new,_=programs
    for index in range(54):
        pos=ap_patch.DEFAULTS+index*8
        api,old_value=struct.unpack_from('<II',old,pos);new_api,value=struct.unpack_from('<II',new,pos)
        assert api==new_api==0x163a+index
        slot=index%18
        expected=0 if 10<=slot<=15 else {16:10,17:11}.get(slot,old_value)
        assert value==expected,(hex(api),value,expected)
        if slot>=10:
            selector=slot if slot<16 else slot+1
            expected_wire=249+slot-10 if slot<16 else {16:19,17:20}[slot]
            assert run(new,selector,value)['wire']==expected_wire


def test_titles_do_not_depend_on_saved_custom_slot_base(programs):
    for i in range(6):
        for base in range(12):
            assert run(programs[1],0,base,title_id=0x858+i)['wire']==0x200abd8+i
    for title_id in (0x857,0x85e,0,0xffff):
        for base in range(12):
            assert run(programs[0],0,base,title_id=title_id)==run(programs[1],0,base,title_id=title_id)


def test_switches_are_deterministic_for_stale_and_valid_bases(programs):
    for selector,expected in ((17,19),(18,20),*((10+i,249+i)for i in range(6))):
        for base in (*range(12),0xff,0xffffffff):
            assert run(programs[1],selector,base)['wire']==expected
    # 原生非目标菜单和诊断行为逐项与旧程序比较。
    for selector in (*range(10),16,19,0xffffffff):
        for base in (*range(12),12,0xff,0xffffffff):
            assert run(programs[1],selector,base)==run(programs[0],selector,base),(selector,base)


def test_unknown_or_already_patched_preimage_is_rejected(programs):
    bad=bytearray(programs[0]);bad[0x100]^=1
    with pytest.raises(ValueError,match='前像'):ap_patch.build(bytes(bad))
    with pytest.raises(ValueError,match='前像'):ap_patch.build(programs[1])


@pytest.mark.parametrize('mode',('still','movie'))
def test_actual_AP_notifications_enter_CP_with_distinct_native_and_joint_matrices(programs,mode):
    from verify_r5_m4strict_cp_cpu import full_selector, SCRATCH, STOP
    from verify_r5_m4strict_cp import matrix_cpu,matrix_run
    from unicorn.arm_const import UC_ARM_REG_R4,UC_ARM_REG_PC
    cp=(ROOT/'analysis/joint-look-adaptation-20261022-01/package/components/cpapp-b.bin').read_bytes()
    banks=find_banks((EVIDENCE/'device-settings-03/Backup.bin').read_bytes())
    def prop(pid):
        for bank in banks:
            try:return bank.property(pid).data
            except KeyError:pass
        raise AssertionError(hex(pid))
    matrix=prop(0x02a4000d);cc1=prop(0x02a40001)
    baseline_cpu=matrix_cpu(cp,matrix)
    baseline=matrix_run(baseline_cpu,21 if mode=='movie' else 0,0,(1024,1024,1024))[:54]
    layout=json.loads((ROOT/'analysis/joint-look-adaptation-20261022-01/package/materials/joint-layout.json').read_text())
    outcomes=[]
    for row_mode,selector,base in settings_rows(programs[0],EVIDENCE/'device-settings-03/Backup.bin'):
        if row_mode!=mode:continue
        notification=run(programs[1],selector,base,'notify')
        wire=bytes.fromhex(notification['calls'][-1]['data'])[8]
        selected,_=full_selector(cp,wire,mode,prop=cc1)
        profile=selected[1]
        assert profile==(({17:54,18:55}[selector]+(2 if mode=='movie' else 0)) if selector>=17 else (21 if mode=='movie' else 0))
        cpu=matrix_cpu(cp,matrix)
        # 执行本包原有复制窗口；不直接用夹具填充联合参数目标RAM。
        cpu.reg_write(UC_ARM_REG_R4,0x128000)
        cpu.emu_start(0x108f41,STOP,count=150000)
        assert cpu.reg_read(UC_ARM_REG_PC)==STOP
        state=SCRATCH+0x7000
        cpu.mem_write(SCRATCH+0x1000,struct.pack('<I',state))
        cpu.mem_write(state+1,bytes([0 if mode=='still' else 1]))
        cpu.mem_write(state+0x2e,bytes([wire]))
        actual=matrix_run(cpu,profile,0,(1024,1024,1024))[:54]
        if selector<16 and mode=='still':
            delta=layout['basis'][selector-10]['matrix_planes']
            expected=[]
            for a,b,c,d,e,f in delta:expected.extend((a+b,-a,-b,-c,c+d,-d,-e,-f,e+f))
            base_values=struct.unpack('<27h',baseline)
            assert actual==struct.pack('<27H',*((x+y)&65535 for x,y in zip(base_values,expected)))
        elif selector<16:
            # 上游联合增量限定照片参数0；视频profile21保留原包行为，不能伪造照片增量已用于视频。
            assert actual==baseline
        else:assert actual!=baseline
        outcomes.append(actual)
    assert len(outcomes)==8 and outcomes[-1]!=outcomes[-2]
    # 单个矩阵可相同；六款以色表、曲线、矩阵、色度的组合区分。
    materials=ROOT/'analysis/joint-look-adaptation-20261022-01/package/materials'
    assert len({(json.dumps(layout['basis'][i],sort_keys=True),
                 (materials/f'slot{i+1}.raw-s8.bin').read_bytes()) for i in range(6)})==6


def test_provided_photos_remain_unchanged():
    import hashlib
    photos=json.loads((EVIDENCE/'photo-parameter-comparison.json').read_text())
    for row in photos['files'].values():
        assert hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()==row['sha256']


def test_only_explicit_AP_ranges_change_and_all_old_features_remain(programs):
    old,new,receipt=programs
    restored=bytearray(new)
    for p in receipt['patches']:
        restored[p['offset']:p['offset']+p['bytes']]=bytes.fromhex(p['before'])
        at=p['offset']
        assert at==ap_patch.ENTRY or at==ap_patch.TITLE+24 or (
            ap_patch.DEFAULTS<=at<ap_patch.DEFAULTS+54*8 and (at-ap_patch.DEFAULTS)%8==4)
    assert bytes(restored)==old and len(old)==len(new)
    for lo,hi in ((0,0x1000),(0x20c99a4,0x20c99c0),(0x20c9ea4,0x20c9ecc),
                  (0x347b6dc,0x347b900),(0x3f4a000,0x3f4ad00)):
        assert new[lo:hi]==old[lo:hi]
