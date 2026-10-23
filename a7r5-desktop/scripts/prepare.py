#!/usr/bin/env python3
"""只在开发机准备独立运行材料；不导入USB后端，不访问相机。"""
import argparse
import ast
import base64
import gzip
import hashlib
import importlib.util
import itertools
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
PREPARED = ROOT/'prepared'
ENGINE = PREPARED/'engine'
MARKER = 'd9a7216bc84f305e92a16bd4c7e038f5'
HASH_MARKER = '$6$rounds=10000$Q8j3k9w2s7m4n6p1$' + ''.join(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./'[b % 64]
    for b in hashlib.shake_256(b'a7r5-desktop-template-not-a-password').digest(86))
CLANG = '/opt/homebrew/opt/llvm/bin/clang'
LLD = '/opt/homebrew/opt/lld/bin/ld.lld'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def copy_tree(source, destination):
    shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=False,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store', 'test', 'tests', '.git'))


def jit_values(run):
    prefix = '/tmp/jiritsu/a7r5-jit-' + run
    return dict(RUN_ID=run, STATE_PATH=prefix+'.state', STATE_NEW=prefix+'.state.new',
                OUTPUT_PATH=prefix+'.output', CLAIM_PATH=prefix+'.claim', TICKET_PATH=prefix+'.ticket',
                TICKET_BYTES='A7R5_LIBJIT '+run+'\n', LIBJIT_PATH='/tmp/jiritsu/libJit.so')


def header(path, values):
    path.write_text(''.join('#define '+k+' '+json.dumps(v)+'\n' for k, v in values.items()))


def compile_configurable(command, *, run, password_hash=None, **kwargs):
    """将可变字符串放入单独编译的配置段，避免字符串合并和指令常量化。"""
    source = next(Path(v) for v in command if str(v).endswith('.c'))
    output = Path(command[command.index('-o')+1])
    include_args = []
    for index, value in enumerate(command):
        if value == '-I':include_args += ['-I', str(command[index+1])]
    text = subprocess.run([CLANG, '--target=aarch64-linux-gnu', '-E', '-P', *include_args, str(source)],
                          capture_output=True, text=True, check=True).stdout
    declarations, definitions = [], []
    strings = re.compile(r'"(?:\\.|[^"\\])*"(?:\s*"(?:\\.|[^"\\])*")*')
    lengths = {}
    def extract(match):
        pieces = re.findall(r'"(?:\\.|[^"\\])*"', match[0])
        if run not in match[0] and (password_hash is None or password_hash not in match[0]):return match[0]
        value = ''.join(ast.literal_eval(piece) for piece in pieces)
        name = 'desktop_config_'+str(len(declarations));size = len(value.encode())+1
        lengths[name] = size
        declarations.append(f'extern char {name}[{size}];')
        definitions.append(f'__attribute__((used,section(".a7r5_cfg"))) char {name}[{size}]='+json.dumps(value)+';')
        return name
    text = strings.sub(extract, text)
    # C局部数组仍保留原来的大小和sizeof语义，从外部配置段初始化。
    def initialize(match):
        variable, field = match[1], match[2]
        size = lengths[field]
        return f'char {variable}[{size}];__builtin_memcpy({variable},{field},{size});'
    text = re.sub(r'const\s+char\s+(\w+)\[\s*\]\s*=\s*(desktop_config_\d+)\s*;', initialize, text)
    body = output.parent/'desktop-body.c';config = output.parent/'desktop-config.c'
    body.write_text('\n'.join(declarations)+'\n'+text)
    config.write_text('\n'.join(definitions)+'\n')
    revised = [str(body) if str(v) == str(source) else str(v) for v in command]
    return subprocess.run([*revised, str(config), '-Wl,-O0', '-Wno-unused-but-set-global'], **kwargs)


def compile_library(directory, source, run):
    output = directory/'libJit.so'
    command = [CLANG, '--target=aarch64-linux-gnu', '--ld-path='+LLD, '-nostdlib',
               '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-fPIC', '-shared',
               '-fvisibility=hidden', '-O2', '-Wall', '-Wextra', '-Werror', '-Wl,-O0', '-Wl,--no-undefined',
               '-Wl,-z,max-page-size=65536', '-Wl,-init,_init', '-I', str(directory),
               '-I', str(ROOT/'sources/trust'), str(source), '-o', str(output)]
    compile_configurable(command, run=run, check=True, capture_output=True)
    return output.read_bytes()


