"""管理请求真实C契约；后端耐久回执在此为显式测试服务，不是机内存储。"""
from pathlib import Path
import shutil
import subprocess

import pytest

NATIVE=Path(__file__).resolve().parents[1]/'native'
HARNESS=r'''
#include "af_ap_manage.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>

static AfPreset preset(void) {
    AfPreset p={0};p.params[6]=3;return p;
}
static AfApManageRequest save_request(unsigned slot) {
    AfApManageRequest q={0};q.op=AF_MANAGE_SAVE;q.source_slot=q.target_slot=slot;return q;
}
static void case_save(void) {
    AfCatalog c,before;AfApManage m;AfApManageJob job;AfSave s;
    AfPreset p=preset();AfApManageRequest q=save_request(7);
    af_catalog_init(&c);af_ap_manage_init(&m);assert(af_install(&c,7,&p,0)==AF_OK);
    assert(af_edit(&c,7,0,3)==AF_OK);before=c;
    assert(af_ap_manage_submit(&m,&c,&q)==AF_OK);
    assert(!memcmp(&c,&before,sizeof(c)));assert(m.phase==AF_MANAGE_QUEUED);
    assert(af_ap_manage_submit(&m,&c,&q)==AF_BUSY);
    q.source_slot=20;assert(m.job.request.source_slot==7);
    assert(af_ap_manage_take(&m,&job)==AF_OK);assert(job.source.working.params[0]==3);
    assert(af_edit(&c,7,0,4)==AF_OK);assert(af_ap_manage_commit_begin(&m,&c,job.ticket)==AF_STALE);
    AfApManageReceipt r={job.ticket,0,AF_STALE,0,0};assert(af_ap_manage_finish(&m,&c,&r)==AF_OK);
    q=save_request(7);assert(af_ap_manage_submit(&m,&c,&q)==AF_OK);
    assert(af_ap_manage_take(&m,&job)==AF_OK);assert(af_ap_manage_commit_begin(&m,&c,job.ticket)==AF_OK);
    assert(af_ap_manage_cancel(&m,job.ticket)==AF_BUSY);
    r=(AfApManageReceipt){job.ticket,c.slots[6].saved_revision+1,AF_OK,0,0};
    assert(af_ap_manage_finish(&m,&c,&r)==AF_INVALID);
    r.durable=1;assert(af_ap_manage_finish(&m,&c,&r)==AF_STALE);
    /* 显式目录提交夹具：这里只验证管理层不制造/覆盖保存快照。 */
    assert(af_begin_save(&c,7,&s)==AF_OK);assert(af_edit(&c,7,0,5)==AF_OK);
    assert(af_finish_save(&c,&s,1)==AF_OK);assert(af_ap_manage_finish(&m,&c,&r)==AF_OK);
    assert(m.phase==AF_MANAGE_DONE && c.slots[6].saved.params[0]==4);
    assert(c.slots[6].working.params[0]==5 && af_dirty(&c,7)==1);
    assert(af_ap_manage_finish(&m,&c,&r)==AF_STALE);
}
static void case_copy_cancel(void) {
    AfCatalog c,before;AfApManage m;AfApManageJob job;AfPreset p=preset();
    AfApManageRequest q={0};q.op=AF_MANAGE_COPY;q.source_slot=7;q.target_slot=8;
    q.name_bytes=4;memcpy(q.name,"Copy",4);
    af_catalog_init(&c);af_ap_manage_init(&m);assert(af_install(&c,7,&p,0)==AF_OK);
    assert(af_install(&c,8,&p,0)==AF_OK);before=c;
    assert(af_ap_manage_submit(&m,&c,&q)==AF_EXISTS);assert(!memcmp(&before,&c,sizeof(c)));
    q.overwrite=1;assert(af_ap_manage_submit(&m,&c,&q)==AF_OK);
    uint64_t first=m.job.ticket;assert(af_ap_manage_cancel(&m,first)==AF_OK);
    assert(m.phase==AF_MANAGE_CANCELLED && af_ap_manage_take(&m,&job)==AF_EMPTY);
    assert(af_ap_manage_cancel(&m,first)==AF_OK);assert(!memcmp(&before,&c,sizeof(c)));
    assert(af_ap_manage_submit(&m,&c,&q)==AF_OK);assert(m.job.ticket>first);
    assert(af_ap_manage_take(&m,&job)==AF_OK);
    assert(af_ap_manage_progress(&m,job.ticket,2,10)==AF_OK);
    assert(af_ap_manage_progress(&m,job.ticket,1,10)==AF_INVALID);
    assert(af_ap_manage_progress(&m,job.ticket,3,11)==AF_INVALID);
    assert(af_edit(&c,8,0,2)==AF_OK);assert(af_ap_manage_commit_begin(&m,&c,job.ticket)==AF_STALE);
    assert(af_ap_manage_cancel(&m,first)==AF_STALE);assert(af_ap_manage_cancel(&m,job.ticket)==AF_OK);
    assert(af_ap_manage_progress(&m,job.ticket,3,10)==AF_MANAGE_CANCEL);
    assert(af_ap_manage_commit_begin(&m,&c,job.ticket)==AF_MANAGE_CANCEL);
    AfApManageReceipt r={job.ticket,0,AF_MANAGE_CANCEL,0,0};
    assert(af_ap_manage_finish(&m,&c,&r)==AF_OK);assert(m.phase==AF_MANAGE_CANCELLED);
    assert(af_ap_manage_submit(&m,&c,&q)==AF_OK);assert(af_ap_manage_take(&m,&job)==AF_OK);
    assert(af_ap_manage_commit_begin(&m,&c,job.ticket)==AF_OK);
    r=(AfApManageReceipt){job.ticket,0,AF_IO,0,1};assert(af_ap_manage_finish(&m,&c,&r)==AF_OK);
    assert(m.phase==AF_MANAGE_UNCERTAIN && af_ap_manage_submit(&m,&c,&q)==AF_BUSY);
    assert(af_ap_manage_recovered(&m)==AF_OK);assert(af_ap_manage_submit(&m,&c,&q)==AF_OK);
}
static void case_create_import(void) {
    AfCatalog c,before;AfApManage m;AfApManageJob job;
    AfApManageRequest q={0};q.op=AF_MANAGE_CREATE;q.target_slot=7;q.initial=preset();
    q.name_bytes=6;memcpy(q.name,"Manual",6);af_catalog_init(&c);af_ap_manage_init(&m);before=c;
    assert(af_ap_manage_submit(&m,&c,&q)==AF_OK);assert(!memcmp(&before,&c,sizeof(c)));
    assert(af_ap_manage_take(&m,&job)==AF_OK);assert(af_ap_manage_commit_begin(&m,&c,job.ticket)==AF_OK);
    assert(af_install(&c,7,&q.initial,0)==AF_OK);
    AfApManageReceipt r={job.ticket,c.slots[6].saved_revision,AF_OK,1,0};
    assert(af_ap_manage_finish(&m,&c,&r)==AF_OK);
    q.op=AF_MANAGE_IMPORT;q.overwrite=1;
    assert(af_ap_manage_submit(&m,&c,&q)==AF_INVALID);
    q.media_generation=4;q.media_index=64;assert(af_ap_manage_submit(&m,&c,&q)==AF_INVALID);
    q.media_index=63;assert(af_ap_manage_submit(&m,&c,&q)==AF_OK);
    assert(af_ap_manage_take(&m,&job)==AF_OK);assert(job.request.media_generation==4);
    assert(af_ap_manage_commit_begin(&m,&c,job.ticket)==AF_OK);
    /* IMPORT现在也接收完整纯参数文件；它表示保存成功，不是LUT成像回执。 */
    assert(af_install(&c,7,&q.initial,1)==AF_OK);r.ticket=job.ticket;r.generation=c.slots[6].saved_revision;
    assert(af_ap_manage_finish(&m,&c,&r)==AF_OK);
    assert(af_ap_manage_submit(&m,&c,&q)==AF_OK&&af_ap_manage_take(&m,&job)==AF_OK);
    assert(af_ap_manage_commit_begin(&m,&c,job.ticket)==AF_OK);r.ticket=job.ticket;
    AfPreset lut=q.initial;lut.kind=1;lut.payload_sha256[0]=1;lut.lut_sha256[0]=2;
    assert(af_install(&c,7,&lut,1)==AF_OK);r.generation=c.slots[6].saved_revision;
    assert(af_ap_manage_finish(&m,&c,&r)==AF_OK);
    q=save_request(0);assert(af_ap_manage_submit(&m,&c,&q)==AF_INVALID);
    q=save_request(21);assert(af_ap_manage_submit(&m,&c,&q)==AF_INVALID);
    assert(af_ap_manage_submit(&m,&c,&m.job.request)==AF_INVALID);
    m.next_ticket=UINT64_MAX;q=save_request(7);assert(af_ap_manage_submit(&m,&c,&q)==AF_EXHAUSTED);
}
static void case_legacy_overlay(void){
 AfCatalog c,before;AfApManage m;AfApManageJob job;AfPreset p=preset();
 af_catalog_init(&c);af_ap_manage_init(&m);before=c;
 for(unsigned op=AF_MANAGE_COPY;op<=AF_MANAGE_CREATE;++op){
  AfApManageRequest q={0};q.op=op;q.target_slot=1;q.initial=p;q.name_bytes=1;q.name[0]='N';
  if(op==AF_MANAGE_COPY)q.source_slot=7;
  if(op==AF_MANAGE_IMPORT)q.media_generation=1;
  assert(af_ap_manage_submit(&m,&c,&q)==AF_INVALID&&!memcmp(&c,&before,sizeof c));
 }
 AfApManageRequest q={0};q.op=AF_MANAGE_CREATE;q.target_slot=1;q.overwrite=1;q.initial=p;q.name_bytes=1;q.name[0]='N';
 assert(af_ap_manage_submit(&m,&c,&q)==AF_OK&&!c.slots[0].present);
 assert(af_ap_manage_take(&m,&job)==AF_OK&&af_ap_manage_commit_begin(&m,&c,job.ticket)==AF_OK);
 assert(af_install(&c,1,&p,0)==AF_OK);AfApManageReceipt receipt={job.ticket,c.slots[0].saved_revision,AF_OK,1,0};
 assert(af_ap_manage_finish(&m,&c,&receipt)==AF_OK);
 q=(AfApManageRequest){0};q.op=AF_MANAGE_RENAME;q.source_slot=q.target_slot=1;q.name_bytes=1;q.name[0]='R';
 assert(af_ap_manage_submit(&m,&c,&q)==AF_OK);assert(af_ap_manage_cancel(&m,m.job.ticket)==AF_OK);
 q=(AfApManageRequest){0};q.op=AF_MANAGE_CLEAR;q.target_slot=1;q.overwrite=1;
 assert(af_ap_manage_submit(&m,&c,&q)==AF_OK);assert(af_ap_manage_cancel(&m,m.job.ticket)==AF_OK);
 q.target_slot=6;assert(af_ap_manage_submit(&m,&c,&q)==AF_EMPTY&&!c.slots[5].present);
 q=save_request(6);assert(af_ap_manage_submit(&m,&c,&q)==AF_EMPTY&&!c.slots[5].present);
}
int main(int argc,char **argv) {
    assert(argc==2);switch(atoi(argv[1])) {case 0:case_save();break;case 1:case_copy_cancel();break;
    case 2:case_create_import();break;case 3:case_legacy_overlay();break;default:assert(0);}return 0;
}
'''


@pytest.fixture(scope='module')
def manager_program(tmp_path_factory):
    directory=tmp_path_factory.mktemp('ap-manage-contract')
    source=directory/'contract.c';source.write_text(HARNESS)
    output=directory/'contract'
    result=subprocess.run([shutil.which('clang'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-I'+str(NATIVE),str(source),str(NATIVE/'af_ap_manage.c'),str(NATIVE/'af_slots.c'),
        '-o',str(output)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return output


@pytest.mark.parametrize('case',[0,1,2,3],ids=['save-snapshot-receipt','copy-cancel-uncertain','create-import-protection','original-overlay-explicit-only'])
def test_single_owner_management_contract(manager_program,case):
    result=subprocess.run([str(manager_program),str(case)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
