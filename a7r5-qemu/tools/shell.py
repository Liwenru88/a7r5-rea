"""原生模拟器内的 root 终端；不连接物理设备、不启动菜单应用。"""
import argparse
import hashlib
import json
import re
from native_vm import NativeVM


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--command',help='仅在本次客体 RAM 中执行；完成后正常退出 QEMU')
    args=parser.parse_args()
    vm=NativeVM('shell',capid=True,boot_services=True)
    result={'status':'failed','backend':'native','menu_started':False}
    error=None
    try:
        vm.start()
        identity=vm.command('cat /proc/self/status && uname -a && test -x /usr/bin/bootin.elf')
        clean=identity.replace(b'\r',b'')
        credentials={}
        for field in ('Uid','Gid'):
            match=re.search(rb'^'+field.encode()+rb':\s*(\d+)[ \t]+(\d+)[ \t]+(\d+)[ \t]+(\d+)[ \t]*$',clean,re.M)
            if not match or any(int(value) for value in match.groups()):
                raise ValueError('客体 UID/GID 不是完整的 root 身份，停止终端')
            credentials[field]=[int(value) for value in match.groups()]
        result['credentials']=credentials
        print(identity.decode(errors='replace'),flush=True)
        if args.command is not None:
            print(vm.command(args.command).decode(errors='replace'),flush=True)
        else:
            print('仅操作模拟器 RAM；输入 exit 或按 Ctrl-D 正常退出。')
            while True:
                try:code=input('a7r5-qemu# ')
                except (EOFError,KeyboardInterrupt):break
                if code.strip() in ('exit','quit'):break
                if not code.strip():continue
                try:print(vm.command(code).decode(errors='replace'),flush=True)
                except RuntimeError as exc:
                    if str(exc).startswith('guest 命令失败，返回码 '):print(str(exc))
                    else:raise
        result['status']='root-shell-verified'
    except BaseException as exc:
        result['error']=str(exc);error=exc
    finally:
        result['cleanup']=vm.close()
        result['console_sha256']=hashlib.sha256(vm.console.read_bytes()).hexdigest()
        (vm.out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'run':str(vm.out),**result},ensure_ascii=False),flush=True)
    if error:raise error
    if result['cleanup']!={'method':'qmp-quit','exit_code':0}:raise RuntimeError('未正常退出 QEMU')


if __name__=='__main__':main()
