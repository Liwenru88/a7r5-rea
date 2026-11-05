"""只执行原任务分派／位掩码逻辑；在系统或图像入口前停止，不模拟CP硬件。"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'a7r5-firmware-features/custom-filters'))
from a7filters.cp_machine import CpMachine,WORK,STACK
from a7filters.access_evidence import CP_SHA,require_source


def audit(raw):
    require_source(raw,CP_SHA,'CP');machine=CpMachine(raw)
    machine.map_ram(0x1912000,4096);machine.map_ram(0x1915000,4096)
    task,obj=WORK+0x100,WORK+0x1000;machine.put(task,struct.pack('<I',obj))
    cases=[]
    for entry,targets in [(0x4694c4,(0x46f1c4,0xae80cc,0xae843e,0x46da78)),
                          (0x469620,(0x4700cc,0xae80cc,0xae843e,0x46da78)),
                          (0x4696d0,(0xae7336,0x480de4,0x470314))]:
        for state,target in enumerate(targets):
            machine.put(task+0x27,bytes([state]));result=machine.run(entry,arguments=(task,),stop_before=(target,),limit=512)
            assert result['status']=='STOPPED_BEFORE_BOUNDARY' and machine.register('r0')==task
            stack_bytes=16 if target==0x46da78 else 0
            assert machine.register('sp')==STACK+0xe000-stack_bytes
            cases.append(dict(entry=hex(entry),state=state,original_target=hex(target),task_argument_preserved=True,original_active_stack_bytes=stack_bytes))
    calls=[]
    for entry,expected in ((0x46f286,0x2b),(0x47020a,0x2b),(0x4704c2,0x7f),(0x46ff76,0xeb)):
        machine.register('r4',obj)
        result=machine.run(entry,stop_before=(0x46f3ac,),limit=32)
        assert result['status']=='STOPPED_BEFORE_BOUNDARY' and machine.register('r0')==obj and machine.register('r1')==expected
        calls.append(dict(entry=hex(entry),mask=hex(expected),same_A_argument=True))
    gamma=[]
    for mask in (0x2b,0x7f,0xeb,0x80):
        machine.register('sb',mask);machine.register('sl',obj)
        result=machine.run(0x46f57a,0x46f60e,stop_before=(0xaec71a,),limit=64,returned=False)
        submitted=result['status']=='STOPPED_BEFORE_BOUNDARY'
        assert submitted==bool(mask&0x80)
        if submitted:assert machine.register('r0')==obj
        gamma.append(dict(mask=hex(mask),calls_Gamma_helper=submitted,stopped_before_helper=submitted))
    machine.register('r0',0);machine.register('r1',0)
    result=machine.run(0xae559e,0xae5662,limit=128,returned=False)
    assert result['status']=='WINDOW_EXECUTED'
    entries={index:machine.word(0x1912d78+20*index+8) for index in (2,4,5)}
    assert entries=={2:0x4694c5,4:0x469621,5:0x4696d1}
    selection=[];plan=WORK+0x3000;output=WORK+0x800
    machine.put(obj+0x5994,struct.pack('<I',plan))
    for choice in (2,4):
        machine.put(plan+0x14,struct.pack('<I',choice))
        result=machine.run(0xae4496,arguments=(output,task),stop_before=(0xaea126,),limit=64)
        assert result['status']=='STOPPED_BEFORE_BOUNDARY' and machine.register('r0')==obj
        assert machine.register('r1')==11 and machine.register('r2')==choice
        # 原记录/通知调用未执行；另测纯表复制窗口，不声称已完成整段planner。
        machine.register('r4',choice);machine.register('r8',output)
        result=machine.run(0xae44d2,0xae44ea,limit=32,returned=False)
        assert result['status']=='WINDOW_EXECUTED' and machine.word(output+8)==entries[choice]
        selection.append(dict(plan_choice=choice,source='[A+0x5994]+0x14',stage=11,callback=hex(entries[choice]),
                              record_or_notify_helper_executed=False))
    windows=[(0x4694c4,0x8c),(0x469620,0x8c),(0x4696d0,0xac),(0x46f286,8),
             (0x47020a,8),(0x46f57a,0x12),(0xaec71a,6),(0xae559e,0xc4),(0xae4496,0x54)]
    return dict(status='PASS_ORIGINAL_PHOTO_DISPATCH_AND_GAMMA_MASK_SOFTWARE_ONLY',CP_sha256=CP_SHA,
        dispatch=cases,common_core_calls=calls,gamma_guard=gamma,original_callback_table={str(k):hex(v) for k,v in entries.items()},
        original_stage11_plan_selection=selection,
        windows=[dict(address=hex(a),bytes=n,sha256=hashlib.sha256(raw[a-0x108000:a-0x108000+n]).hexdigest()) for a,n in windows],
        special_2B_has_explicit_Gamma_submit=False,special_2B_Gamma_lineage_closed=False,
        special_request_type4_type9_mapping_revalidated=False,
        original_bank_ownership_or_prior_Gamma_producer_verified=False,actual_pixels_verified=False,
        system_or_image_helper_executed=False,hardware_emulated=False,camera_io=False,CP_modified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    out=args.output.absolute();assert out.is_relative_to(ROOT/'.local/fixed-custom-filters') and not out.exists()
    source=ROOT/'.local/fixed-custom-filters/integration52-source406/components/cpapp-b.bin'
    raw=source.read_bytes();report=audit(raw)
    # 原身份门禁也实际执行一次拒绝路径，不将任意CP当作同源照片路由。
    changed=bytearray(raw);changed[0]^=1
    try:audit(bytes(changed))
    except ValueError:report['wrong_CP_rejected']=True
    else:raise AssertionError('错误CP未被拒绝')
    report['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    out.mkdir(parents=True);(out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],dispatch_cases=len(report['dispatch']),special_Gamma_lineage_closed=False)))


if __name__=='__main__':main()
