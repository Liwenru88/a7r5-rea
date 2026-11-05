"""交叉核对生产AP、原E4执行、真实CP view及客体选择文件；截图不能替代提交。"""
import argparse
import json
from pathlib import Path
import re
import struct
import zlib
from environment import DAT411_SHA,FONT_AP_SHA,E4_AP_SHA,CP_SHA,save,verified


def crc_ok(raw,offset):
    expected=struct.unpack_from('<I',raw,offset)[0]
    return zlib.crc32(raw[:offset]+bytes(4)+raw[offset+4:])==expected


def selection_file(state,selected):
    f=state.get('selection_file',{});raw=bytes.fromhex(f.get('hex',''))
    if f.get('bytes_read')!=24 or f.get('pending') or len(raw)!=24 or raw[:8]!=b'R5SEL4\0\0' or struct.unpack_from('<III',raw,8)!=(1,selected,0) or not crc_ok(raw,20):
        raise ValueError(f'选择文件未完整提交为{selected}')


def execution(console,refresh):
    serial=refresh['done'];obj=hex(refresh['object'])
    pattern=rf'^OBS A7R5_N12_E4_(ENTER|RETURN) tid=(\d+) object={obj} serial={serial} private=1$'
    events=[(i,re.fullmatch(pattern,line)) for i,line in enumerate(console)]
    events=[(i,m) for i,m in events if m]
    if len(events)!=2 or [m[1] for _,m in events]!=['ENTER','RETURN'] or events[0][1][2]!=events[1][1][2]:
        raise ValueError(f'没有指定私有E4对象{obj}／序号{serial}的原生执行返回证据')
    first,last=events[0][0],events[1][0];tid=events[0][1][2]
    returned=[];commands=[]
    for line in console[first+1:last]:
        match=re.fullmatch(rf'OBS A7R5_N12_DISPATCH_RETURN tid={tid} index=(\d+) params=0x[0-9a-f]+ result=0x[0-9a-f]+',line)
        if match:returned.append(int(match[1]))
        match=re.fullmatch(rf'OBS A7R5_N12_NATIVE_TX tid={tid} dest=0x90030001 source=0x80020002 size=12 payload=([0-9a-f]{{24}})',line)
        if match:
            raw=bytes.fromhex(match[1]);commands.append(struct.unpack_from('<H',raw,2)[0])
    if returned!=list(range(9)) or commands!=[0x402f,0x4030,0x40f3,0x40f4,0x40f5,0x4031,0x4032,0x40f6,0x40f7]:
        raise ValueError('E4原体的九次分派／参数请求未完整执行')
    return dict(serial=serial,object=obj,thread=int(tid),native_dispatches=returned,native_commands=[hex(x) for x in commands])


