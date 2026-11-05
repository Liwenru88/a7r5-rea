"""固定输入版本伴随的真实C行为与32位原子读；不执行相机或目标指令。"""
from pathlib import Path
import subprocess

import pytest


NATIVE = Path(__file__).resolve().parents[1] / "native"
DRIVER = r'''
#include "af_cp_input406.h"
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdlib.h>
#include <string.h>
static AfPreset pure(unsigned n){
    AfPreset p={.base=(uint8_t)(17+(n&1)),.params={-1,2,-3,4,-5,6,3,8}};
    p.params[0]=(int8_t)((int)(n%19)-9);return p;
}
static void actual(const AfPreset *p,unsigned char *buffer){
    unsigned char marker=0;assert(!af_cp406_write_state(p,buffer,AF_CP_INPUT406_SNAPSHOT_BYTES,&marker)&&marker==1);
}
static void vd(unsigned char *buffer,uint32_t v){for(unsigned i=0;i<4;++i)buffer[AF_CP_INPUT406_VD_OFFSET+i]=(unsigned char)(v>>(8*i));}
static AfCpInput406Token read_token(AfCpInput406 *s,uint32_t source){
    AfCpInput406Token token;assert(!af_cp_input406_read(s,source,&token));return token;
}
static void publish(AfCpInput406 *s,uint64_t version,unsigned slot,unsigned mode,const AfPreset *p,unsigned char *buffer){
    AfCpInput406Write write;
    assert(!af_cp_input406_snapshot_begin(s,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_SNAPSHOT_BYTES,&write));
    actual(p,buffer);
    assert(!af_cp_input406_snapshot_end(s,&write,version,slot,mode,mode==AF_CP_OVERRIDE_NATIVE?0:p,
        buffer,AF_CP_INPUT406_SNAPSHOT_BYTES));
}
static void expect_unchanged_read(AfCpInput406 *s,uint32_t source,int status){
    AfCpInput406Token output,before;memset(&output,0xa5,sizeof output);before=output;
    assert(af_cp_input406_read(s,source,&output)==status&&!memcmp(&before,&output,sizeof output));
}
static int snapshots(void){
    AfCpInput406 s={0};unsigned char raw[AF_CP_INPUT406_COPY_BYTES];memset(raw,0x5a,sizeof raw);
    AfPreset p=pure(2);AfCpInput406Write first;
    assert(af_cp_input406_bytes()==sizeof s);
    expect_unchanged_read(&s,AF_CP_INPUT406_SNAPSHOT,AF_EMPTY);
    assert(!af_cp_input406_snapshot_begin(&s,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_SNAPSHOT_BYTES,&first));
    expect_unchanged_read(&s,AF_CP_INPUT406_SNAPSHOT,AF_BUSY);actual(&p,raw);
    unsigned char before[sizeof raw];memcpy(before,raw,sizeof raw);
    const uint64_t version=UINT64_C(0x12345678abcdef00);
    assert(!af_cp_input406_snapshot_end(&s,&first,version,7,AF_CP_OVERRIDE_USER,&p,raw,AF_CP_INPUT406_SNAPSHOT_BYTES));
    AfCpInput406Token token=read_token(&s,AF_CP_INPUT406_SNAPSHOT);
    assert(token.version==version&&token.slot==7&&token.mode==AF_CP_OVERRIDE_USER);
    assert(token.source==AF_CP_INPUT406_SNAPSHOT&&token.epoch==2&&token.origin_snapshot_epoch==2);
    assert(token.flags==AF_CP_INPUT406_USER_VERSION&&!token.native_vd);
    assert(!memcmp(&token.actual,&p,sizeof p)&&!memcmp(before,raw,sizeof raw));
    publish(&s,version+1,0,AF_CP_OVERRIDE_FACTORY_PENDING,&p,raw);
    token=read_token(&s,AF_CP_INPUT406_SNAPSHOT);assert(!token.flags&&!token.slot&&token.version==version+1);
    p=pure(7);publish(&s,version+2,0,AF_CP_OVERRIDE_NATIVE,&p,raw);
    token=read_token(&s,AF_CP_INPUT406_SNAPSHOT);
    assert(token.mode==AF_CP_OVERRIDE_NATIVE&&!token.flags&&!token.slot&&token.actual.base==18);
    assert(!memcmp(&token.actual,&p,sizeof p));
    AfCpInput406 fresh={0};publish(&fresh,0,0,AF_CP_OVERRIDE_NATIVE,&p,raw);
    token=read_token(&fresh,AF_CP_INPUT406_SNAPSHOT);assert(!token.version&&!token.flags);
    return 0;
}
static int copies(void){
    AfCpInput406 s={0};unsigned char raw[AF_CP_INPUT406_COPY_BYTES],destination[sizeof raw];
    memset(raw,0x5a,sizeof raw);AfPreset p=pure(3);AfCpInput406Write write;
    const uint64_t first=UINT64_C(0x100000009);publish(&s,first,7,AF_CP_OVERRIDE_USER,&p,raw);
    assert(!af_cp_input406_copy_begin(&s,AF_CP_INPUT406_COPY_A,AF_CP_INPUT406_SNAPSHOT,sizeof raw,0x3456,&write));
    expect_unchanged_read(&s,AF_CP_INPUT406_COPY_A,AF_BUSY);
    vd(raw,0x3456);memcpy(destination,raw,sizeof raw);
    assert(!af_cp_input406_copy_end(&s,&write,destination,sizeof destination));
    AfCpInput406Token token=read_token(&s,AF_CP_INPUT406_COPY_A);
    assert(token.version==first&&token.epoch==2&&token.origin_snapshot_epoch==2&&token.native_vd==0x3456);
    assert(token.flags==(AF_CP_INPUT406_USER_VERSION|AF_CP_INPUT406_VD_VALID));
    assert(!memcmp(&token.actual,&p,sizeof p));
    /* 同九字段、不同版本也必须通过真实源epoch拒绝旧copy，不能按同值推断身份。 */
    assert(!af_cp_input406_copy_begin(&s,AF_CP_INPUT406_COPY_B,AF_CP_INPUT406_SNAPSHOT,sizeof raw,0x3456,&write));
    memcpy(destination,raw,sizeof raw);publish(&s,first+1,8,AF_CP_OVERRIDE_USER,&p,raw);
    assert(af_cp_input406_copy_end(&s,&write,destination,sizeof destination)==AF_STALE);
    expect_unchanged_read(&s,AF_CP_INPUT406_COPY_B,AF_EMPTY);
    token=read_token(&s,AF_CP_INPUT406_COPY_A);assert(token.version==first&&token.origin_snapshot_epoch==2);
    assert(!af_cp_input406_copy_begin(&s,AF_CP_INPUT406_COPY_B,AF_CP_INPUT406_SNAPSHOT,sizeof raw,0x3456,&write));
    memcpy(destination,raw,sizeof raw);vd(destination,0x3457);
    assert(af_cp_input406_copy_end(&s,&write,destination,sizeof destination)==AF_STALE);
    expect_unchanged_read(&s,AF_CP_INPUT406_COPY_B,AF_EMPTY);
    assert(!af_cp_input406_copy_begin(&s,AF_CP_INPUT406_COPY_B,AF_CP_INPUT406_SNAPSHOT,sizeof raw,0,&write));
    memcpy(destination,raw,sizeof raw);vd(destination,0);destination[0xa44]^=1;
    assert(af_cp_input406_copy_end(&s,&write,destination,sizeof destination)==AF_STALE);
    assert(!af_cp_input406_copy_begin(&s,AF_CP_INPUT406_COPY_B,AF_CP_INPUT406_SNAPSHOT,sizeof raw,0,&write));
    memcpy(destination,raw,sizeof raw);vd(destination,0);
    assert(!af_cp_input406_copy_end(&s,&write,destination,sizeof destination));
    token=read_token(&s,AF_CP_INPUT406_COPY_B);
    assert(token.version==first+1&&token.slot==8&&token.origin_snapshot_epoch==4&&!token.native_vd);
    assert(token.flags&AF_CP_INPUT406_VD_VALID);
    /* 即使新snapshot仍用同一版本/参数，开始改写原源也使在途copy失去资格。 */
    assert(!af_cp_input406_copy_begin(&s,AF_CP_INPUT406_COPY_B,AF_CP_INPUT406_SNAPSHOT,sizeof raw,0,&write));
    AfCpInput406Write snapshot;
    assert(!af_cp_input406_snapshot_begin(&s,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_SNAPSHOT_BYTES,&snapshot));
    assert(af_cp_input406_copy_end(&s,&write,destination,sizeof destination)==AF_STALE);
    expect_unchanged_read(&s,AF_CP_INPUT406_COPY_B,AF_EMPTY);
    actual(&p,raw);
    assert(!af_cp_input406_snapshot_end(&s,&snapshot,first+1,8,AF_CP_OVERRIDE_USER,&p,raw,AF_CP_INPUT406_SNAPSHOT_BYTES));
    return 0;
}
static int rejected(void){
    AfCpInput406 s={0};unsigned char raw[AF_CP_INPUT406_COPY_BYTES];memset(raw,0x5a,sizeof raw);
    AfPreset p=pure(1);AfCpInput406Write output,before,old,current;
    publish(&s,3,7,AF_CP_OVERRIDE_USER,&p,raw);memset(&output,0xa5,sizeof output);before=output;
    assert(af_cp_input406_snapshot_begin(&s,AF_CP_INPUT406_SNAPSHOT,1,&output)==AF_INVALID);
    assert(!memcmp(&output,&before,sizeof output));expect_unchanged_read(&s,AF_CP_INPUT406_SNAPSHOT,AF_EMPTY);
    publish(&s,4,7,AF_CP_OVERRIDE_USER,&p,raw);
    assert(af_cp_input406_copy_begin(&s,AF_CP_INPUT406_COPY_A,0x1234,sizeof raw,1,&output)==AF_INVALID);
    assert(!memcmp(&output,&before,sizeof output));expect_unchanged_read(&s,AF_CP_INPUT406_COPY_A,AF_EMPTY);
    assert(read_token(&s,AF_CP_INPUT406_SNAPSHOT).version==4);
    assert(af_cp_input406_copy_begin(&s,0x1234,AF_CP_INPUT406_SNAPSHOT,sizeof raw,1,&output)==AF_INVALID);
    assert(read_token(&s,AF_CP_INPUT406_SNAPSHOT).version==4);
    assert(af_cp_input406_read(&s,AF_CP_INPUT406_SNAPSHOT,(AfCpInput406Token *)&s)==AF_INVALID);
    assert(af_cp_input406_snapshot_begin(&s,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_SNAPSHOT_BYTES,
        (AfCpInput406Write *)&s)==AF_INVALID);
    expect_unchanged_read(&s,AF_CP_INPUT406_SNAPSHOT,AF_EMPTY);
    assert(!af_cp_input406_snapshot_begin(&s,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_SNAPSHOT_BYTES,&old));
    AfPreset mismatch=p;mismatch.params[0]++;
    assert(af_cp_input406_snapshot_end(&s,&old,5,7,AF_CP_OVERRIDE_USER,&mismatch,raw,AF_CP_INPUT406_SNAPSHOT_BYTES)==AF_STALE);
    assert(!af_cp_input406_snapshot_begin(&s,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_SNAPSHOT_BYTES,&current));
    assert(af_cp_input406_snapshot_end(&s,&old,5,7,AF_CP_OVERRIDE_USER,&p,raw,AF_CP_INPUT406_SNAPSHOT_BYTES)==AF_STALE);
    expect_unchanged_read(&s,AF_CP_INPUT406_SNAPSHOT,AF_BUSY);
    assert(!af_cp_input406_snapshot_end(&s,&current,5,7,AF_CP_OVERRIDE_USER,&p,raw,AF_CP_INPUT406_SNAPSHOT_BYTES));
    assert(!af_cp_input406_snapshot_begin(&s,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_SNAPSHOT_BYTES,&current));
    assert(af_cp_input406_snapshot_end(&s,&current,4,7,AF_CP_OVERRIDE_USER,&p,raw,AF_CP_INPUT406_SNAPSHOT_BYTES)==AF_STALE);
    expect_unchanged_read(&s,AF_CP_INPUT406_SNAPSHOT,AF_EMPTY);
    assert(!af_cp_input406_snapshot_begin(&s,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_SNAPSHOT_BYTES,&current));
    AfPreset lut=p;lut.kind=1;lut.payload_sha256[0]=lut.lut_sha256[0]=1;
    assert(af_cp_input406_snapshot_end(&s,&current,6,7,AF_CP_OVERRIDE_USER,&lut,raw,AF_CP_INPUT406_SNAPSHOT_BYTES)==AF_INVALID);
    assert(!af_cp_input406_snapshot_begin(&s,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_SNAPSHOT_BYTES,&current));
    assert(af_cp_input406_snapshot_end(&s,&current,6,7,AF_CP_OVERRIDE_USER,&p,(const void *)&s,
        AF_CP_INPUT406_SNAPSHOT_BYTES)==AF_INVALID);
    expect_unchanged_read(&s,AF_CP_INPUT406_SNAPSHOT,AF_EMPTY);
    /* 最后可用偶数epoch可正常读，下一次Begin永久耗尽，不回卷或发布票据。 */
    AfCpInput406 edge={0};edge.records[0].sequence=UINT32_MAX-3u;
    publish(&edge,1,7,AF_CP_OVERRIDE_USER,&p,raw);
    assert(read_token(&edge,AF_CP_INPUT406_SNAPSHOT).epoch==UINT32_MAX-1u);
    assert(af_cp_input406_snapshot_begin(&edge,AF_CP_INPUT406_SNAPSHOT,AF_CP_INPUT406_SNAPSHOT_BYTES,&output)==AF_EXHAUSTED);
    assert(!memcmp(&output,&before,sizeof output));expect_unchanged_read(&edge,AF_CP_INPUT406_SNAPSHOT,AF_EXHAUSTED);
    assert(af_cp_input406_copy_begin(&edge,AF_CP_INPUT406_COPY_A,AF_CP_INPUT406_SNAPSHOT,sizeof raw,0,&output)==AF_EXHAUSTED);
    expect_unchanged_read(&edge,AF_CP_INPUT406_COPY_A,AF_EMPTY);
    assert(edge.records[0].sequence==UINT32_MAX);
    return 0;
}
static AfCpInput406 shared;
static unsigned done,started,attempted;
static void verify(const AfCpInput406Token *t){
    unsigned lo=(uint32_t)t->version,i=lo-0x80000000u;
    assert(i<5000&&(uint32_t)(t->version>>32)==i+3);
    AfPreset p=pure(i);assert(!memcmp(&t->actual,&p,sizeof p));
    assert(t->slot==7+(i&1)&&t->flags==AF_CP_INPUT406_USER_VERSION&&t->origin_snapshot_epoch==t->epoch);
}
static void *reader(void *unused){
    (void)unused;__atomic_store_n(&started,1,__ATOMIC_RELEASE);
    do{
        AfCpInput406Token token;int result=af_cp_input406_read(&shared,AF_CP_INPUT406_SNAPSHOT,&token);
        if(!result)verify(&token);else assert(result==AF_BUSY||result==AF_EMPTY);
        ++attempted;
    }while(!__atomic_load_n(&done,__ATOMIC_ACQUIRE));return 0;
}
static int concurrent(void){
    pthread_t thread;assert(!pthread_create(&thread,0,reader,0));
    while(!__atomic_load_n(&started,__ATOMIC_ACQUIRE))sched_yield();
    unsigned char raw[AF_CP_INPUT406_SNAPSHOT_BYTES];memset(raw,0,sizeof raw);
    for(unsigned i=0;i<5000;++i){
        AfPreset p=pure(i);uint64_t version=((uint64_t)(i+3)<<32)|(0x80000000u+i);
        publish(&shared,version,7+(i&1),AF_CP_OVERRIDE_USER,&p,raw);
    }
    __atomic_store_n(&done,1,__ATOMIC_RELEASE);assert(!pthread_join(thread,0)&&attempted);
    AfCpInput406Token token=read_token(&shared,AF_CP_INPUT406_SNAPSHOT);verify(&token);return 0;
}
int main(int argc,char **argv){
    assert(argc==2);
    switch(atoi(argv[1])){case 0:return snapshots();case 1:return copies();case 2:return rejected();case 3:return concurrent();}
    return 2;
}
'''


