"""原厂界面处理完成与下一帧之间的屏障；不追加或重发输入。"""
import re
import time
from control_actions import ACTION_SPECS
from menu_live import SINGLE_STATUS,TAP_STATUS,FirmwareMonitor,clean_console

# 来自名称表和正反向映射，使用归一化后的 UI ID。
UI_IDS=dict(UP=2,DOWN=6,LEFT=4,RIGHT=22,ENTER=20,MENU=19,C4=35,FN=141,
            PLAYBACK=34,DISP=2,C1=14,C2=223,C3=228,FRONT_DIAL=0x2f5,
            REAR_DIAL_L=0x2ea,REAR_DIAL_R=0x2ef,CONTROL_WHEEL=0x2f6,MODE_DIAL=0x2a,JOYSTICK=0xf1)


def completed_sequence(data,action):
    control=ACTION_SPECS[action][0]
    expected=[int(SINGLE_STATUS[action],0)] if action in SINGLE_STATUS else [int(TAP_STATUS.get(action,'1'),0),0]
    clean=clean_console(data).replace(b'\r',b'')
    rows=[(int(status,0),int(sequence)) for key,status,sequence in re.findall(
        rb'^(?:/ # )?OBS A7R5_INPUT_COMPLETED key=(0x[0-9a-f]+|0) status=(0x[0-9a-f]+|0) frame_sequence=([0-9]+) result=[0-9]+$',clean,re.M)
        if int(key,0)==UI_IDS[control]]
    if [s for s,_ in rows]!=expected or any(seq<=0 for _,seq in rows):
        raise RuntimeError('缺少精确的界面处理完成回执：'+action)
    return max(seq for _,seq in rows)


def wait_input_completion(vm,action,offset,timeout=5):
    monitor=FirmwareMonitor(vm.console)
    deadline=time.monotonic()+timeout
    while True:
        monitor.check()
        try:return completed_sequence(vm.console.read_bytes()[offset:],action)
        except RuntimeError:
            if time.monotonic()>=deadline:raise
        if vm.process.poll() is not None:raise RuntimeError('等待界面处理完成时虚拟器退出')
        time.sleep(.005)
