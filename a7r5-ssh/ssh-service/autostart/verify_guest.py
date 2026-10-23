"""断网QEMU：仅RAM夹具、自启钩子和静态禁用工具，不启动sshd。"""
from pathlib import Path
import hashlib,json,re,shlex,subprocess,sys
HERE=Path(__file__).resolve().parent;WORK=next(p for p in HERE.parents if (p/'a7r5-qemu/runtime/manifest.json').is_file())
sys.path.insert(0,str(WORK/'a7r5-qemu/tools'))
from native_vm import NativeVM
from build import CLANG,LLD,sha,call

def put(vm,path,raw):
 vm.command('umask 077; : > '+shlex.quote(path))
 for offset in range(0,len(raw),48):
  row=''.join('\\%03o'%b for b in raw[offset:offset+48]);vm.command('printf '+shlex.quote(row)+' >> '+shlex.quote(path))
 vm.command('/bin/busybox chmod 700 '+shlex.quote(path))
 out=vm.command('/bin/busybox md5sum '+path)
 if not re.search(rb'\n'+hashlib.md5(raw).hexdigest().encode()+rb'\s+'+path.encode()+rb'\r?\n',out):raise ValueError('客体传输校验失败')

def main():
 v=HERE/'verification/guest';v.mkdir(parents=True,exist_ok=True)
 op=json.loads((HERE/'operation.json').read_text());aid=op['auto_id'];base='/simulation/autostart-test';etc=base+'/etc';ram=base+'/ram';auto=etc+'/a7r5-autostart-'+aid
 config=v/'auto_config.h';libc=WORK/'a7r5-ssh/vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
 common=[CLANG,'--target=aarch64-linux-gnu','--ld-path='+LLD,'-nostdlib','-ffreestanding','-fno-builtin','-fno-stack-protector','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wl,--no-undefined','-Wl,-z,max-page-size=65536','-I',str(WORK/'a7r5-ssh/src'),'-I',str(v)]
 def build(name,source,static=False,shared=False):
  args=['-fPIC','-shared'] if shared else ['-Wl,-e,_start',str(WORK/'a7r5-ssh/src/start.S')]+(['-static',str(HERE/'src/linux_crt.c')] if static else ['-fPIE','-pie','-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1'])
  if shared:args+=['-fvisibility=hidden']
  call(common+args+[str(source)]+([] if static else [str(libc)])+['-o',str(v/name)])
 fixture=v/'helper.c';fixture.write_text('#include "ns_abi.h"\nint main(void){int fd=open("'+base+'/launched",O_WRONLY|O_CREAT|1024,0600);if(fd<0)return 61;return write(fd,"LAUNCHED1\\n",10)==10&&close(fd)==0?0:62;}\n')
 build('fixture-helper',fixture,static=True)
 trigger=v/'trigger.c';trigger.write_text('#include "ns_abi.h"\nint main(void){return write(1,"TRIGGER_RETURNED1\\n",18)==18?0:1;}\n')
 build('boot-trigger',trigger)
 result=dict(status='failed',camera_io=False,physical_devices=False,guest_nic='none',sshd_started=False,account_modified=False,real_boot_verified=False,
             production_controller_sha256=sha(HERE/'materials/control.static'),fixture_core_sources={n:sha(HERE/'src'/n) for n in ('control.c','linux_crt.c','boot_hook.c')})
 vm=NativeVM('autostart-ram-only',capid=True,boot_services=True);result['vm_evidence']=str(vm.out)
 try:
  vm.start();print('QEMU_ROOT_READY',flush=True)
  vm.command('mkdir '+base+'; mount -t tmpfs -o size=4m,mode=0755 tmpfs '+base+'; mkdir '+etc+' '+ram+' '+ram+'/stage '+ram+'/active '+ram+'/private; chmod 700 '+ram+'/stage '+ram+'/active '+ram+'/private; chmod 1777 '+ram)
  out=vm.command('/bin/busybox readlink /proc/self/ns/mnt');ns=re.findall(rb'\nmnt:\[[0-9]+\]\r?\n',out)[-1].strip().decode()
  values=dict(AUTO_ID=aid,AUTO_NAME='a7r5-autostart-'+aid,AUTO_DIR=auto,ETC_ROOT=etc,PRELOAD_LINE=auto+'/boot.so\n',PRELOAD_NEW='new',PRELOAD_RESTORE='restore',STAGE_DIR=ram+'/stage',PRIVATE_SOURCE=ram+'/private',RAM_ROOT=ram+'/active',RAM_PARENT=ram,CLAIM_NAME='claim',ACTIVE_NS=ns,PROC_NS='/proc/self/ns/mnt',SELF_EXE='/proc/self/exe',BOOT_TRIGGER=base+'/boot-trigger',PROC_CMDLINE='/proc/self/cmdline',PROC_EXE='/proc/self/exe',PUBLIC_SHA=hashlib.sha256(b'PUBLIC_TEST_ONLY\n').hexdigest(),READY_SHA=hashlib.sha256(b'READY_TEST_ONLY\n').hexdigest(),HELPER_SHA=sha(v/'fixture-helper'))
  def writeconfig():config.write_text(''.join('#define '+k+' '+json.dumps(x)+'\n' for k,x in values.items()))
  writeconfig();build('boot.so',HERE/'src/boot_hook.c',shared=True);values['HOOK_SHA']=sha(v/'boot.so');writeconfig();build('control.static',HERE/'src/control.c',static=True)
  for name,target in [('fixture-helper',ram+'/stage/ssh-service.arm64'),('boot.so',ram+'/stage/boot.so'),('control.static',base+'/control.static'),('boot-trigger',base+'/boot-trigger')]:
   put(vm,target,(v/name).read_bytes());print('QEMU_TRANSFERRED '+name,flush=True)
  vm.command("printf 'PUBLIC_TEST_ONLY\\n' > "+ram+"/active/host-public-key; printf 'READY_TEST_ONLY\\n' > "+ram+"/active/ready; dd if=/dev/zero of="+ram+"/private/host_ecdsa bs=505 count=1; chmod 600 "+ram+"/private/host_ecdsa")
  put(vm,etc+'/ld.so.preload',b'\n'*512)
  # 精确生产ELF在未设置的生产指针上必须拒绝inspect，不允许执行enable。
  put(vm,base+'/production-control.static',(HERE/'materials/control.static').read_bytes())
  proof=vm.command(base+'/production-control.static inspect; production_rc=$?; printf "PRODUCTION_REFUSAL:%s\\n" "$production_rc"; test "$production_rc" -eq 3')
  (v/'production-inspect.txt').write_bytes(proof);result['production_static_elf_executed_and_refused_unknown']=True
  proof=vm.command(base+'/control.static enable');(v/'enable.txt').write_bytes(proof)
  if ('\nA7R5_AUTO_ENABLED1 '+aid+' ').encode() not in proof.replace(b'\r',b''):raise ValueError('缺少启用回执')
  vm.command('LD_PRELOAD='+auto+'/boot.so '+base+'/boot-trigger; sleep 1; test ! -e '+base+'/launched')
  result['current_boot_duplicate_suppressed']=True
  # 只删除本夹具的RAM凭证以模拟RAM重置，并非相机或VM重启。
  vm.command('rm '+ram+'/claim/current-boot-suppressed; rmdir '+ram+'/claim; chmod 755 '+auto+'/enabled')
  vm.command('LD_PRELOAD='+auto+'/boot.so '+base+'/boot-trigger; sleep 1; test -f '+base+'/launched')
  proof=vm.command('cat '+base+'/launched; cat '+ram+'/claim/attempt');(v/'launched.txt').write_bytes(proof)
  if b'\nLAUNCHED1\n' not in proof.replace(b'\r',b''):raise ValueError('execveat没有启动固定测试ELF')
  result.update(fake_new_boot_launch_verified=True,marker_0755_accepted=True,static_helper_execveat_verified=True)
  vm.command('LD_PRELOAD='+auto+'/boot.so '+base+'/boot-trigger; sleep 1; test "$(/bin/busybox wc -c < '+base+'/launched)" -eq 10')
  result['repeated_trigger_no_second_launch']=True
  vm.command('rm '+ram+'/claim/attempt; rmdir '+ram+'/claim; printf broken > '+auto+'/ssh-service.arm64; LD_PRELOAD='+auto+'/boot.so '+base+'/boot-trigger; sleep 1; test "$(cat '+ram+'/claim/attempt)" = helper-refused; test "$(/bin/busybox wc -c < '+base+'/launched)" -eq 10')
  result['tampered_helper_refused_without_second_launch']=True
  proof=vm.command(base+'/control.static disable');(v/'disable.txt').write_bytes(proof)
  vm.command('rm '+ram+'/claim/attempt; rmdir '+ram+'/claim; LD_PRELOAD='+auto+'/boot.so '+base+'/boot-trigger; sleep 1; test ! -e '+ram+'/claim')
  result['disabled_marker_no_launch']=True
  put(vm,etc+'/ld.so.preload',(auto+'/boot.so\n').encode())
  proof=vm.command('printf broken > '+auto+'/boot.so; printf broken > '+auto+'/ssh-service.arm64; LD_PRELOAD=/does-not-exist '+base+'/control.static recover');(v/'recovery-with-broken-loader.txt').write_bytes(proof)
  if ('\nA7R5_AUTO_RECOVERED1 '+aid+' ').encode() not in proof.replace(b'\r',b''):raise ValueError('静态恢复未通过')
  vm.command('test "$(/bin/busybox wc -c < '+etc+'/ld.so.preload)" -eq 512')
  result.update(static_recover_without_dynamic_loader=True,fixture_preload_neutral=True,status='passed')
 except BaseException as exc:result['error']=type(exc).__name__+': '+str(exc)
 finally:
  result['cleanup']=vm.close()
  if result['cleanup']!={'method':'qmp-quit','exit_code':0}:result['status']='failed'
  (HERE/'verification/guest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
