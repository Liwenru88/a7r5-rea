"""离线构建固定会话自启候选；无网络、USB或相机执行。"""
from pathlib import Path
import hashlib,json,re,shutil,subprocess,uuid
HERE=Path(__file__).resolve().parent
WORK=next(p for p in HERE.parents if (p/'a7r5-qemu/runtime/manifest.json').is_file())
OLD=WORK/'a7r5-ssh/ssh-service/ram-key-fix/packages/ram-key-install-20261021-01'
CLANG='/opt/homebrew/opt/llvm/bin/clang'
LLD='/opt/homebrew/opt/lld/bin/ld.lld'
RUN='5e551f1a97774fa1885f15799583d09b'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def call(args):
 p=subprocess.run(args,capture_output=True,text=True,timeout=60)
 if p.returncode:raise RuntimeError(p.stderr)
 return p.stdout

def main():
 materials=HERE/'materials';materials.mkdir(exist_ok=True)
 src=HERE/'source-snapshot/engine'
 if not src.exists():shutil.copytree(OLD/'rebuild-sources',src)
 cfgpath=HERE/'operation.json'
 if cfgpath.exists():op=json.loads(cfgpath.read_text())
 else:
  aid=uuid.uuid4().hex
  op=dict(schema='a7r5-ssh-autostart-v1',auto_id=aid,service_run=RUN,target_ip='10.10.10.177',port=2222,
   auto_dir='/etc/a7r5-autostart-'+aid,stage_dir='/tmp_network/a7r5-auto-stage-'+aid,ram_root='/tmp_network/a7r5-ssh-'+RUN,
   private_source='/var/run/a7r5-ssh-'+RUN,active_namespace='mnt:[4026533196]',
   claimed_namespace_source='previous_verified_ready_receipt',
   real_boot_verified=False,live_approved=False,current_service_must_remain=True)
  cfgpath.write_text(json.dumps(op,ensure_ascii=False,indent=2)+'\n')
 aid=op['auto_id'];auto=op['auto_dir'];result=OLD/'result/session'
 helperconfig=(materials/'config.h' if (materials/'config.h').exists() else OLD/'materials/config.h').read_text()
 helperconfig=re.sub(r'^#define INSTALL_DIR .*$', '#define INSTALL_DIR '+json.dumps(auto),helperconfig,flags=re.M)
 (materials/'config.h').write_text(helperconfig)
 public=(materials/'trusted-host-public-key' if (materials/'trusted-host-public-key').exists() else result/'host-public-key').read_bytes()
 ready=(materials/'expected-ready.bin' if (materials/'expected-ready.bin').exists() else result/'ready.bin').read_bytes()
 if hashlib.sha256(public).hexdigest()!='1d37ff3ca1da5e372673315c5848e6f2a180de2df9390bbea5437211e46b5328':raise ValueError('可信公钥改变')
 (materials/'trusted-host-public-key').write_bytes(public)
 (materials/'expected-ready.bin').write_bytes(ready)
 values=dict(AUTO_ID=aid,AUTO_NAME='a7r5-autostart-'+aid,AUTO_DIR=auto,ETC_ROOT='/etc',PRELOAD_LINE=auto+'/boot.so\n',
  PRELOAD_NEW='.a7r5-preload-new-'+aid,PRELOAD_RESTORE='.a7r5-preload-restore-'+aid,
  STAGE_DIR=op['stage_dir'],PRIVATE_SOURCE=op['private_source'],RAM_ROOT=op['ram_root'],RAM_PARENT='/tmp_network',
  CLAIM_NAME='a7r5-autostart-'+aid+'.claim',ACTIVE_NS=op['active_namespace'],PROC_NS='/proc/self/ns/mnt',SELF_EXE='/proc/self/exe',
  BOOT_TRIGGER='/usr/bin/bootin.elf',PROC_CMDLINE='/proc/self/cmdline',PROC_EXE='/proc/self/exe',
  PUBLIC_SHA=hashlib.sha256(public).hexdigest(),READY_SHA=hashlib.sha256(ready).hexdigest())
 libc=WORK/'a7r5-ssh/vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
 if sha(libc)!='f9104526eb7e5d2ea533c1a209bb0b83e69367f569e4c966895c8e106e6382c9':raise ValueError('libc改变')
 common=[CLANG,'--target=aarch64-linux-gnu','--ld-path='+LLD,'-nostdlib','-ffreestanding','-fno-builtin','-fno-stack-protector','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wl,--no-undefined','-Wl,-z,max-page-size=65536','-I',str(materials),'-I',str(src/'src')]
 commands=[]
 def compile(name,args):
  command=common+args+['-o',str(materials/name)];call(command);commands.append(command)
 compile('ssh-service.arm64',['-fPIE','-pie','-Wl,-e,_start','-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1',str(src/'src/start.S'),str(src/'ssh-service/launcher.c'),str(libc)])
 values['HELPER_SHA']=sha(materials/'ssh-service.arm64')
 def config():
  (materials/'auto_config.h').write_text(''.join('#define '+k+' '+json.dumps(v)+'\n' for k,v in values.items()))
 config()
 compile('boot.so',['-fPIC','-shared','-fvisibility=hidden',str(HERE/'src/boot_hook.c'),str(libc)])
 values['HOOK_SHA']=sha(materials/'boot.so');config()
 compile('control.static',['-static','-Wl,-e,_start',str(src/'src/start.S'),str(HERE/'src/linux_crt.c'),str(HERE/'src/control.c')])
 (materials/'preload-enabled.bin').write_bytes(values['PRELOAD_LINE'].encode())
 (materials/'preload-neutral.bin').write_bytes(b'\n'*512)
 op['payloads']={n:dict(bytes=(materials/n).stat().st_size,sha256=sha(materials/n)) for n in ('boot.so','ssh-service.arm64','control.static')}
 op['public_sha256']=values['PUBLIC_SHA'];op['ready_sha256']=values['READY_SHA']
 cfgpath.write_text(json.dumps(op,ensure_ascii=False,indent=2)+'\n')
 verification=HERE/'verification';verification.mkdir(exist_ok=True)
 (verification/'build.json').write_text(json.dumps(dict(commands=commands,artifacts=op['payloads'],camera_io=False),indent=2)+'\n')
 print(json.dumps(op['payloads'],indent=2))
if __name__=='__main__':main()