def capture_library(directory, run):
    directory.mkdir()
    profile = json.loads((ROOT/'engine/profile.json').read_text())
    header(directory/'jit_config.h', jit_values(run))
    header(directory/'capture_config.h', dict(CAPTURE_TARGET='/dev/cnflasha1',
        CAPTURE_RAM_PARENT='/tmp_wbshd', CAPTURE_RAM_DIR='/tmp_wbshd/a7r5-capture-'+run,
        CAPTURE_PATH='/tmp_wbshd/a7r5-capture-'+run+'/partition.bin',
        CAPTURE_BEGIN='A7R5_CAPTURE_BEGIN '+run+'\n', CAPTURE_END='A7R5_CAPTURE_END '+run+'\n',
        PRELOAD_A=bytes.fromhex(profile['preload_baselines'][0][1]).decode(),
        PRELOAD_B=bytes.fromhex(profile['preload_baselines'][1][1]).decode()))
    source = (ROOT/'sources/trust/libjit-trust.c').read_text().replace(
        '#include "native_gate.c"', '#include "capture_gate.c"').replace(
        'A7R5_TRUST_PRODUCTION_V2', 'A7R5_CAPTURE_READONLY_V1')
    (directory/'capture-wrapper.c').write_text(source)
    return compile_library(directory, directory/'capture-wrapper.c', run)


def trust_library(directory, run, preload, before, after, plan):
    directory.mkdir()
    header(directory/'jit_config.h', jit_values(run))
    rows = plan['rows']
    old = b''.join(before[r['offset']:r['offset']+512] for r in rows)
    new = b''.join(after[r['offset']:r['offset']+512] for r in rows)
    ram = '/tmp_wbshd/a7r5-trust-'+run
    header(directory/'trust_config.h', dict(ORIGINAL_SHA=sha(before), CANDIDATE_SHA=sha(after),
        BEFORE_PATCH_SHA=sha(old), AFTER_PATCH_SHA=sha(new), RAM_DIR=ram,
        JOURNAL_PATH=ram+'/journal', READBACK_PATH=ram+'/partition.logical', EXPECTED_PRELOAD=preload,
        OUTPUT_BEGIN='A7R5_TRUST_BEGIN_'+run+'\n', OUTPUT_END='A7R5_TRUST_END_'+run+'\n', TARGET_PATH='/dev/cnflasha1'))
    with (directory/'trust_config.h').open('a') as stream:
        stream.write('#define PARTITION_BYTES 25100288UL\n#define PATCH_COUNT 258U\n')
        stream.write('static const unsigned long PATCH_OFFSETS[]={'+','.join(str(r['offset'])+'UL' for r in rows)+'};\n')
        stream.write('static const unsigned char PATCH_CHECKSUM[]={'+','.join(str(int(r['phase']=='checksum')) for r in rows)+'};\n')
        for name, raw in [('BEFORE_SECTORS', old), ('AFTER_SECTORS', new)]:
            stream.write('static const unsigned char '+name+'[]={'+','.join(str(b) for b in raw)+'};\n')
    return compile_library(directory, ROOT/'sources/trust/libjit-trust.c', run)


def template_record(name, raw, alternate, run, *, hash_value=None):
    from elftools.elf.elffile import ELFFile
    import io
    elf = ELFFile(io.BytesIO(raw))
    assert elf['e_machine'] == 'EM_AARCH64' and elf['e_type'] == 'ET_DYN'
    ranges = [(s['sh_offset'], s['sh_offset']+s['sh_size']) for s in elf.iter_sections()
              if s.name == '.a7r5_cfg']
    fields = [(MARKER.encode(), run.encode())]
    if hash_value:
        fields.append((HASH_MARKER.encode(), hash_value.encode()))
    patched = raw
    counts = {}
    for old, new in fields:
        assert len(old) == len(new)
        positions = []
        start = 0
        while (at := raw.find(old, start)) >= 0:
            assert any(a <= at and at+len(old) <= b for a, b in ranges), (name, '模板字段位于非数据段')
            positions.append(at);start = at+len(old)
        # 部分SSH程序不使用密码哈希，允许相应字段不存在。
        counts['run' if old == MARKER.encode() else 'password_hash'] = len(positions)
        patched = patched.replace(old, new)
    assert patched == alternate, (name, '配置替换与独立编译结果不一致，禁止打包')
    assert counts['run'] > 0
    target = ENGINE/'templates'/name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return dict(sha256=sha(raw), bytes=len(raw), fields=counts, configuration_matches_compilation=True)


