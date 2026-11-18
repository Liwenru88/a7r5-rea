"""校验冻结来源后生成独立的容量／文件原型；不生成可安装固件。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
FEATURE = HERE.parent / 'native12-combined'
UPSTREAM = FEATURE / 'upstream'
SOURCE = UPSTREAM / 'firmware/r5/src'
SNAPSHOT_SHA = 'c81e5b4681479eccf99224aae820adabaf139df3fb758a1e1927d81787e0ad95'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def replace(text, before, after, count=1):
    if text.count(before) != count:
        raise ValueError(f'派生前像次数不符：{before!r}，期望{count}，实际{text.count(before)}')
    return text.replace(before, after)


def codec24(text):
    text = replace(text, "static const uint8_t magic[8]=", "static const uint8_t magic5[8]={'R','5','C','U','S','T','5',0};\nstatic const uint8_t magic[8]=")
    text = replace(text, 'u32(p)>12', 'u32(p)>R5_LOOK_SLOTS')
    text = replace(text, 'uint32_t count,mask,found=0,previous=0,i;',
                   'uint32_t count,mask,found=0,previous=0,i,limit,version;')
    text = replace(text, 'count=u32(p+20);mask=u32(p+24);',
                   'count=u32(p+20);mask=u32(p+24);version=u32(p+8);limit=version==4?12u:24u;')
    text = replace(text, '!equal(p,magic,8) || u32(p+8)!=R5_LOOK_VERSION',
                   '((version!=4 || !equal(p,magic,8)) && (version!=5 || !equal(p,magic5,8)))')
    text = replace(text, 'count>12', 'count>limit')
    text = replace(text, '(mask&~4095u)', '(mask&~((1u<<limit)-1u))')
    text = replace(text, '!valid_record(r) || slot<=previous',
                   '!valid_record(r) || slot>limit || slot<=previous')
    text = replace(text, '(set->valid_mask&~4095u)', '(set->valid_mask&~0xffffffu)', 2)
    text = replace(text, 'slot<12;', 'slot<R5_LOOK_SLOTS;', 2)
    text = replace(text, 'i<12;i++', 'i<R5_LOOK_SLOTS;i++', 2)
    text = replace(text, 'for (i=0;i<8;i++) out[i]=magic[i];\n    put32(out+8,R5_LOOK_VERSION);',
                   '{unsigned v=(set->valid_mask&~4095u)?5u:4u;\n'
                   '     const uint8_t *m=v==5?magic5:magic;\n'
                   '     for(i=0;i<8;i++)out[i]=m[i];put32(out+8,v);}\n    ')
    return replace(text, 'sizeof(struct r5_look_set)==29332', 'sizeof(struct r5_look_set)==58660')


def selection24(text):
    text = replace(text, 'r->selected>12', 'r->selected>R5_LOOK_SLOTS', 2)
    text = replace(text, 'selected>12', 'selected>R5_LOOK_SLOTS', 2)
    return replace(text, 'put32(p+12,selected);put32(p+20,crc(p,24,20));',
                   "put32(p+12,selected);if(selected>12){p[5]='5';put32(p+8,2);}\n"
                   '    put32(p+20,crc(p,24,20));')


WRAPPER = '''/* 仅暴露原选择文件的静态编解码，不接文件系统。 */
#include "selection.c"
unsigned prototype_selection_encode(unsigned n,uint8_t out[24]) {
    if(n>R5_LOOK_SLOTS || !out)return 0;encode(n,out);return 1;
}
int prototype_selection_decode(const uint8_t in[24],unsigned *out) {
    if(!in || !out)return -1;return decode(in,out);
}
'''


def prepare(output):
    lock = UPSTREAM / 'UPSTREAM_SNAPSHOT.json'
    if sha(lock) != SNAPSHOT_SHA:
        raise ValueError('上游快照身份不符')
    snapshot = json.loads(lock.read_text())
    for name, row in snapshot['files'].items():
        p = UPSTREAM / name
        if p.stat().st_size != row['bytes'] or sha(p) != row['sha256']:
            raise ValueError(f'冻结来源不符：{name}')
    # 只允许新目录，所有编译及派生文件均在此目录下。
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'schema': 'native24-feasibility/1', 'upstream_snapshot_sha256': sha(lock),
               'upstream_files_verified': len(snapshot['files']), 'commands': [], 'inputs': {},
               'outputs': {}, 'firmware_generated': False, 'DAT_generated': False, 'camera_io': False}

    def command(argv):
        result = subprocess.run(argv, text=True, capture_output=True)
        receipt['commands'].append({'argv': argv, 'exit_code': result.returncode,
                                    'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode:
            (output / 'failed-build.json').write_text(json.dumps(receipt, indent=2) + '\n')
            raise RuntimeError(result.stderr)

    for slots in (12, 24):
        folder = output / str(slots)
        folder.mkdir()
        for p in sorted((SOURCE / 'import').glob('*.h')):
            receipt['inputs'][str(p.relative_to(UPSTREAM))] = sha(p)
            text = p.read_text()
            if p.name == 'sd_native_look.h' and slots == 24:
                text = replace(text, '#define R5_LOOK_SLOTS 12u', '#define R5_LOOK_SLOTS 24u')
            (folder / p.name).write_text(text)
        gamma = SOURCE / 'gamma/native_gamma.h'
        receipt['inputs'][str(gamma.relative_to(UPSTREAM))] = sha(gamma)
        (folder / gamma.name).write_bytes(gamma.read_bytes())
        for name, transform in (('r5_stage410_codec.c', codec24), ('r5_filter_selection423.c', selection24)):
            source = SOURCE / 'import' / name
            receipt['inputs'][str(source.relative_to(UPSTREAM))] = sha(source)
            text = source.read_text()
            if slots == 24:
                text = transform(text)
            (folder / ('codec.c' if 'codec' in name else 'selection.c')).write_text(text)
        (folder / 'selection_wrapper.c').write_text(WRAPPER)
        (folder / 'layout.c').write_bytes((HERE / 'layout.c').read_bytes())
        command(['clang', '-shared', '-fPIC', '-O1', '-fno-builtin', '-Wall', '-Wextra', '-Werror',
                 '-Wno-misleading-indentation', '-I', str(folder), str(folder / 'codec.c'),
                 str(folder / 'selection_wrapper.c'), str(folder / 'layout.c'), '-o', str(folder / 'prototype.dylib')])
        for target in ('arm-none-eabi', 'aarch64-none-elf'):
            args = ['clang', '--target=' + target, '-ffreestanding', '-fno-builtin', '-O1', '-Wall',
                    '-Wextra', '-Werror', '-I', str(folder), '-c', str(folder / 'layout.c'),
                    '-o', str(folder / (target + '.o'))]
            if target == 'arm-none-eabi':
                args[2:2] = ['-mthumb', '-march=armv7-a', '-mfloat-abi=soft']
            command(args)
    for p in sorted(output.rglob('*')):
        if p.is_file():
            receipt['outputs'][str(p.relative_to(output))] = sha(p)
    receipt['prototype_sources'] = {p.name: sha(p) for p in (HERE / 'prepare.py', HERE / 'layout.c')}
    (output / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.output.resolve())
    print(json.dumps({'output': str(args.output), 'commands': len(result['commands']),
                      'upstream_files_verified': result['upstream_files_verified'], 'firmware_generated': False}))
