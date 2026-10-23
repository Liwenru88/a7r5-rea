"""独立模块的离线封存与AArch64构建；本文件不导入USB后端。"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import uuid

HERE=Path(__file__).resolve().parent
MODULE=HERE.parent
sys.path.insert(0,str(MODULE/'src'))
from trust_recipe import construct, SOURCE_P1_SHA, TARGET_SHA, PUBLIC_SHA
from sector_plan import make_plan
from filesystems import require, sha

CLANG=Path('/opt/homebrew/opt/llvm/bin/clang')
LLD=Path('/opt/homebrew/opt/lld/bin/ld.lld')
LIBUSB=Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib')


def safe(value):
    path=Path(value).absolute()
    require('..' not in path.parts and not path.is_relative_to('/dev'),'非法本机路径')
    require(not any(p.is_symlink() for p in (path,*path.parents)),'本机材料不得经过符号链接')
    return path


def regular(value):
    path=safe(value)
    require(stat.S_ISREG(path.stat().st_mode),'只接受普通本机材料')
    return path


def digest(value):
    with regular(value).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def save(path,value):
    raw=value if isinstance(value,bytes) else (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
    with safe(path).open('xb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())


def resources():
    paths=[*HERE.glob('*.py'),*HERE.glob('*.sh'),HERE/'profile-historical.json',MODULE/'public-key.pem',*list((MODULE/'src').glob('*.py'))]
    for sub in ('payload','runtime','vendor'):
        paths += [p for p in (HERE/sub).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    return {str(p.relative_to(MODULE)):digest(p) for p in sorted(paths)}


def validate_profile(profile,preload_name):
    known=json.loads((HERE/'profile-historical.json').read_text())
    require(profile['host_baseline']['model']=='ILCE-7RM5' and profile['host_baseline']['pid']==0x0e0a,'只支持A7R5普通身份')
    require(profile['host_baseline']['location_id']==0x00100000,'本版只接受已验证端口，不自动换口')
    require(profile['host_baseline']['media'] and profile['host_baseline']['drivers'],'缺少完整媒体或驱动基线')
    for key,pid in [('interface-1.json',0x0e0a),('interface-2.json',0x0336)]:
        entry=profile['interfaces'][key]
        require(entry['pid']==pid and entry['bus']==0 and entry['ports']==[1] and entry['number']==entry['alternate']==0,'接口身份不符')
        require([e['address']for e in entry['endpoints']][:2]==[129,2],'端点顺序不符')
        require(entry==known['interfaces'][key],'接口指纹未知，禁止改类型后退选其他bulk端点')
    require(profile['loader_sha256']=='ea2d9ba9dbeb56fc11ad88be7b5c30b6b237f8ccc55ce9f24c02546eb0ba07b1' and profile['loader_bytes']==233416,'加载器身份不符')
    require(isinstance(profile['version_sha256'],str) and len(profile['version_sha256'])==64 and all(c in '0123456789abcdef'for c in profile['version_sha256']),'版本摘要无效')
    choices={name:bytes.fromhex(raw) for name,raw in profile['preload_baselines']}
    approved={name:bytes.fromhex(raw)for name,raw in known['preload_baselines']}
    require(preload_name in choices and choices[preload_name]==approved.get(preload_name),'必须选择一个精确已知预加载基线')
    return choices[preload_name]


def emit_array(name,raw):
    return 'static const unsigned char '+name+'[]={'+','.join(str(b)for b in raw)+'};\n'


def compile_native(directory,cfg,before,after,fixture=False):
    materials=directory/'materials';materials.mkdir(mode=0o700)
    run=cfg['run_id'];prefix='/tmp/jiritsu/a7r5-jit-'+run
    strings=dict(RUN_ID=run,STATE_PATH=prefix+'.state',STATE_NEW=prefix+'.state.new',
        OUTPUT_PATH=prefix+'.output',CLAIM_PATH=prefix+'.claim',TICKET_PATH=prefix+'.ticket',
        TICKET_BYTES='A7R5_LIBJIT '+run+'\n',LIBJIT_PATH='/tmp/jiritsu/libJit.so')
    save(materials/'jit_config.h', ''.join('#define '+k+' '+json.dumps(v)+'\n'for k,v in strings.items()).encode())
    plan=make_plan(before,after);rows=plan['rows']
    old=b''.join(before[r['offset']:r['offset']+512]for r in rows)
    new=b''.join(after[r['offset']:r['offset']+512]for r in rows)
    defs=dict(ORIGINAL_SHA=SOURCE_P1_SHA,CANDIDATE_SHA=TARGET_SHA,BEFORE_PATCH_SHA=sha(old),AFTER_PATCH_SHA=sha(new),
        RAM_DIR=cfg['ram_dir'],JOURNAL_PATH=cfg['journal_path'],READBACK_PATH=cfg['readback_path'],
        EXPECTED_PRELOAD=bytes.fromhex(cfg['expected_preload_hex']).decode('ascii'),
        OUTPUT_BEGIN=cfg['expected_output_begin'],OUTPUT_END=cfg['expected_output_end'],
        TARGET_PATH=('/simulation/trust-'+run+'/disk.img') if fixture else '/dev/cnflasha1')
    header=''.join('#define '+k+' '+json.dumps(v)+'\n'for k,v in defs.items())
    header+='#define PARTITION_BYTES 25100288UL\n#define PATCH_COUNT 258U\n'
    header+='static const unsigned long PATCH_OFFSETS[]={'+','.join(str(r['offset'])+'UL'for r in rows)+'};\n'
    header+='static const unsigned char PATCH_CHECKSUM[]={'+','.join(str(int(r['phase']=='checksum'))for r in rows)+'};\n'
    header+=emit_array('BEFORE_SECTORS',old)+emit_array('AFTER_SECTORS',new)
    save(materials/'trust_config.h',header.encode())
    command=[str(CLANG),'--target=aarch64-linux-gnu','--ld-path='+str(LLD),'-nostdlib','-ffreestanding','-fno-builtin',
        '-fno-stack-protector','-fPIC','-shared','-fvisibility=hidden','-O2','-Wall','-Wextra','-Werror',
        '-Wl,--no-undefined','-Wl,-z,max-page-size=65536','-Wl,-init,_init',
        '-I',str(materials),'-I',str(HERE/'payload'),str(HERE/'payload/libjit-trust.c'),'-o',str(materials/'libJit.so')]
    if fixture:command+=['-DTRUST_FIXTURE']
    result=subprocess.run(command,capture_output=True,text=True,timeout=60)
    save(materials/'build.json',dict(argv=command,returncode=result.returncode,stderr=result.stderr,camera_IO=False))
    require(result.returncode==0,'载荷构建失败：'+result.stderr[-2000:])
    from elftools.elf.elffile import ELFFile
    with (materials/'libJit.so').open('rb')as f:
        elf=ELFFile(f);tags=list(elf.get_section_by_name('.dynamic').iter_tags())
        needed=[t.needed for t in tags if t.entry.d_tag=='DT_NEEDED']
        undefined=[s.name for s in elf.get_section_by_name('.dynsym').iter_symbols() if s.name and s['st_shndx']=='SHN_UNDEF']
        require(elf['e_machine']=='EM_AARCH64' and elf['e_type']=='ET_DYN' and not needed and not undefined,'载荷不是无依赖AArch64库')
        require(any(t.entry.d_tag=='DT_INIT'for t in tags),'缺少构造入口')
    require((materials/'libJit.so').stat().st_size<1048576,'载荷超出固定通道上限')
    save(materials/'ticket.bin',strings['TICKET_BYTES'].encode())
    save(materials/'candidate.logical.img',after)
    save(materials/'write-plan.json',plan)
    return dict(sha256=digest(materials/'libJit.so'),bytes=(materials/'libJit.so').stat().st_size,needed=needed,undefined=undefined,fixture=fixture)


def prepare(source,profile_path,preload_name,fixture=False,output_root=None):
    before=regular(source).read_bytes();public=regular(MODULE/'public-key.pem').read_bytes()
    require(sha(before)==SOURCE_P1_SHA and sha(public)==PUBLIC_SHA,'固定输入摘要不符')
    profile=json.loads(regular(profile_path).read_text());baseline=validate_profile(profile,preload_name)
    after,_,_,facts=construct(before,None,public);require(sha(after)==TARGET_SHA,'完整候选重建不符')
    run=uuid.uuid4().hex
    root=safe(output_root) if output_root else HERE/'runs'
    root.mkdir(mode=0o700,exist_ok=True)
    directory=root/run;directory.mkdir(mode=0o700)
    cfg={k:profile[k]for k in ('interfaces','host_baseline','version_sha256','loader_sha256','loader_bytes')}
    cfg.update(run_id=run,expected_preload_hex=baseline.hex(),task_seconds=60,observe_seconds=60,
        ram_dir='/tmp_wbshd/a7r5-trust-'+run,journal_path='/tmp_wbshd/a7r5-trust-'+run+'/journal',
        readback_path='/tmp_wbshd/a7r5-trust-'+run+'/partition.logical',partition_bytes=25100288,
        candidate_sha256=TARGET_SHA,source_sha256=SOURCE_P1_SHA,
        expected_output_begin='A7R5_TRUST_BEGIN_'+run+'\n',expected_output_end='A7R5_TRUST_END_'+run+'\n')
    save(directory/'config.json',cfg)
    payload=compile_native(directory,cfg,before,after,fixture)
    quote=__import__('shlex').quote
    script='#!/bin/zsh\nset -eu\nTASK_RUN="${0:A:h}"\n'
    script+='if [[ "$TASK_RUN" != '+quote(str(directory))+' ]]; then\n  print -u2 "会话启动脚本已移动；请重新prepare，不回指旧目录执行"\n  exit 2\nfi\n'
    script+='exec sudo '+quote(str(Path(sys.executable).absolute()))+' -B '+quote(str(HERE/'deploy.py'))+' execute --run '+quote(str(directory))+' --device-io\n'
    save(directory/'run-once.command',script.encode());(directory/'run-once.command').chmod(0o700)
    dependencies={str(p.resolve()):hashlib.sha256(p.resolve().read_bytes()).hexdigest()for p in [Path(sys.executable),CLANG,LLD,LIBUSB]}
    manifest=dict(schema='a7r5-trust-libjit-once-v2',directory=str(directory),run_id=run,fixture=fixture,
        payload=payload,resources=resources(),dependencies=dependencies,
        files={str(p.relative_to(directory)):digest(p)for p in sorted(directory.rglob('*'))if p.is_file()},
        risk='固定管理文件上传及一次libJit触发，最多258扇区写入一号逻辑明文分区；非原子，固定残留、掉电和恢复受限风险。无预加载写入、无DEBUG、无自动重试或回滚。超时只停止主机观察，不杀写入进程；异常不STOP。',
        source_original_sha256=sha(before),filesystems=facts,camera_IO=False,current_device_binding_verified=False)
    save(directory/'manifest.json',manifest)
    save(directory/'approval-template.json',dict(accepted=False,run_id=run,manifest_sha256=digest(directory/'manifest.json')))
    return directory


def check(directory,allow_fixture=False):
    directory=safe(directory);m=json.loads(regular(directory/'manifest.json').read_text())
    require(m['schema']=='a7r5-trust-libjit-once-v2' and m['directory']==str(directory) and m['run_id']==directory.name,'会话位置或身份不符')
    require(not m['fixture'] or allow_fixture,'夹具库禁止实机执行')
    payload=regular(directory/'materials/libJit.so').read_bytes()
    require(sha(payload)==m['payload']['sha256'] and m['payload']['fixture']==m['fixture'],'载荷身份标记不符')
    if not m['fixture']:
        require(b'A7R5_TRUST_PRODUCTION_V2\0' in payload and b'A7R5_TRUST_FIXTURE_ONLY_V2' not in payload and b'/simulation/trust-' not in payload,'载荷内部是夹具或缺少生产标记')
    else:
        require(b'A7R5_TRUST_FIXTURE_ONLY_V2\0' in payload,'夹具内部标记不符')
    require(m['resources']==resources(),'模块资源变化，应重新准备，不能复用批准')
    for name,want in m['files'].items():
        require(not Path(name).is_absolute() and '..' not in Path(name).parts and digest(directory/name)==want,'会话材料变化：'+name)
    for name,want in m['dependencies'].items():
        require(hashlib.sha256(Path(name).read_bytes()).hexdigest()==want,'依赖变化：'+name)
    cfg=json.loads((directory/'config.json').read_text())
    require(cfg['source_sha256']==SOURCE_P1_SHA and cfg['candidate_sha256']==TARGET_SHA and cfg['partition_bytes']==25100288,'目标身份变化')
    return m
