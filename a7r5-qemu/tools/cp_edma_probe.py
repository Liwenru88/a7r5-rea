"""独立客体校验 DMA 字节搬运和 IRQ403；不加载或替代原厂 CP。"""
import argparse
import fcntl
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import time

from app_paths import open_vm_lock
from cp_native_probe import qmp_command, research_binary
from native_vm import NativeVM, sandbox_profile
from runtime_manifest import LAB, digest, verified_inputs, verified_libraries


def run(candidate):
    binary, receipt = research_binary(candidate)
    verified_inputs()
    out = Path(tempfile.mkdtemp(prefix='cp-edma-', dir=LAB/'build'))
    layout = out/'probe.ld'
    layout.write_text('ENTRY(_start)\nSECTIONS { . = 0; .vectors : { *(.vectors) } . = 0x10000; .text : { *(.startup) *(.text*) } .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) } /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) } }\n')
    sources = [LAB/'source/guest'/n for n in ('cp-edma-start.S','cp-edma-contract.c')]
    elf = out/'probe.elf'
    compile_command = ['/opt/homebrew/opt/llvm/bin/clang', '--target=armv7a-none-eabi',
        '-mcpu=cortex-a35', '-mthumb', '-mfloat-abi=soft', '-nostdlib', '-ffreestanding',
        '-fno-builtin', '-fno-stack-protector', '-O2',
        '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld', '-Wl,-T,'+str(layout),
        '-Wl,--build-id=none', *(str(p) for p in sources), '-o', str(elf)]
    compiled = subprocess.run(compile_command, capture_output=True, text=True, timeout=30)
    (out/'compiler.log').write_text(compiled.stdout+compiled.stderr)
    if compiled.returncode:
        raise RuntimeError('DMA 客体验收程序构建失败')
    (out/'receipt.json').write_text(json.dumps({'command':compile_command,
        'sources':{str(p.relative_to(LAB)):digest(p) for p in sources},
        'ELF_sha256':digest(elf), 'CP_loaded':False},indent=2)+'\n')
    vm = NativeVM('cp-edma-contract')
    print('CP_EDMA_RUN',vm.out,flush=True)
    result = {'status':'failed','CP_loaded':False,'AP_connected':False,'CP_generated_0x2040':False,
              'ISP_pixels_verified':False,'research_binary_sha256':receipt['binary_sha256'],
              'probe':str(out)}
    try:
        vm.lock = open_vm_lock()
        fcntl.flock(vm.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        vm.control = Path(tempfile.mkdtemp(prefix='a7r5-edma-',dir='/private/tmp'))
        profile=vm.out/'native.sb'
        profile.write_text(sandbox_profile(binary,elf,layout,elf,vm.out,vm.control,
                                           libraries=verified_libraries()))
        command=['/usr/bin/sandbox-exec','-f',str(profile),str(binary),'-machine','a7r5-cp-boot',
            '-accel','tcg','-smp','4','-m','128M','-nodefaults','-display','none',
            '-monitor','none','-serial','stdio','-nic','none','-no-reboot',
            '-qmp',f'unix:{vm.control}/qmp.sock,server=on,wait=off',
            '-d','guest_errors','-D',str(vm.out/'mmio.log'),
            '-device',f'loader,file={elf},cpu-num=0','-S']
        (vm.out/'native-command.json').write_text(json.dumps(command,indent=2)+'\n')
        vm.log=vm.console.open('wb')
        vm.process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=vm.log,
            stderr=subprocess.STDOUT,env={'PATH':'/usr/bin:/bin','HOME':str(vm.control),
            'TMPDIR':str(vm.control),'LC_ALL':'C'},start_new_session=True)
        (vm.out/'native-owner.json').write_text(json.dumps({'pid':vm.process.pid,
            'control':str(vm.control),'backend':'macos-native-edma-contract'})+'\n')
        deadline=time.monotonic()+5
        while not (vm.control/'qmp.sock').exists():
            if vm.process.poll() is not None or time.monotonic()>deadline:
                raise RuntimeError('DMA 验收 QMP 未就绪')
            time.sleep(.01)
        qmp_command(vm,{'execute':'cont'})
        deadline=time.monotonic()+5
        while b'CP_EDMA_NATIVE_' not in vm.console.read_bytes():
            if vm.process.poll() is not None:
                raise RuntimeError('DMA 客体验收提前退出')
            if time.monotonic()>deadline:
                break
            time.sleep(.01)
        qmp_command(vm,{'execute':'stop'})
        raw=vm.out/'contract-result.bin'
        qmp_command(vm,{'execute':'pmemsave','arguments':{'val':0x3e00000,'size':28,'filename':str(raw)}})
        values=struct.unpack('<7I',raw.read_bytes())
        result['guest_result']=values
        if values!=(0xedaa0001,0xffffffff,16,17,1,2,5):
            raise ValueError('DMA 客体验收阶段或结果不符：'+str(values))
        if vm.console.read_bytes().splitlines()!=[b'CP_EDMA_NATIVE_OK']:
            raise ValueError('DMA 客体验收终态不完整')
        result.update(status='native_edma_contract_verified',copies=18,bytes=1088,
                      direct_copies=16,linked_list_copies=2,irq403_pending_checks=17,
                      no_new_cycle_no_completion=True,unconnected_AP_address_aborted=True)
        result.update(I2C_no_slave_NACK_and_IRQ_verified=5,
                      clock_reset_registers_control_I2C_MMIO=True)
    except Exception as error:
        result['error']=str(error)
        raise
    finally:
        result['exit']=vm.close()
        result['console_sha256']=digest(vm.console)
        (vm.out/'contract-result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp-qemu',required=True,type=Path)
    print(json.dumps(run(parser.parse_args().cp_qemu),indent=2))
