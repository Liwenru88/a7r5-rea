"""直接执行生产映射解析与保护查询，覆盖真实机身规模；不连接设备或模拟ARM。"""
import ctypes
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

FEATURE=Path(__file__).resolve().parents[1]
ROOT=FEATURE.parents[1]
SOURCE=FEATURE/'experiments/packaging406/loader/af_bootstrap406.c'


def function(text,signature):
    start=text.index(signature);begin=text.index('{',start);end=begin+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]+'\n'


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    directory=tmp_path_factory.mktemp('loader-maps');source=SOURCE.read_text()
    declarations=re.search(r'typedef struct \{uintptr_t lo,hi;int flags;\} Region;',source).group()
    declarations+='\n'+re.search(r'static Region regions\[[^]]+\];static size_t region_count;',source).group()
    prefix=r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#define COUNT(a) (sizeof(a)/sizeof((a)[0]))
static const char *fixture;
static int chunk,read_fail_after,read_calls,close_failure;
static int fixture_open(const char *name,int flags){
 if(strcmp(name,"/proc/self/maps") || flags!=(O_RDONLY|O_CLOEXEC))return -1;
 return open(fixture,O_RDONLY);
}
static ssize_t fixture_read(int fd,void *out,size_t bytes){
 if(read_fail_after>=0 && read_calls++>=read_fail_after){errno=EIO;return -1;}
 if(chunk>0 && bytes>(size_t)chunk)bytes=(size_t)chunk;
 return read(fd,out,bytes);
}
static int fixture_close(int fd){int result=close(fd);return close_failure?-1:result;}
#define open fixture_open
#define read fixture_read
#define close fixture_close
'''
    suffix=r'''
int check(const char *path,int chunk_size,int fail_after,int close_fail){
 fixture=path;chunk=chunk_size;read_fail_after=fail_after;read_calls=0;close_failure=close_fail;
 return maps();
}
size_t count(void){return region_count;}
size_t limit(void){return COUNT(regions);}
int permission(uintptr_t at,size_t bytes){return protection(at,bytes);}
'''
    path=directory/'maps.c';path.write_text(prefix+declarations+'\n'+function(source,'static int maps(void)')+function(source,'static int protection(uintptr_t at,size_t n)')+suffix)
    library=directory/'maps.dylib'
    command=[shutil.which('clang'),'-dynamiclib' if sys.platform=='darwin' else '-shared','-fPIC','-std=c11','-D_GNU_SOURCE','-O2','-Wall','-Wextra','-Werror',str(path),'-o',str(library)]
    run=subprocess.run(command,capture_output=True,text=True);assert run.returncode==0,run.stderr
    result=ctypes.CDLL(str(library));result.check.argtypes=[ctypes.c_char_p,ctypes.c_int,ctypes.c_int,ctypes.c_int]
    result.count.restype=result.limit.restype=ctypes.c_size_t
    result.permission.argtypes=[ctypes.c_size_t,ctypes.c_size_t]
    return result


def rows(count):
    return ''.join(f'{0x40000000+0x2000*i:012x}-{0x40001000+0x2000*i:012x} r-xp 00000000 00:00 0 /library-{i}\n' for i in range(count))


@pytest.mark.parametrize('fragment',[0,7])
def test_current_device_scale_and_permission_queries(api,tmp_path,fragment):
    path=tmp_path/'maps';path.write_text(rows(1090))
    assert api.check(str(path).encode(),fragment,-1,0)==1
    assert api.count()==1090
    assert api.permission(0x40000000+1089*0x2000,16)==5
    assert api.permission(0x40000ff8,16)==-1
    assert api.permission(0x40000000,0)==-1


def test_real_recorded_device_maps_without_status_trailer(api,tmp_path):
    receipt=ROOT/'.local/incident409-20261101/app-runtime.json'
    if not receipt.exists():pytest.skip('未提供该机身只读映射回执')
    raw=json.loads(receipt.read_text())['stdout']
    records=[line for line in raw.splitlines() if re.match(r'^[0-9a-f]+-[0-9a-f]+ ',line)]
    assert len(records)==1090
    path=tmp_path/'actual-maps';path.write_text('\n'.join(records)+'\n')
    assert api.check(str(path).encode(),113,-1,0)==1
    assert api.count()==len(records)


@pytest.mark.parametrize('fault',['capacity','line','total','overlap','trailing','malformed','read','close'])
def test_failure_invalidates_snapshot_and_cannot_authorize_a_prefix(api,tmp_path,fault):
    limit=api.limit();assert limit<=4096
    text=rows(16);chunk=0;read_fail=-1;close_fail=0
    if fault=='capacity':text=rows(limit+1)
    elif fault=='line':text+='x'*512+'\n'
    elif fault=='total':text=''.join(line[:-1]+'x'*180+'\n' for line in rows(limit).splitlines(keepends=True));assert len(text)>262144
    elif fault=='overlap':text+=rows(1)
    elif fault=='trailing':text+='unfinished'
    elif fault=='malformed':text+='not-a-mapping\n'
    elif fault=='read':chunk=64;read_fail=8
    else:close_fail=1
    good=tmp_path/'good';good.write_text(rows(16));assert api.check(str(good).encode(),0,-1,0)==1
    path=tmp_path/'bad';path.write_text(text)
    assert api.check(str(path).encode(),chunk,read_fail,close_fail)==0
    assert api.count()==0
    assert api.permission(0x40000000,4)==-1


def test_exact_capacity_remains_bounded(api,tmp_path):
    limit=api.limit();assert 1090<=limit<=4096
    path=tmp_path/'limit';path.write_text(rows(limit))
    assert api.check(str(path).encode(),0,-1,0)==1
    assert api.count()==limit


@pytest.mark.parametrize('boundary',['continuous','gap','writable','no_execute'])
def test_ap_code_range_can_span_split_vmas_but_never_a_hole_or_permission_change(api,tmp_path,boundary):
    # 原观察挂钩的mprotect/COW会把同一AP的RX映射切开；区间身份不能依赖VMA数量。
    start=0x7f00000000
    middle=start+0x1000
    mode={'continuous':'r-xp','gap':'r-xp','writable':'rwxp','no_execute':'r--p'}[boundary]
    second=middle+(0x1000 if boundary=='gap' else 0)
    path=tmp_path/'split-ap-maps'
    path.write_text(f'{start:x}-{middle:x} r-xp 00000000 00:01 649 /usr/lib/appFw.so\n'
                    f'{second:x}-{second+0x1000:x} {mode} 00001000 00:01 649 /usr/lib/appFw.so\n'
                    f'{second+0x1000:x}-{second+0x3000:x} r-xp 00002000 00:01 649 /usr/lib/appFw.so\n')
    assert api.check(str(path).encode(),0,-1,0)==1
    assert api.permission(start+0x80,0x3000)==(5 if boundary=='continuous' else -1)
