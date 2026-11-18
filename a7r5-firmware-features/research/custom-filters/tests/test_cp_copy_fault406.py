"""实际目标C控制流的宿主地址适配；故障后公开getter不得授予输入资格。"""
from pathlib import Path
import subprocess

import pytest


NATIVE = Path(__file__).resolve().parents[1] / "native"
PREFIX = r'''
#include <assert.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
static unsigned char test_native[0xe70],test_destination[0xe70],test_copy_a[0xe70];
static unsigned copies;
static int inject_fault;
static void test_copy(void *,const void *,size_t);
'''
SUFFIX = r'''
static void test_copy(void *dst,const void *src,size_t bytes){
    AfCpInput406Token token;
    assert(bytes==AF_CP_INPUT406_SNAPSHOT_BYTES);
    assert(af_cp_input406_read(&input_state,AF_CP_INPUT406_SNAPSHOT,&token)==AF_BUSY);
    ++copies;
    if(inject_fault)__atomic_store_n(&fault,1,__ATOMIC_RELAXED);
    memcpy(dst,src,bytes);
}
static void closed(uint32_t source){
    AfCpInput406Token token,before;memset(&token,0xa5,sizeof token);before=token;
    assert(af_cp_override406_read_input(source,&token)==AF_IO);
    assert(!memcmp(&token,&before,sizeof token));
}
int main(int argc,char **argv){
    assert(argc==2);int mode=atoi(argv[1]);
    AfPreset native={.base=0},selected={.base=18,.params={-3,4,-5,2,6,7,3,8}};
    native.params[6]=3;unsigned char marker=0;AfCpInput406Token token;
    assert(!af_cp406_write_state(&native,test_native,AF_CP_INPUT406_SNAPSHOT_BYTES,&marker));
    assert(!af_cp_override406_publish_locked(&active,11,7,&selected,&marker));
    inject_fault=mode==0;
    af_cp_override406_snapshot_copy_target(test_destination,test_native,AF_CP_INPUT406_SNAPSHOT_BYTES);
    /* 原copy只执行一次；故障检查不能通过重复原copy实现回滚。 */
    assert(copies==1);
    if(mode==0){
        assert(__atomic_load_n(&fault,__ATOMIC_RELAXED)==1);
        assert(af_cp_input406_read(&input_state,AF_CP_INPUT406_SNAPSHOT,&token)==AF_EMPTY);
        closed(AF_CP_INPUT406_SNAPSHOT);
    }else{
        assert(!af_cp_override406_read_input(AF_CP_INPUT406_SNAPSHOT,&token));
        assert(token.version==11&&token.flags==AF_CP_INPUT406_USER_VERSION);
        assert(!memcmp(&token.actual,&selected,sizeof selected));
        /* 模拟原E70复制已完成，保留一份真实派生token以检查全部公开源都受fault约束。 */
        AfCpInput406Write write;
        assert(!af_cp_input406_copy_begin(&input_state,AF_CP_INPUT406_COPY_A,AF_CP_INPUT406_SNAPSHOT,
            AF_CP_INPUT406_COPY_BYTES,37,&write));
        memcpy(test_copy_a,test_destination,sizeof test_copy_a);test_copy_a[AF_CP_INPUT406_VD_OFFSET]=37;
        assert(!af_cp_input406_copy_end(&input_state,&write,test_copy_a,sizeof test_copy_a));
        assert(!af_cp_override406_read_input(AF_CP_INPUT406_COPY_A,&token)&&token.version==11);
        /* 发布后的原始记录可以是历史记录，但不能绕过公开读取的全局故障门禁。 */
        __atomic_store_n(&fault,1,__ATOMIC_RELAXED);
        assert(!af_cp_input406_read(&input_state,AF_CP_INPUT406_SNAPSHOT,&token));
        assert(token.flags==AF_CP_INPUT406_USER_VERSION);
        closed(AF_CP_INPUT406_SNAPSHOT);closed(AF_CP_INPUT406_COPY_A);
    }
    return 0;
}
'''


@pytest.fixture(scope="module")
def executable(tmp_path_factory):
    folder = tmp_path_factory.mktemp("cp-copy-fault406")
    body = (NATIVE / "af_cp_override406.c").read_text()
    # 只替换目标地址和ARM专用屏障，保留实际生产分支、故障处理及getter实现。
    replacements = {
        "#if defined(__arm__) && defined(AF_SNAPSHOT_OVERLAY406)":
            "#if defined(AF_SNAPSHOT_OVERLAY406)",
        '__asm__ volatile("dmb sy" ::: "memory");':
            "__atomic_thread_fence(__ATOMIC_SEQ_CST);",
        "(AfCpSnapshotCopy406)(uintptr_t)0x5f51bcu": "test_copy",
        "(const void *)(uintptr_t)0x157aa10u": "test_native",
        "(uintptr_t)dst!=AF_CP_INPUT406_SNAPSHOT": "dst!=test_destination",
        "(uintptr_t)source!=0x157aa10u": "source!=test_native",
        "(uint32_t)(uintptr_t)dst": "AF_CP_INPUT406_SNAPSHOT",
    }
    for old, new in replacements.items():
        assert old in body, old
        body = body.replace(old, new)
    source, binary = folder / "copy_fault.c", folder / "copy_fault"
    source.write_text(PREFIX + body + SUFFIX)
    result = subprocess.run(
        ["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
         "-DAF_CP_CAPTURE_INPUT406=1", "-DAF_CP_CARVE_BRANCH406=1", "-DAF_SNAPSHOT_OVERLAY406=1",
         "-DAF_CP_SNAPSHOT_ENTRY406=0xbefa29u", "-I" + str(NATIVE), str(source),
         *[str(NATIVE / n) for n in ("af_cp_input406.c", "af_cp406_state.c", "af_slots.c")],
         "-o", str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("mode", [0, 1], ids=["fault-during-copy", "fault-after-publication"])
def test_public_input_getter_closes_faulted_copy(executable, mode):
    result = subprocess.run([str(executable), str(mode)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