def check(run,manifest,mode):
    record=json.loads(manifest.read_text());files=verified(record)
    if record['DAT_sha256']!=DAT411_SHA or record['AP_sha256'] not in (FONT_AP_SHA,E4_AP_SHA) or record['CP_sha256']!=CP_SHA:
        raise ValueError('不是当前4.11组件')
    used=json.loads((run/'inputs.json').read_text())
    for name in ('binary','kernel','initrd','dtb'):
        path=run/'virt.dtb' if name=='dtb' else files[name]
        if used[str(path)]['sha256']!=record['files'][name]['sha256']:raise ValueError('运行输入与构建清单不同：'+name)
    cp_inputs=verified({'files':record['loading_inputs']});cp_command=json.loads((run/'cp/command.json').read_text())
    if f'loader,file={cp_inputs["cp"]},addr=0x108000,force-raw=on' not in cp_command or f'loader,file={cp_inputs["receiver"]},cpu-num=0' not in cp_command:
        raise ValueError('侧车未使用当前CP及接收器')
    actions=json.loads((run/'research-actions.json').read_text())
    initialization=json.loads((run/'native-initialization.json').read_text())
    isolated=initialization.get('menu_isolation',False)
    start=15 if isolated else 28
    if isolated:
        expected=['LEFT','LEFT','DOWN','DOWN','DOWN','RIGHT','DOWN','DOWN','DOWN','DOWN','DOWN','RIGHT','DOWN','DOWN','ENTER']
        if [row['action'] for row in actions[:start]]!=expected or actions[start-1]['screen']!=0xd9 or initialization['touch_guide_acknowledged_by_original_enter']:
            raise ValueError('菜单隔离导航证据不符')
    if record.get('native_frequency_lock'):
        setup=(run/'setup-13.log').read_text()
        for marker in ('command=6 argument=10 transport=0 status=0','CUR_STATE DFS_STATE_FULL','CUR_FREQ  DFS_FREQ_AVB_FULL_CPU_FULL','DFS_FACTOR_DEBUG','N12_UPM_FREQUENCY_LOCK_HELD'):
            if marker not in setup:raise ValueError('原厂频率锁未确认：'+marker)
    messages=json.loads((run/'cp/messages.json').read_text())
    original_console=(run/'console.log').read_text(errors='strict').replace('\r','')
    # 内核串口记录可插入用户态write中间；只剥离已观察到的完整固定UIPC日志，不补字节。
    normalized,removed=re.subn(r'\[\s*\d+\.\d+\] \[K\]\*\*UIPC ERROR\*\* osal_snd_msg: No snd_msg registered\. Skip snd to 0x[0-9a-f]+\n','',original_console)
    console=[line.removeprefix('/ # ') for line in normalized.splitlines()]
    results=[]
    def state(index):
        row=actions[index];name=f"research-{index:03d}-{row['action']}"
        return row,json.loads((run/f'loading-state-{name}.json').read_text())
    def cp_at(row,selected):
        subset=messages[:row['CP_messages']]
        selected_messages=[m for m in subset if bytes.fromhex(m['request'])[0]==0xea][-2:]
        if len(selected_messages)!=2:raise ValueError('缺少E4前后两次CP选择确认')
        for m in selected_messages:
            p=bytes.fromhex(m['request']);ack=bytes.fromhex(m['reply'])
            if len(p)!=32 or len(ack)!=32 or p[0:4]!=bytes.fromhex('ea010120') or ack[:4]!=bytes.fromhex('ea018120') or ack[4:24]!=p[4:24] or struct.unpack_from('<I',p,12)[0]!=selected or struct.unpack_from('<I',ack,24)[0] or not crc_ok(p,28) or not crc_ok(ack,28):
                raise ValueError('CP选择回执与本次参数／编号不匹配')
            if m.get('CP_selected')!=selected or m.get('CP_control_selected')!=selected or not m.get('CP_active_view') or m['heap_allocations']!=1:
                raise ValueError('真实CP的活动view未切换或发生重复分配')
        return selected_messages[-1]['CP_active_view']
    def committed(index,selected,action):
        row,s=state(index)
        if row['action']!=action or s['available_mask']!=4095 or s['selected']!=selected or s['command_state']!=2:
            raise ValueError(f'第{index}次操作未将滤镜{selected}提交为成功，实际selected={s["selected"]} state={s["command_state"]}')
        refresh=s['native_refresh']
        if refresh['wait'] or not refresh['done']:raise ValueError('E4仍等待或未完成')
        selection_file(s,selected);view=cp_at(row,selected)
        result=dict(action_index=index,selected=selected,CP_active_view=hex(view),**execution(console,refresh))
        results.append(result);return row,s
    if mode=='all':
        for index,n in enumerate(range(1,13),start):committed(index,n,'DOWN')
        for index,n in enumerate(range(11,-1,-1),start+12):committed(index,n,'UP')
        previous,old=state(start+23);repeat,new=state(start+24)
        if repeat['action']!='ENTER' or new['command_state']!=2 or new['selected']!=0 or old['native_refresh']['done']!=new['native_refresh']['done'] or repeat['CP_messages']!=previous['CP_messages']:
            raise ValueError('重复已提交的选择没有保持无额外事务语义')
        selection_file(new,0)
        if any(a['serial']>=b['serial'] for a,b in zip(results,results[1:])):raise ValueError('新切换没有产生独立原生E4序号')
    else:
        for index,n in enumerate(range(1,7),start):committed(index,n,'DOWN')
        failed,s=state(start+6)
        if failed['action']!='DOWN' or s['command_state']!=3 or s['selected']!=6:raise ValueError('错误回执没有显示失败并保持前一选择')
        selection_file(s,6);cp_at(failed,6)
        if s['native_refresh']['wait'] or not s['native_refresh']['done']:raise ValueError('回退原E4未完成')
        rollback_execution=execution(console,s['native_refresh'])
        faults=[json.loads(x) for x in (run/'fault-delivery.jsonl').read_text().splitlines()]
        if len(faults)!=1 or faults[0]['scenario']!='bad-select-ack' or faults[0]['selected']!=7 or crc_ok(bytes.fromhex(faults[0]['delivered']),28):raise ValueError('没有精确的第二次SELECT错误CRC注入')
        committed(start+7,6,'UP');committed(start+8,7,'DOWN')
    if json.loads((run/'exit.json').read_text())!={'method':'qmp-quit','exit_code':0}:raise ValueError('AP退出异常')
    cp_close=json.loads((run/'cp/close.json').read_text())
    if cp_close['exit_code'] or cp_close['method']!='semihosting-SYS_EXIT_EXTENDED':raise ValueError('CP退出异常')
    report=dict(status='PASS_MENU_ISOLATION' if isolated else 'PASS',mode=mode,source_DAT_sha256=DAT411_SHA,AP_sha256=record['AP_sha256'],CP_sha256=CP_SHA,
        verified_commits=results,all_twelve_forward=mode=='all',all_twelve_reverse_and_off=mode=='all',
        repeated_selection_without_extra_transaction=mode=='all',bad_post_E4_ack_rollback_and_retry=mode=='rollback',
        production_AP_completion_gate_preserved=True,menu_isolation=isolated,shooting_initialization_verified=not isolated,known_kernel_serial_records_removed=removed,camera_io=False,full_CP_RTOS_emulated=False,ISP_image_acceptance=False)
    report['AP_derived_not_packaged']=record['AP_sha256']==E4_AP_SHA
    if mode=='rollback':report['rollback_native_execution']=rollback_execution
    save(run/'e4-audit.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True,type=Path);p.add_argument('--manifest',required=True,type=Path)
    p.add_argument('--mode',choices=('all','rollback'),default='all');args=p.parse_args()
    report=check(args.run.absolute(),args.manifest.absolute(),args.mode)
    print(json.dumps({k:v for k,v in report.items() if k!='verified_commits'},ensure_ascii=False,indent=2))
