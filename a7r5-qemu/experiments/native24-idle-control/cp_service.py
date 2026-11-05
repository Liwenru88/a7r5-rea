"""有界、持久 ARM 接收侧车；回执仅来自真实 CP 指令执行。"""
import json
from pathlib import Path
import queue
import re
import struct
import socket
import subprocess
import tempfile
import threading
import environment as env
from native_vm import sandbox_profile
from runtime_manifest import verified_libraries


def build(output):
    output.mkdir(mode=0o700)
    layout=output/'receiver.ld';elf=output/'receiver.elf'
    layout.write_text('ENTRY(_start)\nSECTIONS { . = 0x03030000; .text : { *(.vectors) *(.startup) *(.text*) } .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) } /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) } }\n')
    source=output/'cp-receiver.c';source.write_bytes(Path(__file__).with_name('cp-receiver.c').read_bytes())
    startup=output/'cp-native-start.S';startup.write_bytes((env.LAB/'source/guest/cp-native-start.S').read_bytes())
    cmd=['/opt/homebrew/opt/llvm/bin/clang','--target=armv7a-none-eabi','-mcpu=cortex-a15','-mthumb','-mfloat-abi=soft',
         '-nostdlib','-ffreestanding','-fno-builtin','-fno-stack-protector','-O2',
         '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld','-Wl,-T,'+str(layout),'-Wl,--build-id=none',str(startup),str(source),'-o',str(elf)]
    result=subprocess.run(cmd,capture_output=True,text=True);(output/'compiler.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('ARM侧车编译失败')
    env.save(output/'build.json',dict(command=cmd,source=env.fact(source),startup=env.fact(startup),elf=env.fact(elf)))
    return elf


class CPService:
    def __init__(self,inputs,cp,elf,output):
        self.out=output;output.mkdir(mode=0o700);self.lines=queue.Queue();self.messages=[]
        self.control=Path(tempfile.mkdtemp(prefix='a7r5-n12cp-',dir='/private/tmp'))
        profile=output/'cp.sb'
        profile.write_text(sandbox_profile(inputs['binary'],cp,elf,elf,output,self.control,libraries=verified_libraries()))
        cmd=['/usr/bin/sandbox-exec','-f',str(profile),str(inputs['binary']),'-accel','tcg','-nodefaults','-display','none','-monitor','none','-serial','none','-nic','none','-no-reboot',
             '-machine','versatilepb,audiodev=silent','-cpu','cortex-a15,has_el2=off','-m','128M','-audiodev','none,id=silent',
             '-semihosting-config','enable=on,target=native',
             '-d','int,guest_errors','-D',str(output/'trace.log'),
             '-qmp',f'unix:{self.control}/qmp.sock,server=on,wait=off',
             '-device',f'loader,file={cp},addr=0x108000,force-raw=on','-device',f'loader,file={elf},cpu-num=0']
        env.save(output/'command.json',cmd)
        self.process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            env={'PATH':'/usr/bin:/bin','HOME':str(self.control),'TMPDIR':str(self.control),'LC_ALL':'C'},start_new_session=True)
        def receive():
            with (output/'console.log').open('wb') as log:
                for line in iter(self.process.stdout.readline,b''):
                    log.write(line);log.flush();self.lines.put(line)
        self.reader=threading.Thread(target=receive,daemon=True);self.reader.start()
        if self.lines.get(timeout=15)!=b'N12_CP_READY\n':raise RuntimeError('CP侧车未就绪')

    def consume(self,packet):
        if not 0<len(packet)<=4096:raise ValueError('CP请求越界')
        self.process.stdin.write(struct.pack('<I',len(packet))+packet);self.process.stdin.flush()
        line=self.lines.get(timeout=10)
        m=re.fullmatch(rb'N12_CP_REPLY ([0-9a-f]{8}) ([0-9a-f]{8}) ([0-9a-f]{8}) (?:(?P<active>[0-9a-f]{8}) (?P<selected>[0-9a-f]{8}) (?P<control>[0-9a-f]{8}) )?(?P<ack>[0-9a-f]*)\n',line)
        if not m:raise RuntimeError('CP执行失败：'+repr(line))
        consumed,heap,count=(int(x,16) for x in m.groups()[:3]);ack=bytes.fromhex(m['ack'].decode())
        row=dict(request=packet.hex(),reply=ack.hex(),consumed=consumed,heap_bytes=heap,heap_allocations=count)
        if m['active'] is not None:row.update(CP_active_view=int(m['active'],16),CP_selected=int(m['selected'],16),CP_control_selected=int(m['control'],16))
        self.messages.append(row);(self.out/'messages.json').write_text(json.dumps(self.messages,indent=2)+'\n')
        return ack

    def close(self):
        method='semihosting-SYS_EXIT_EXTENDED'
        if self.process.poll() is None:
            self.process.stdin.write(bytes(4));self.process.stdin.flush()
        try:code=self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            method='qmp-quit-after-failure'
            with socket.socket(socket.AF_UNIX) as s:
                s.settimeout(5);s.connect(str(self.control/'qmp.sock'))
                with s.makefile('rwb') as f:
                    f.readline()
                    for name in ('qmp_capabilities','quit'):
                        f.write(json.dumps({'execute':name}).encode()+b'\n');f.flush()
                        while 'return' not in json.loads(f.readline()):pass
            code=self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        env.save(self.out/'close.json',dict(exit_code=code,method=method,camera_io=False))
        if code:raise RuntimeError('CP侧车退出失败')