def payloads():
    sys.path.insert(0, str(PROJECT/'a7r5-updater-trust/src'))
    import trust_recipe, sector_plan
    before = (PROJECT/'a7r5-firmware-images/标准固件_19项/明文分区_17项/cnflasha1.img').read_bytes()
    public = (PROJECT/'a7r5-updater-trust/public-key.pem').read_bytes()
    after, _, _, _ = trust_recipe.construct(before, None, public)
    assert sha(after) == trust_recipe.TARGET_SHA
    plan = sector_plan.make_plan(before, after)
    save(ENGINE/'write-plan.json', plan)
    sectors = dict(source_sha256=sha(before), target_sha256=sha(after), bytes=len(before), rows=[
        dict(offset=r['offset'], before=base64.b64encode(before[r['offset']:r['offset']+512]).decode(),
             after=base64.b64encode(after[r['offset']:r['offset']+512]).decode()) for r in plan['rows']])
    save(ENGINE/'trust-sectors.json', sectors)
    profile = json.loads((ROOT/'engine/profile.json').read_text())
    report = {}
    with tempfile.TemporaryDirectory(prefix='a7r5-payload-build-') as temporary:
        folder = Path(temporary).resolve()
        run = secrets.token_hex(16)
        report['capture.so'] = template_record('capture.so', capture_library(folder/'ca', MARKER), capture_library(folder/'cb', run), run)
        for index, (name, preload) in enumerate(profile['preload_baselines']):
            text = bytes.fromhex(preload).decode()
            report['trust-'+name+'.so'] = template_record('trust-'+name+'.so',
                trust_library(folder/('ta'+str(index)), MARKER, text, before, after, plan),
                trust_library(folder/('tb'+str(index)), run, text, before, after, plan), run)
        # 编译沿用已核对的原厂libc SDK；运行包不携带SDK或编译器。
        build = module(PROJECT/'a7r5-ssh/libjit-ssh-on-demand/build.py', 'desktop_ssh_builder')
        from types import SimpleNamespace
        # 关闭链接时字符串合并，使配置内容变化不改变数据段布局及重定位。
        other_hash = '$6$rounds=10000$'+secrets.token_hex(8)+'$'+''.join(secrets.choice('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./') for _ in range(86))
        build.subprocess = SimpleNamespace(run=lambda command, **kw:compile_configurable(command, run=MARKER, password_hash=HASH_MARKER, **kw))
        build.build(folder/'ssh-a', HASH_MARKER, run=MARKER)
        build.subprocess = SimpleNamespace(run=lambda command, **kw:compile_configurable(command, run=run, password_hash=other_hash, **kw))
        build.build(folder/'ssh-b', other_hash, run=run)
        for filename in ('service.arm64', 'session.arm64', 'libJit.so'):
            report['ssh-'+filename] = template_record('ssh-'+filename,
                (folder/'ssh-a'/filename).read_bytes(), (folder/'ssh-b'/filename).read_bytes(), run, hash_value=other_hash)
        for name in ('sftp-server.arm64', 'sftp-provenance.json', 'sftp-COPYRIGHT'):
            shutil.copyfile(folder/'ssh-a'/name, ENGINE/'templates'/name)
    save(ENGINE/'templates.json', dict(run_marker=MARKER, hash_marker=HASH_MARKER, files=report))
    save(ROOT/'verification/payload-build.json', dict(templates=report, camera_IO=False, compiler_not_required_at_runtime=True,
        wrapper_change='独立副本使用AArch64 O_NOFOLLOW=32768；原模块未修改'))
    print('载荷模板准备完成，独立编译配置一致性通过', flush=True)