@pytest.fixture(scope="module")
def executable(tmp_path_factory):
    directory = tmp_path_factory.mktemp("cp-input406")
    source, binary = directory / "input.c", directory / "input"
    source.write_text(DRIVER)
    result = subprocess.run(
        ["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
         "-I" + str(NATIVE), str(source), *[str(NATIVE / n) for n in
         ("af_cp_input406.c", "af_cp406_state.c", "af_slots.c")], "-o", str(binary)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("scenario", [0, 1, 2, 3], ids=[
    "snapshot-modes", "copy-version-vd", "rejection-epoch", "atomic-reader-writer"])
def test_fixed_source_input_sidecar(executable, scenario):
    run = subprocess.run([str(executable), str(scenario)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


def test_thumb_input_sidecar_uses_only_lock_free_32_bit_atomics(tmp_path):
    target = tmp_path / "input.o"
    result = subprocess.run(
        ["clang", "--target=armv7a-none-eabi", "-mthumb", "-march=armv7-a", "-std=c11", "-Oz",
         "-ffreestanding", "-fno-builtin", "-Wall", "-Wextra", "-Werror", "-c",
         str(NATIVE / "af_cp_input406.c"), "-o", str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    symbols = subprocess.run(["nm", "-u", str(target)], capture_output=True, text=True)
    assert symbols.returncode == 0, symbols.stderr
    assert [line.split()[-1] for line in symbols.stdout.splitlines() if line.strip()] == ["af_validate"]
