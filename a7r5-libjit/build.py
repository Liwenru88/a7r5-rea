"""仅构建本机一次性包，不观察设备；旧 kit 和旧会话保持不变。"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from references import REFERENCE, loader_path

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
CLANG='/opt/homebrew/opt/llvm/bin/clang'
LLD='/opt/homebrew/opt/lld/bin/ld.lld'
OLD=WORK/'a7r5-ssh/ssh-service/manual-restart/packages/restart-20261021-01'
EVIDENCE=REFERENCE/'evidence'

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def save(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')

def header(run,script,seconds,root='/tmp/jiritsu'):
    if not 1<=seconds<=60:raise ValueError('首验包仅支持1至60秒')
    prefix=root+'/a7r5-jit-'+run
    values=dict(RUN_ID=run,TASK_SCRIPT=script,LIBJIT_PATH=root+'/libJit.so',
                TICKET_PATH=prefix+'.ticket',TICKET_BYTES='A7R5_LIBJIT '+run+'\n',
                CLAIM_PATH=prefix+'.claim',STATE_PATH=prefix+'.state',STATE_NEW=prefix+'.state.new',OUTPUT_PATH=prefix+'.output')
    return ''.join('#define '+k+' '+json.dumps(v,ensure_ascii=True)+'\n' for k,v in values.items())+f'#define TASK_SECONDS {seconds}L\n#define OUTPUT_LIMIT 32768L\n'

def compile_payload(directory,run,script,seconds,root='/tmp/jiritsu'):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    (directory/'jit_config.h').write_text(header(run,script,seconds,root))
    command=[CLANG,'--target=aarch64-linux-gnu','--ld-path='+LLD,'-nostdlib','-ffreestanding',
             '-fno-builtin','-fno-stack-protector','-fPIC','-shared','-fvisibility=hidden','-O2',
             '-Wall','-Wextra','-Werror','-Wl,--no-undefined','-Wl,-z,max-page-size=65536','-Wl,-init,_init',
             '-I',str(directory),str(HERE/'src/runner.c'),'-o',str(directory/'libJit.so')]
    got=subprocess.run(command,capture_output=True,text=True,timeout=30)
    save(directory/'build.json',dict(argv=command,returncode=got.returncode,stdout=got.stdout,stderr=got.stderr))
    if got.returncode:raise ValueError(got.stderr)
    from elftools.elf.elffile import ELFFile
    with (directory/'libJit.so').open('rb') as f:
        elf=ELFFile(f);tags=list(elf.get_section_by_name('.dynamic').iter_tags())
        undefined=[s.name for s in elf.get_section_by_name('.dynsym').iter_symbols() if s.name and s['st_shndx']=='SHN_UNDEF']
        needed=[t.needed for t in tags if t.entry.d_tag=='DT_NEEDED']
        init=[t.entry.d_val for t in tags if t.entry.d_tag=='DT_INIT']
        if elf['e_machine']!='EM_AARCH64' or elf['e_type']!='ET_DYN' or needed or undefined or len(init)!=1:
            raise ValueError('载荷格式、初始化入口或无依赖门槛失败')
    proof=dict(sha256=sha(directory/'libJit.so'),bytes=(directory/'libJit.so').stat().st_size,
               needed=needed,undefined=undefined,dt_init=init[0],camera_execution_verified=False)
    save(directory/'elf-check.json',proof);return proof

def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--candidate',type=Path)
    p.add_argument('--proof',type=Path,help='本次独立验证目录，内含tests/host-final和guest-01记录')
    args=p.parse_args()
    dest=args.output.absolute();dest.mkdir(parents=True,exist_ok=False)
    if any(p.is_symlink() for p in (dest,*dest.parents)):raise ValueError('封包目录不能经过链接')
    static=json.loads((EVIDENCE/'static-verdict.json').read_text())
    if not static['same_loader_branch_confirmed']:raise ValueError('静态加载入口尚未确认')
    run=uuid.uuid4().hex
    if args.candidate:
        if sha(args.candidate/'src/runner.c')!=sha(HERE/'src/runner.c'):raise ValueError('候选源码变化，必须重新验证')
        run=json.loads((args.candidate/'config.json').read_text())['run_id']
    script='set -eu\necho A7R5_LIBJIT_INFO_BEGIN\n/bin/cat /proc/self/status\n/bin/cat /version.txt\n/bin/cat /proc/version\n/bin/cat /proc/mounts\necho A7R5_LIBJIT_INFO_END\n'
    (dest/'src').mkdir()
    shutil.copyfile(HERE/'src/runner.c',dest/'src/runner.c')
    for name in ('runner.py','operation.py','transport.py','host_state.py','references.py'):
        shutil.copyfile(HERE/name,dest/name)
    shutil.copyfile(HERE/'rebuild_check.py',dest/'rebuild_check.py')
    shutil.copyfile(HERE/'run_offline_tests.py',dest/'run_offline_tests.py')
    # 恢复旧会话的测试留在源码工程，不混入新一次性执行包。
    shutil.copytree(HERE/'tests',dest/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc','test_stream_recovery.py'))
    (dest/'test-fixtures').mkdir()
    shutil.copyfile(loader_path(),dest/'test-fixtures/libJiritsu.so')
    (dest/'requirements-test.txt').write_text('pytest==9.1.1\n')
    engine=dest/'vendor/engine'
    for sub in ('mac/system_dump','libs','sources/workspaces/j/work/sony-pmca-re'):
        source=OLD/'vendor/engine'/sub
        shutil.copytree(source,engine/sub,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
    adapter=engine/'mac/system_dump/usb_adapter.py'
    text=adapter.read_text()
    if 'range(1, 2)' not in text or 'attempt == 1' not in text:raise ValueError('未使用已经核对的单次接管门槛')
    shutil.copytree(WORK/'a7r5-implementation-kit/licenses',dest/'licenses')
    # 不将历史格式化、DEBUG 部署器或账户凭据带入新包。
    deps=json.loads((OLD/'operation.json').read_text())
    config=json.loads((OLD/'config.json').read_text())
    config={k:config[k] for k in ('interfaces','version_sha256')}
    config.update(run_id=run,task_seconds=15,output_limit=32768,host_baseline=deps['host_baseline'],
                  loader_sha256=static['library_sha256'],loader_bytes=static['library_bytes'],
                  preload_baselines=[('blank-512',('\n'*512).encode().hex()),
                    ('installed-boot-hook',b'/etc/a7r5-autostart-8e94bdaf0bd44e5c82c801ad74a34929/boot.so\n'.hex())],
                  expected_output_begin='A7R5_LIBJIT_INFO_BEGIN\n',expected_output_end='A7R5_LIBJIT_INFO_END\n',
                  maximum_writes=2,maximum_trigger_attempts=1,debug=0,preload_writes=0,stop_maximum=1,
                  work_read_error_means='stat_failed_not_absence_proof',camera_execution_verified=False)
    save(dest/'config.json',config)
    (dest/'task.sh').write_text(script)
    payload=compile_payload(dest/'materials',run,script,15)
    if args.candidate and payload['sha256']!=sha(args.candidate/'materials/libJit.so'):raise ValueError('最终库不等于已验证候选')
    (dest/'materials/ticket.bin').write_text('A7R5_LIBJIT '+run+'\n')
    (dest/'evidence').mkdir()
    for name in ('static-verdict.json','set-file2.txt','get-file2.txt','static-analysis.md'):
        shutil.copyfile(EVIDENCE/name,dest/'evidence'/name)
    verification=dest/'verification';verification.mkdir()
    proofroot=args.proof.absolute() if args.proof else REFERENCE/'verification'
    guestroot=proofroot/'guest-01' if args.proof else proofroot
    proof_files=[(proofroot/'tests/host-final.log','host-tests.log'),
                 (proofroot/'tests/host-final.xml','host-tests.xml'),
                 (guestroot/'result.json','aarch64-guest.json'),
                 (proofroot/'guest-run-01.log','aarch64-guest.log')] if args.proof else [
                 (proofroot/name,name) for name in ('host-tests.log','host-tests.xml','aarch64-guest.json','aarch64-guest.log')]
    for source,name in proof_files:
        shutil.copyfile(source,verification/name)
    for file in guestroot.glob('*.txt'):shutil.copyfile(file,verification/file.name)
    if args.proof:
        # 红灯、修复后分块记录和已完成主机恢复的证据是历史背景，单独标记。
        history=verification/'history';history.mkdir()
        for source in [REFERENCE/'verification/history/chunk-before.log',REFERENCE/'verification/history/chunk-after.log',
                       HERE/'recovery/packages/libjit-recovery-20261021-01/result/result.json',
                       HERE/'recovery/packages/libjit-recovery-20261021-01/result/screen-confirmation.json']:
            shutil.copyfile(source,history/source.name)
    save(verification/'source-lineage.json',dict(kit_task_supervisor_source='a7r5-implementation-kit/payload/root_once.c',
        kit_task_supervisor_sha256=sha(WORK/'a7r5-implementation-kit/payload/root_once.c'),
        usb_engine_source=str(OLD.relative_to(WORK)),engine_files={str(p.relative_to(engine)):sha(p) for p in engine.rglob('*.py')},
        bootstrap_source='new raw Linux syscalls; no libc dependency',reference_commit=static['reference_commit'],
        camera_io=False,original_images_modified=False,
        inherited_verification_is_historical=not bool(args.proof),
        reference_package=str(REFERENCE.relative_to(WORK))))
    shutil.copyfile(HERE/'实施与恢复.md',dest/'实施与恢复.md')
    # 仅用本机 Python；实际执行必须另行显式批准。
    import shlex
    command='#!/bin/zsh\nset -eu\ncd -- "${0:A:h}"\nexec sudo '+shlex.quote(str(Path(sys.executable).resolve()))+' -B runner.py execute --device-io\n'
    (dest/'run-libjit-once.command').write_text(command);(dest/'run-libjit-once.command').chmod(0o700)
    operation=dict(schema='a7r5-libjit-once-1',directory=str(dest),run_id=run,risk=__import__('runner').RISK,
                   payload=payload,host_baseline=config['host_baseline'],
                   dependencies={str(p):sha(p) for p in (Path(sys.executable).resolve(),Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib').resolve())},files={})
    for path in sorted(dest.rglob('*')):
        if path.is_symlink():raise ValueError('包内禁止链接')
        if path.is_file():operation['files'][str(path.relative_to(dest))]=sha(path)
    save(dest/'operation.json',operation)
    save(dest/'approval-template.json',dict(accepted=False,operation_sha256=sha(dest/'operation.json'),risk=operation['risk']))
    (dest/'checksums.sha256').write_text(''.join(sha(path)+'  '+str(path.relative_to(dest))+'\n' for path in sorted(dest.rglob('*')) if path.is_file() and path.name!='checksums.sha256'))
    print(json.dumps(dict(package=str(dest),run_id=run,payload=payload,approved=False,device_io=False),ensure_ascii=False))

if __name__=='__main__':main()
