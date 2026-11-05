"""原EVF显示对象/输出命令及完成通知入口；尚未绑定照片成像根。"""
import struct

from .access_evidence import CP_SHA,require_source
from .cp_machine import CpMachine,WORK
from .investigate import CP_BASE,instructions


def collect(cp):
    require_source(cp,CP_SHA,'CP')
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
    def words(at,n):return struct.unpack_from('<'+'I'*n,cp,at-CP_BASE)
    bindings=[]
    for label,name_at,rtti,vtable,entries in (
        ('N3VDF20VfxmixExecutorDevEvfE',0xc93a60,0xc93a80,0xce2718,(0x6a3095,0x6ab7eb,0x6ab7c5)),
        ('N3VDF13DevEvfCmdOutvE',0xc93aa0,0xce2768,0xce272c,(0x698ff9,0x6ab83d,0x1f3401))):
        raw=label.encode()+b'\0'
        if (cp[name_at-CP_BASE:name_at-CP_BASE+len(raw)]!=raw or words(rtti+4,1)!=(name_at,) or
            words(vtable-8,2)!=(0,rtti) or words(vtable,len(entries))!=entries):
            raise ValueError('原EVF类型/虚表绑定不符')
        bindings.append(dict(type_name=label,rtti=hex(rtti),vtable=hex(vtable),entries=list(map(hex,entries))))
    m=CpMachine(cp)
    m.map_ram(0x16a8000,0x1000);m.map_ram(0x198b000,0x1000)
    initialized=m.run(0x6ab7ee)
    if (initialized['r0']!=0x16a8268 or m.word(0x16a8268)!=0xce2718 or
        m.word(0x16a8268+0x2c)!=0x1f62b1):raise ValueError('原EVF执行器初始化不符')
    command=WORK+0x1000
    m.run(0x6ab816,arguments=(command,))
    if m.word(command)!=0xce272c or m.word(command+4)!=0xb:
        raise ValueError('原EVF输出命令初始化不符')
    callback=m.run(0x1f62b0,arguments=(0x16a8268,0,0x1234),stop_before=(0x6a3070,))
    if (callback['status']!='STOPPED_BEFORE_BOUNDARY' or
        (m.register('r0'),m.register('r1'))!=(0x9059081a,0x1234)):
        raise ValueError('原EVF回调没有到达已锁定通知入口')
    # 到达通用通知服务之前结束；不伪造设备已显示或已释放一帧。
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    return dict(schema='a7r5-native-evf-display-entry/1',cp_sha256=CP_SHA,type_bindings=bindings,
        native_executor_initialization=True,executor_object='0x16a8268',
        native_output_command_initialization=True,command_identity='0xb',
        native_callback='0x1f62b0',notification_entry='0x6a3070',notification_endpoint='0x9059081a',
        callback_value=0x1234,stopped_before_notification_service=True,
        windows={hex(a):instructions(md,cp[a-CP_BASE:a-CP_BASE+n],a) for a,n in
                 ((0x6ab7ee,66),(0x6a297c,52),(0x1f62b0,42),(0x6a3070,36),(0x6a3cb4,150))},
        fixture_boundaries=['zeroed executor/command state','callback argument fixture','EVF diagnostic flag zero'],
        original_color_bank_to_evf_bound=False,photo_mode_context_identity_verified=False,
        displayed_frame_or_final_reference_verified=False,camera_io=False,firmware_modified=False)