def delta_record(original, target):
    import re
    assert len(original) == len(target)
    # 先按64字节块筛选；小间隙合并，减少JSON和运行时替换次数。
    spans = []
    for offset in range(0, len(original), 65536):
        before, after = original[offset:offset+65536], target[offset:offset+65536]
        if before == after:
            continue
        mask = bytes(a != b for a, b in zip(before, after))
        for match in re.finditer(b'\x01(?:[\x00]{0,31}\x01)*', mask):
            a, b = (offset+v for v in match.span())
            spans.append(dict(offset=a, before=original[a:b].hex(), after=target[a:b].hex()))
    rebuilt = bytearray(original)
    for row in spans:
        raw = bytes.fromhex(row['after']);rebuilt[row['offset']:row['offset']+len(raw)] = raw
    assert bytes(rebuilt) == target
    return dict(before_bytes=len(original), before_sha256=sha(original), after_bytes=len(target), after_sha256=sha(target), patches=spans)


def feature_patches(*, engine=None, receipt=None):
    import feature_builder as features
    destination = Path(engine) if engine is not None else ENGINE
    with tempfile.TemporaryDirectory(prefix='a7r5-features-build-') as temporary:
        work = Path(temporary).resolve()/'work'
        subprocess.run([str(PROJECT/'a7r5-dat-tool/.venv/bin/python'), '-B', str(PROJECT/'a7r5-dat-tool/dattool.py'),
                        'unpack', str(PROJECT/'a7r5-firmware-images/官方升级包/BODYDATA.DAT'), '--output', str(work)], check=True, capture_output=True)
        ap, cp = (work/features.AP).read_bytes(), (work/features.CP).read_bytes()
        manifest = {}
        for bits in itertools.product((False, True), repeat=4):
            key = ''.join(str(int(v)) for v in bits)
            flags = dict(zip(features.KEYS, bits))
            value = {features.AP:delta_record(ap, features.build_ap(ap, flags)), features.CP:delta_record(cp, features.build_cp(cp, flags))}
            for name, row in value.items():row['path'] = name
            packed = gzip.compress(json.dumps(value, separators=(',', ':')).encode(), mtime=0)
            target = destination/'feature-patches'/(key+'.json.gz');target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(packed)
            manifest[key] = dict(sha256=sha(packed), targets={name:row['after_sha256'] for name, row in value.items()})
            print('功能补丁准备：'+key, flush=True)
        save(destination/'feature-patches/manifest.json', manifest)
        save(receipt or ROOT/'verification/feature-build.json', dict(combinations=manifest, camera_IO=False))


def relocate_macho(path, library_dir, copied):
    path = Path(path)
    result = subprocess.run(['/usr/bin/otool', '-L', str(path)], capture_output=True, text=True, check=True)
    for line in result.stdout.splitlines()[1:]:
        dependency = line.strip().split(' (', 1)[0]
        if not dependency.startswith('/opt/homebrew/'):
            continue
        source = Path(dependency).resolve()
        destination = library_dir/source.name
        if source not in copied:
            copied.add(source)
            shutil.copyfile(source, destination)
            destination.chmod(0o755)
            relocate_macho(destination, library_dir, copied)
        relative = os.path.relpath(destination, path.parent)
        subprocess.run(['/usr/bin/install_name_tool', '-change', dependency, '@loader_path/'+relative, str(path)], check=True, capture_output=True)
    if path.suffix == '.dylib':
        subprocess.run(['/usr/bin/install_name_tool', '-id', '@loader_path/'+path.name, str(path)], check=True, capture_output=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(path)], check=True, capture_output=True)


