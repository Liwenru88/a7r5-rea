"""实际启动器逆补丁在照片标记组合下的宿主验证，不执行原AP或ARM。"""
import hashlib
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys

import pytest

FEATURE = Path(__file__).resolve().parents[1]
ROOT = FEATURE.parents[1]
PACKAGING = FEATURE / 'experiments/packaging406'
LOADER = PACKAGING / 'loader'
NATIVE = FEATURE / 'native'
sys.path.insert(0, str(PACKAGING))
from candidate_preflight import AP_SHA, compose, read_cpio


def function(text, signature):
    start = text.index(signature)
    at = text.index('{', start)
    end, depth = at + 1, 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


def array(raw):
    return '{' + ','.join(str(value) for value in raw) + '}'


PREFIX = r'''
#include "manifest_types.h"
#include "af_sha256.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define COUNT(a) (sizeof(a)/sizeof((a)[0]))
static unsigned file_calls,unmap_calls;
static int same(const void *a,const void *b,size_t n){return !memcmp(a,b,n);}
static void bytes(void *target,const void *source,size_t n){memcpy(target,source,n);}
/* 只隔离本地文件映射：完整文件及SHA均由真实生产摘要函数核对。 */
static void *file_map(const BootFile *file,int writable){
 assert(writable==1);++file_calls;
 FILE *stream=fopen(file->path,"rb");assert(stream);
 unsigned char *p=malloc(file->bytes);assert(p);
 assert(fread(p,1,file->bytes,stream)==file->bytes);
 assert(fgetc(stream)==EOF && !ferror(stream));assert(!fclose(stream));
 uint8_t actual[32];assert(!af_sha256(p,file->bytes,actual));
 assert(same(actual,file->sha,32));return p;
}
static int munmap(void *p,size_t n){assert(p && n==97368304);++unmap_calls;free(p);return 0;}
'''

MAIN = r'''
int main(int argc,char **argv){
 assert(argc==4 && strlen(argv[2])==64);boot_ap.path=argv[1];
 for(unsigned i=0;i<32;++i){unsigned value=0;assert(sscanf(argv[2]+2*i,"%2x",&value)==1);boot_ap.sha[i]=(uint8_t)value;}
 int expected=atoi(argv[3]);assert(expected==0 || expected==1);
 assert(canonical()==expected);assert(file_calls==1 && unmap_calls==1);return 0;
}
'''


@pytest.fixture(scope='module')
def canonical_marker_candidates(tmp_path_factory):
    folder = tmp_path_factory.mktemp('marker-bootstrap')
    source = ROOT / 'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio'
    original = read_cpio(source, {'usr/lib/appFw.so'})['usr/lib/appFw.so']
    assert len(original) == 97368304 and hashlib.sha256(original).hexdigest() == AP_SHA
    path = ROOT / 'a7r5-firmware-features/aspect-guide406-update/ap_patch.py'
    spec = importlib.util.spec_from_file_location('marker_bootstrap_ap_patch', path)
    aspect = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(aspect)
    _, report = aspect.build(original)
    marker = [row for row in report['patches'] if row['offset'] not in (0x60, 0x68)]
    assert len(marker) == 35

    # 本测试不运行垫片，只需精确保持其既有7窗所有权与原像。
    # 两个不同填充值代表固定396B／400B启动体，其他窗口为实际登记／extent。
    updates = [
        (0x500fc70, bytes([0x21]) * 396),
        (0x17feac0, bytes.fromhex('6c44e014')),
        (0x500fdfc, bytes([0x22]) * 400),
        (0x5010388, struct.pack('<Q', 0x500fdfc)),
        (0x10c68, struct.pack('<Q', 0x500fdfc)),
        (0x60, struct.pack('<Q', 0x500ff8c)),
        (0x68, struct.pack('<Q', 0x500ff8c)),
    ]
    assert original[0x500fc70:0x500ff8c] == bytes(796)
    assert original[0x17feac0:0x17feac4] == bytes.fromhex('fd7bbaa9')
    assert original[0x5010388:0x5010390] == original[0x10c68:0x10c70] == struct.pack('<Q', 0x16fbfc0)
    assert original[0x60:0x68] == original[0x68:0x70] == struct.pack('<Q', 0x500fc10)
    bootstrap = [dict(offset=at, before=original[at:at+len(data)].hex(), after=data.hex())
                 for at, data in updates]
    combined = marker + bootstrap
    assert len(combined) == 42
    legacy = compose(original, AP_SHA, bootstrap)
    candidate = compose(original, AP_SHA, combined)
    source_text = (LOADER / 'af_bootstrap406.c').read_text()
    canonical = function(source_text, 'static int canonical(')
    binaries = {}
    for name, patches in (('legacy', bootstrap), ('combined', combined)):
        declarations = [
            'static BootFile boot_ap={0,97368304,{0}};',
            'static const uint8_t boot_original_sha[32]=' + array(bytes.fromhex(AP_SHA)) + ';',
        ]
        entries = []
        for index, row in enumerate(patches):
            before, after = bytes.fromhex(row['before']), bytes.fromhex(row['after'])
            declarations += [f'static const uint8_t before_{index}[]=' + array(before) + ';',
                             f'static const uint8_t after_{index}[]=' + array(after) + ';']
            entries.append('{%d,%d,before_%d,after_%d}' % (row['offset'], len(before), index, index))
        declarations.append('static const BootPatch boot_patches[]={' + ','.join(entries) + '};')
        c_file = folder / (name + '.c')
        binary = folder / name
        c_file.write_text(PREFIX + '\n'.join(declarations) + '\n' + canonical + MAIN)
        result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                                 '-I' + str(LOADER), '-I' + str(NATIVE), str(c_file),
                                 str(NATIVE / 'af_sha256.c'), '-o', str(binary)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        binaries[name] = binary

    candidates = {}
    for name, raw in (('legacy', legacy), ('combined', candidate)):
        path = folder / (name + '.ap')
        path.write_bytes(raw)
        candidates[name] = (path, hashlib.sha256(raw).hexdigest())
    for name, offset in (('window-corruption', 0x500fc10), ('outside-corruption', 0x1000)):
        if name == 'outside-corruption':
            assert all(not row['offset'] <= offset < row['offset'] + len(bytes.fromhex(row['after']))
                       for row in combined)
        altered = bytearray(candidate)
        altered[offset] ^= 1
        path = folder / (name + '.ap')
        path.write_bytes(altered)
        candidates[name] = (path, hashlib.sha256(altered).hexdigest())
    return binaries, candidates


@pytest.mark.parametrize('binary,candidate,expected', [
    ('combined', 'combined', 1),
    ('legacy', 'combined', 0),
    ('combined', 'window-corruption', 0),
    ('combined', 'outside-corruption', 0),
    ('legacy', 'legacy', 1),
], ids=['42-window-accepted', 'missing-marker-inverse-rejected', 'declared-window-corruption-rejected',
        'whole-original-hash-enforced', 'legacy-7-window-accepted'])
def test_production_canonical_reverses_full_original_ap(canonical_marker_candidates, binary, candidate, expected):
    binaries, candidates = canonical_marker_candidates
    path, wanted = candidates[candidate]
    result = subprocess.run([str(binaries[binary]), str(path), wanted, str(expected)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
