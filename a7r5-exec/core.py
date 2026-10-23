"""只在本机准备和封存任务；不导入USB、不执行用户脚本。"""
from pathlib import Path
import hashlib
import json
import os
import shlex
import stat
import subprocess
import sys
import uuid

HERE=Path(__file__).resolve().parent
CLANG=Path('/opt/homebrew/opt/llvm/bin/clang').resolve()
LLD=Path('/opt/homebrew/opt/lld/bin/ld.lld').resolve()
LINKER_ALIAS=Path('/opt/homebrew/opt/lld/bin/ld.lld')
LIBUSB=Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib').resolve()


def safe(path):
    path=Path(path).absolute()
    if path.is_relative_to('/dev') or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('只接受无符号链接的普通本机路径')
    return path


def regular(path):
    path=safe(path)
    if not stat.S_ISREG(path.stat().st_mode):raise ValueError('不是普通文件')
    return path


def sha(path):
    return hashlib.sha256(regular(path).read_bytes()).hexdigest()


def save(path,value):
    with safe(path).open('x',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())


def resources():
    paths=[*HERE.glob('*.py'),*HERE.glob('*.sh')]
    for sub in ['runtime','payload','sdk','vendor']:
        paths += [p for p in (HERE/sub).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    return {str(p.relative_to(HERE)):sha(p) for p in sorted(paths)}


def check_tool():
    value=json.loads(regular(HERE/'TOOL.json').read_text())
    if value['schema']!='a7r5-exec-tool-1' or value['resources']!=resources():raise ValueError('工具材料变化，请重新离线验收，不复用批准')
    return value


def wrapper(script,run):
    begin='A7R5_EXEC_BEGIN_'+run+'\n';end='A7R5_EXEC_END_'+run+'\n'
    # 用户脚本只嵌入机内子shell，不能让其exit/exec跳过主包装器的退出码处理。
    text='printf '+shlex.quote(begin)+'\n/bin/sh -c '+shlex.quote(script)+' a7r5-exec-task\n'
    text+='task_rc=$?\n[ "$task_rc" -eq 0 ] || exit "$task_rc"\nprintf '+shlex.quote(end)+'\n'
    return text,begin,end


def compile_payload(out,engine,run,script,seconds):
    prefix='/tmp/jiritsu/a7r5-'+('jit-' if engine=='libjit' else '')+run
    config=dict(RUN_ID=run,TASK_SCRIPT=script,STATE_PATH=prefix+'.state',OUTPUT_PATH=prefix+'.output')
    if engine=='libjit':
        config.update(LIBJIT_PATH='/tmp/jiritsu/libJit.so',TICKET_PATH=prefix+'.ticket',
                      TICKET_BYTES='A7R5_LIBJIT '+run+'\n',CLAIM_PATH=prefix+'.claim',STATE_NEW=prefix+'.state.new')
        header='jit_config.h';source='libjit.c'
    else:
        config.update(ARM_BYTES=prefix+'.so\n',PRELOAD_PATH='/etc/ld.so.preload',GATE_PATH='/proc/self/cmdline')
        header='root_config.h';source='kit.c'
    text=''.join('#define '+k+' '+json.dumps(v,ensure_ascii=True)+'\n' for k,v in config.items())
    (out/header).write_text(text+f'#define TASK_SECONDS {seconds}U\n#define OUTPUT_LIMIT 32768U\n')
    # lld按argv[0]选择ELF驱动；摘要绑定真实文件，但调用名必须保留ld.lld。
    if LINKER_ALIAS.resolve()!=LLD:raise ValueError('链接器别名解析变化')
    command=[str(CLANG),'--target=aarch64-linux-gnu','--ld-path='+str(LINKER_ALIAS),'-nostdlib','-ffreestanding',
             '-fno-builtin','-fno-stack-protector','-fPIC','-shared','-fvisibility=hidden','-O2',
             '-Wall','-Wextra','-Werror','-Wl,--no-undefined','-Wl,-z,max-page-size=65536','-I',str(out),
             str(HERE/'payload'/source),'-o',str(out/'payload.so')]
    if engine=='libjit':command+=['-Wl,-init,_init']
    else:command+=[str(HERE/'sdk/libc-2.25.so')]
    result=subprocess.run(command,capture_output=True,text=True,timeout=45)
    save(out/'build.json',dict(argv=command,exit_code=result.returncode,stderr=result.stderr,stdout=result.stdout))
    if result.returncode:raise ValueError('载荷构建失败，保留build.json')
    from elftools.elf.elffile import ELFFile
    with (out/'payload.so').open('rb') as f:
        elf=ELFFile(f);tags=list(elf.get_section_by_name('.dynamic').iter_tags())
        needed=[t.needed for t in tags if t.entry.d_tag=='DT_NEEDED']
        undefined=[s.name for s in elf.get_section_by_name('.dynsym').iter_symbols() if s.name and s['st_shndx']=='SHN_UNDEF']
        if elf['e_machine']!='EM_AARCH64' or elf['e_type']!='ET_DYN':raise ValueError('载荷ABI错误')
        if engine=='libjit' and (needed or undefined or not any(t.entry.d_tag=='DT_INIT' for t in tags)):
            raise ValueError('libJit无依赖或入口门槛错误')
        if engine=='kit':
            with (HERE/'sdk/libc-2.25.so').open('rb') as library:
                exports={s.name for s in ELFFile(library).get_section_by_name('.dynsym').iter_symbols() if s['st_shndx']!='SHN_UNDEF'}
            if needed!=['libc.so.6'] or set(undefined)-exports or not any(t.entry.d_tag=='DT_INIT_ARRAY' for t in tags):
                raise ValueError('kit依赖、符号或入口错误')
    return dict(bytes=(out/'payload.so').stat().st_size,sha256=sha(out/'payload.so'),needed=needed,undefined=undefined)


def risk(engine):
    common='两阶段认证/START，以root执行本次封存脚本；任意脚本可能修改真实系统，超时和输出上限不构成沙箱。stat错误6不证明文件不存在，仍有路径覆盖、持久残留及恢复受限风险。完整成功终态、输出、预加载和重复状态全部通过才一次STOP；异常停止、不重试、不自动断电、不自动清理或恢复。'
    if engine=='libjit':return common+'libJit票据和固定库各上传一次，写入/tmp/jiritsu/libJit.so即触发；保留既有预加载，不DEBUG。'
    return common+'kit只接受精确512换行，上传随机路径库、临时写预加载并一次DEBUG；机内中和至512换行，不覆盖自启指针或未知内容。kit新工具适配仅离线验证。'


def prepare(engine,script,seconds=15):
    check_tool()
    if engine not in ('libjit','kit') or type(seconds) is not int or not 1<=seconds<=60:raise ValueError('方法或时限无效，范围1至60秒')
    raw=script.encode('utf-8')
    if not 1<=len(raw)<=8192 or b'\0' in raw or b'\r' in raw:raise ValueError('脚本须1至8192字节UTF-8，无NUL/CR')
    result=subprocess.run(['/bin/sh','-n'],input=raw,capture_output=True,timeout=10)
    if result.returncode:raise ValueError('shell语法错误：'+result.stderr.decode(errors='replace'))
    run=uuid.uuid4().hex
    directory=safe(HERE/'runs'/run);directory.mkdir(parents=True,mode=0o700,exist_ok=False)
    (directory/'task.sh').write_bytes(raw)
    task,begin,end=wrapper(script,run);(directory/'wrapped-task.sh').write_text(task)
    materials=directory/'materials';materials.mkdir()
    elf=compile_payload(materials,engine,run,task,seconds)
    if engine=='libjit':(materials/'ticket.bin').write_text('A7R5_LIBJIT '+run+'\n')
    profile=json.loads((HERE/'runtime/profile.json').read_text())
    config={k:profile[k] for k in ('interfaces','host_baseline','version_sha256','loader_sha256','loader_bytes','preload_baselines')}
    config.update(run_id=run,engine=engine,task_seconds=seconds,output_limit=32768,
                  expected_output_begin=begin,expected_output_end=end)
    save(directory/'config.json',config)
    if engine=='libjit':(materials/'libJit.so').write_bytes((materials/'payload.so').read_bytes())
    python=str(Path(sys.executable).resolve())
    command='#!/bin/zsh\nset -eu\nexec '
    if engine=='libjit':
        # 重复打开启动文件时重新准备，不能复用机内已消费的票据和claim。
        # 构建仍需虚拟环境中的elftools，启动名不能解析成环境外的Python。
        command+=shlex.quote(str(Path(sys.executable).absolute()))+' -B '+shlex.quote(str(HERE/'exec.py'))+' run --script '+shlex.quote(str(directory/'task.sh'))+' --timeout '+str(seconds)+'\n'
    else:
        command+='sudo '+shlex.quote(python)+' -B '+shlex.quote(str(HERE/'exec.py'))+' execute --run '+shlex.quote(str(directory))+' --device-io\n'
    (directory/'run-once.command').write_text(command);(directory/'run-once.command').chmod(0o700)
    dependencies={str(p):sha(p) for p in [Path(python),CLANG,LLD,LIBUSB]}
    operation=dict(schema='a7r5-exec-once-1',directory=str(directory),tool_root=str(HERE),engine=engine,run_id=run,
                   risk=risk(engine),payload=elf,resources=resources(),dependencies=dependencies,
                   artifacts={str(p.relative_to(directory)):sha(p) for p in sorted(directory.rglob('*')) if p.is_file()},
                   camera_execution_verified=False,script_is_sandboxed=False)
    save(directory/'operation.json',operation)
    if engine=='kit':save(directory/'approval-template.json',approval_for(directory,operation,False))
    return directory


def load(directory):
    directory=safe(directory)
    if directory.parent!=HERE/'runs':raise ValueError('不是本工具runs中的会话')
    op=json.loads(regular(directory/'operation.json').read_text());check_tool()
    if (op['schema']!='a7r5-exec-once-1' or op['directory']!=str(directory) or op['tool_root']!=str(HERE)
            or op['engine'] not in ('libjit','kit') or op['risk']!=risk(op['engine']) or op['run_id']!=directory.name):
        raise ValueError('会话、位置或风险说明不符')
    if op['resources']!=resources():raise ValueError('执行器材料变化')
    if set(op['dependencies'])!={str(p) for p in [Path(sys.executable).resolve(),CLANG,LLD,LIBUSB]}:
        raise ValueError('解释器或工具依赖解析路径变化')
    for name,want in op['dependencies'].items():
        if sha(name)!=want:raise ValueError('依赖变化：'+name)
    for name,want in op['artifacts'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or sha(directory/name)!=want:raise ValueError('材料变化：'+name)
    return op


def approval_for(directory,op,accepted):
    return dict(accepted=accepted,operation_sha256=sha(directory/'operation.json'),run_id=op['run_id'],risk=op['risk'])


def approve(directory,phrase):
    directory=safe(directory);op=load(directory)
    if phrase!='ACCEPT-'+sha(directory/'operation.json')[:16]:raise PermissionError('须明确接受本次材料和脚本的风险短语')
    if any((directory/p).exists() for p in ['ATTEMPT_LOCK','result']):raise FileExistsError('已经尝试，不能重新批准')
    save(directory/'approval.json',approval_for(directory,op,True))


def approved(directory):
    directory=safe(directory)
    if not (directory/'approval.json').is_file():raise PermissionError('没有本次批准，不观察设备')
    op=load(directory);value=json.loads(regular(directory/'approval.json').read_text())
    if value!=approval_for(directory,op,True) or value.get('accepted') is not True:raise PermissionError('批准不符')
    if any((directory/p).exists() for p in ['ATTEMPT_LOCK','result']):raise FileExistsError('单次操作已经使用，不重跑')
    return op
