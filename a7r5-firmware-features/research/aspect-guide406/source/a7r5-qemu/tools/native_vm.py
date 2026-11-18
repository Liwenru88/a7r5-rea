"""macOS 原生 QEMU 后端；只读固件副本，强制本机沙箱，不挂物理设备。"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

from vm_session import VM, LAB, ANALYSIS, RUNS

NATIVE=LAB


def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def dtb_properties(raw):
    """只解析已有验收设备树，拒绝损坏或不支持的结构。"""
    header=struct.unpack_from('>10I',raw)
    magic,total,off,strings,_,version,_,_,strings_size,tree_size=header
    if magic!=0xd00dfeed or total!=len(raw) or version<17:raise ValueError('设备树头不符')
    names=raw[strings:strings+strings_size];end=off+tree_size;stack=[];result={}
    while off<end:
        token=struct.unpack_from('>I',raw,off)[0];off+=4
        if token==1:
            stop=raw.index(b'\0',off,end);stack.append(raw[off:stop].decode());off=(stop+4)&~3
        elif token==2:stack.pop()
        elif token==3:
            count,nameoff=struct.unpack_from('>II',raw,off);off+=8
            stop=names.index(b'\0',nameoff);name=names[nameoff:stop].decode()
            result[('/'.join(stack) or '/',name)]=raw[off:off+count];off=(off+count+3)&~3
        elif token==4:continue
        elif token==9:return result
        else:raise ValueError('设备树 token 不符')
    raise ValueError('设备树缺少结束标记')


def sandbox_profile(binary, kernel, initrd, dtb, output, control, libraries=(), allow_homebrew=True):
    """默认拒绝；仅允许系统动态库、固定输入及本次输出。"""
    def literal(path):return '(literal '+json.dumps(str(Path(path).resolve()),ensure_ascii=False)+')'
    def subpath(path):return '(subpath '+json.dumps(str(Path(path).resolve()),ensure_ascii=False)+')'
    qmp=str((control/'qmp.sock').resolve())
    return '\n'.join([
        '(version 1)','(deny default)','(import "dyld-support.sb")',
        '(allow process-exec '+literal(binary)+')',
        '(allow signal (target self))','(allow sysctl-read)',
        '(allow mach-lookup)','(allow file-read-metadata)',
        '(allow file-read* file-map-executable '+subpath('/System/Library')+' '+subpath('/System/Volumes/Preboot/Cryptexes/OS')+' '+subpath('/usr/lib')+' '+(subpath('/opt/homebrew') if allow_homebrew else '')+' '+literal(binary)+' '+' '.join(literal(p) for p in libraries)+')',
        '(allow file-read* '+ ' '.join(literal(p) for p in (kernel,initrd,dtb,Path('/dev/urandom'),Path('/dev/random')))+')',
        '(allow file-read* file-write* '+literal('/dev/null')+' '+subpath(output)+' '+subpath(control)+')',
        '(allow network-bind network-inbound (local unix-socket (path-literal '+json.dumps(qmp,ensure_ascii=False)+')))',
    ])+'\n'


class NativeVM(VM):
    def __init__(self,prefix,capid=False,boot_services=False):
        super().__init__('native-'+prefix,capid=capid,boot_services=boot_services)
        self.control=None
        self.native_paused=False
        self.console.touch(exist_ok=False)

    def connect_qmp(self,sock):
        sock.connect(str(self.control/'qmp.sock'))

    def runtime_inputs(self):
        """默认入口始终使用交付清单；研究子类须另行验证其候选。"""
        from runtime_manifest import verified_inputs
        return verified_inputs()

    def start(self):
        if sys.platform!='darwin':raise RuntimeError('原生后端仅支持 macOS')
        if not self.capid or not self.boot_services:raise ValueError('原生入口只支持已验收的完整菜单配置')
        import fcntl
        from app_paths import open_vm_lock
        self.lock=open_vm_lock()
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        from runtime_manifest import verified_inputs, verified_libraries
        inputs=self.runtime_inputs()
        libraries=verified_libraries()
        binary,kernel,initrd,source_dtb=(inputs[k] for k in ('binary','kernel','initrd','dtb'))
        self.native_reentry=True
        dtb=self.out/'virt.dtb';dtb.write_bytes(source_dtb.read_bytes())
        props=dtb_properties(dtb.read_bytes());chosen='/chosen'
        start=int.from_bytes(props[(chosen,'linux,initrd-start')],'big')
        end=int.from_bytes(props[(chosen,'linux,initrd-end')],'big')
        if start!=0x440000000 or end-start!=initrd.stat().st_size:raise ValueError('设备树与客体容量不符')
        cmdline=props[(chosen,'bootargs')].rstrip(b'\0').decode()
        for expected in ('memrsv=0x00010000@0x41d000000:uc','memrsv=0x00100000@0x41e000000:uc','rdinit=/init'):
            if expected not in cmdline.split():raise ValueError('设备树启动配置不符')
        if ' '.join(cmdline.split())!=cmdline:raise ValueError('启动参数格式不符')
        self.control=Path(tempfile.mkdtemp(prefix='a7r5-',dir='/private/tmp'))
        profile=self.out/'native.sb';profile.write_text(sandbox_profile(binary,kernel,initrd,dtb,self.out,self.control,
            libraries=libraries,allow_homebrew=not bool(libraries)))
        inputs={str(p):{'bytes':p.stat().st_size,'sha256':digest(p)} for p in (binary,kernel,initrd,dtb)}
        (self.out/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
        command=['/usr/bin/sandbox-exec','-f',str(profile),str(binary),
            '-machine','virt,secure=off','-cpu','cortex-a35','-accel','tcg','-smp','1','-m','24576',
            '-nodefaults','-display','none','-monitor','none','-serial','stdio','-nic','none','-no-reboot',
            '-qmp',f'unix:{self.control}/qmp.sock,server=on,wait=off',
            '-device',f'loader,file={dtb},addr=0x400002000',
            '-device',f'loader,file={kernel},addr=0x400080000,force-raw=on',
            '-device',f'loader,file={initrd},addr=0x440000000,force-raw=on',
            '-device','loader,addr=0x400080000,cpu-num=0',
            '-kernel',str(kernel),'-initrd',str(initrd),'-append',cmdline,
            '-d','cpu_reset,guest_errors,unimp','-D',str(self.out/'boot-trace.log')]
        (self.out/'native-command.json').write_text(json.dumps(command,indent=2)+'\n')
        env={'PATH':'/usr/bin:/bin','HOME':str(self.control),'TMPDIR':str(self.control),'LC_ALL':'C','QEMU_SONY_TIMERS':'1'}
        self.log=self.console.open('wb')
        self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=self.log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        (self.out/'native-owner.json').write_text(json.dumps({'pid':self.process.pid,'control':str(self.control),'backend':'macos-native'})+'\n')
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            data=self.console.read_bytes().replace(b'\r\n',b'\n')
            if b'Entering exception monitor.' in data or b'Kernel panic' in data:raise RuntimeError('原厂内核异常')
            if b'A7R5_QEMU_ROOT_READY\n' in data and b'/ #' in data:return
            if self.process.poll() is not None:raise RuntimeError(f'原生 QEMU 提前退出: {self.process.returncode}; {data[-1200:]!r}')
            if len(data)>16*1024*1024:raise RuntimeError('启动日志超限')
            bridge = getattr(self, 'live_bridge', None)
            if bridge and (bridge/'cancel').exists():raise RuntimeError('启动已取消')
            time.sleep(.2)
        raise TimeoutError('原生后端 150 秒内未进入原厂终端')

    def set_native_paused(self, paused):
        """通过本实例 QMP 冻结/继续虚拟时钟；失败时不回退到无控制运行。"""
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(5);self.connect_qmp(sock)
            with sock.makefile('rwb') as stream:
                if 'QMP' not in json.loads(stream.readline()):raise RuntimeError('原生 QMP 握手不符')
                state=None
                for name in ('qmp_capabilities','stop' if paused else 'cont','query-status'):
                    stream.write(json.dumps({'execute':name}).encode()+b'\n');stream.flush()
                    while True:
                        reply=json.loads(stream.readline())
                        if 'error' in reply:raise RuntimeError(str(reply['error']))
                        if 'return' in reply:
                            if name=='query-status':state=reply['return']
                            break
        if not state or state['running'] is not (not paused):raise RuntimeError('原生 QMP 暂停状态核对失败')
        self.native_paused=paused
        record={'paused_for_input':paused,'qmp_status':state,'host_monotonic':time.monotonic()}
        (self.out/'native-runtime-state.json').write_text(json.dumps(record,indent=2)+'\n')
        with (self.out/'native-qmp-events.jsonl').open('a') as log:log.write(json.dumps(record)+'\n')

    def command(self, code, timeout=90):
        from latency import stage, record
        timings = {}
        if getattr(self,'native_paused',False):
            with stage(timings, 'resume_ms'):
                self.set_native_paused(False)
        if getattr(self,'native_reentry',False) and 'LD_PRELOAD=/simulation/menu-observe-a7r5-baseline.so /usr/bin/bootin.elf' in code:
            code='export A7R5_NATIVE_MENU_REENTRY=1; '+code
        with stage(timings, 'serial_ms'):
            data=super().command(code,timeout=timeout)
        exporting = code == '/simulation/headless-osd-export' or bool(re.fullmatch(r'/simulation/headless-osd-export --after [0-9]+', code))
        if getattr(self,'native_reentry',False) and exporting:
            with stage(timings, 'pause_ms'):
                self.set_native_paused(True)
        record(self.out, dict(command_kind='export' if exporting else 'command', **timings))
        self.last_command_timings = timings
        if getattr(self,'native_reentry',False) and code.startswith('sleep 15; echo A7R5_LOADER_LOG_BEGIN;'):
            self.prime_native_menu()
        return data

    def last_native_screen(self):
        rows=re.findall(rb'^OBS A7R5_MANAGER_APPLY manager=[^\n]*? to=(0x[0-9a-f]+|0) ',
                        self.console.read_bytes().replace(b'\r',b''),re.M)
        return int(rows[-1],0) if rows else None

    def wait_native_screen(self, expected):
        from menu_live import FirmwareMonitor
        accepted=(expected,) if isinstance(expected,int) else tuple(expected)
        if not accepted or any(type(value) is not int for value in accepted):
            raise ValueError('期望页面必须是明确的整数编号')
        monitor=FirmwareMonitor(self.console)
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            monitor.check()
            if self.last_native_screen() in accepted:return
            if self.process.poll() is not None:raise RuntimeError('原生初始化时虚拟器退出')
            time.sleep(.1)
        raise RuntimeError('原生初始化页面不符，期望 '+','.join(hex(value) for value in accepted)+'，实际 '+str(self.last_native_screen()))

    def prime_native_menu(self):
        """仅在已知首次启动路径确认一次原厂提示；设置只在本次 RAM。"""
        if getattr(self,'native_primed',False):raise RuntimeError('拒绝重复执行原生首次初始化')
        from menu_live import key_command
        self.wait_native_screen(0x2d6)
        steps=[]
        # 未完成启动 -> 原厂菜单 -> 首次触控提示 -> 拍摄信息页 -> 菜单。
        for key,expected in (('MENU',0x355),('MENU',0x2d6),('MENU',0x1e9),('ENTER',0),('MENU',0x2d6)):
            before=self.last_native_screen()
            super().command(key_command(key)+' && sleep 1',timeout=30)
            self.wait_native_screen(expected)
            steps.append({'key':key,'before':before,'after':expected})
            (self.out/'native-initialization.json').write_text(json.dumps({'status':'in-progress','steps':steps},indent=2)+'\n')
        self.native_primed=True
        (self.out/'native-initialization.json').write_text(json.dumps({'status':'ready','steps':steps,
            'touch_guide_acknowledged_by_original_enter':True,'settings_persistence':'guest RAM only'},indent=2)+'\n')

    def close(self):
        result=super().close()
        # 只清理本实例的临时套接字；证据目录完整保留。
        if self.control and self.process is not None and self.process.poll() is not None:
            socket_path=self.control/'qmp.sock'
            if socket_path.exists():socket_path.unlink()
            if not list(self.control.iterdir()):self.control.rmdir()
        return result