def runtime():
    ENGINE.mkdir(parents=True, exist_ok=True)
    copy_tree(ROOT/'engine', ENGINE)
    runtime_root = ENGINE/'python'
    base = Path(sys.base_prefix)
    copy_tree(base, runtime_root)
    # 当前uv解释器可搬迁；只移除构建时不需要的入口，不改开发机解释器。
    site = ENGINE/'site';site.mkdir(exist_ok=True)
    dat_site = PROJECT/'a7r5-dat-tool/.venv/lib/python3.14/site-packages'
    for name in ('numpy', 'numpy.libs', 'Cryptodome', 'cryptography', '_cffi_backend.cpython-314-darwin.so'):
        source = dat_site/name
        if not source.exists():
            continue
        if source.is_dir():copy_tree(source, site/name)
        else:shutil.copyfile(source, site/name)
    copy_tree(PROJECT/'a7r5-dat-tool/a7r5dat', ENGINE/'a7r5dat')
    vendor = ENGINE/'vendor';vendor.mkdir(exist_ok=True)
    copy_tree(PROJECT/'a7r5-updater-trust/deploy/vendor/engine/libs/usb', site/'usb')
    copy_tree(PROJECT/'a7r5-updater-trust/deploy/vendor/engine/sources/workspaces/j/work/sony-pmca-re', vendor/'pmca_source')
    keys = ENGINE/'keys';keys.mkdir(exist_ok=True, mode=0o700)
    for name in ('research-signing-private.pem', 'research-public.pem', 'sony-original-public.pem'):
        shutil.copyfile(PROJECT/'a7r5-dat-tool/keys'/name, keys/name)
        (keys/name).chmod(0o600)
    libraries = ENGINE/'lib';libraries.mkdir(exist_ok=True)
    binaries = ENGINE/'bin';binaries.mkdir(exist_ok=True)
    # 已生成目录中的旧哈希程序不再属于运行依赖；只清理本轮构建产物。
    for obsolete in (binaries/'openssl',libraries/'libssl.3.dylib',libraries/'libcrypto.3.dylib',libraries/'libusb-1.0.0.dylib'):
        if obsolete.exists():obsolete.unlink()
    for source, destination in [(PREPARED/'dependencies/libusb-1.0.dylib', libraries/'libusb-1.0.dylib')]:
        shutil.copyfile(source.resolve(), destination);destination.chmod(0o755)
        relocate_macho(destination, libraries, set())
    notices=ENGINE/'notices';notices.mkdir(exist_ok=True)
    for name in ('libusb-1.0.30.tar.bz2','libusb-COPYING','libusb-build.json'):
        shutil.copyfile(PREPARED/'dependencies'/name,notices/name)
    for pattern in ('numpy-*.dist-info','pycryptodomex-*.dist-info','cryptography-*.dist-info','cffi-*.dist-info'):
        source=next(dat_site.glob(pattern));copy_tree(source,notices/source.name)
    usb_license=PROJECT/'a7r5-updater-trust/deploy/vendor/engine/libs/PyUSB-1.3.1.dist-info/licenses/LICENSE'
    if usb_license.exists():shutil.copyfile(usb_license,notices/'PyUSB-LICENSE')
    save(ENGINE/'runtime-info.json', dict(python='3.14', platform='macOS-arm64', qemu_required=False,
        homebrew_required=False, compiler_required=False, contains_research_signing_identity=True))
    # 在封存前给全部本机运行组件加临时签名，不要求终端用户安装开发依赖。
    for path in ENGINE.rglob('*'):
        if path.is_file() and path.read_bytes()[:4] in (b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe'):
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(path)], check=True, capture_output=True)
    print('独立Python及USB运行库准备完成；密码哈希由Rust内部计算', flush=True)


def seal():
    files = {str(p.relative_to(ENGINE)):dict(sha256=sha(p.read_bytes()), bytes=p.stat().st_size)
             for p in sorted(ENGINE.rglob('*')) if p.is_file() and p.name != 'integrity.json'}
    save(ENGINE/'integrity.json', dict(schema=1, files=files))
    (ROOT/'src-tauri/engine.sha256').write_text(sha((ENGINE/'integrity.json').read_bytes())+'\n')
    print('材料清单已封存：'+str(len(files))+'个文件', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage', choices=('runtime', 'payloads', 'features', 'seal', 'all'))
    args = p.parse_args()
    os.umask(0o077)
    ENGINE.mkdir(parents=True, exist_ok=True)
    for name, function in [('runtime',runtime), ('payloads',payloads), ('features',feature_patches), ('seal',seal)]:
        if args.stage in (name, 'all'):function()
