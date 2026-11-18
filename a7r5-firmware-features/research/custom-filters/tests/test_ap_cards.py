"""宿主C契约；原函数仅为显式服务边界，不运行原AP或外设。"""
from pathlib import Path
import shutil
import subprocess
import pytest

HERE = Path(__file__).resolve().parents[1]
ROOT = next(p for p in HERE.parents if (p / 'a7r5-firmware-features').is_dir())
SHARED = ROOT / 'a7r5-firmware-features/custom-filters/native'

HARNESS = r'''
#include "af_ap_cards.c"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint32_t shown,language,parent_override=UINT32_MAX;
static uintptr_t trees[4]={1,2,3,4};
static uint8_t root_template[128],item_template[128],desc_template[192];
static unsigned collisions,registered_calls;
static const uint32_t *current(void) {return &shown;}
static const uint32_t *get_language(void) {return &language;}
static uint32_t get_parent(uint32_t menu) {return parent_override==UINT32_MAX?af_ap_cards_parent(menu):parent_override;}
static int contains(void *tree,const uint32_t *key) {
    return collisions==(unsigned)(uintptr_t)tree &&
           (*key==AF_CARDS_MENU_SLOT1 || *key==AF_CARDS_MENU_ROOT || *key==AF_CARDS_MENU_DESCRIPTOR);
}
static uint32_t read32(const void *p) {uint32_t v;memcpy(&v,p,4);return v;}
static uintptr_t readptr(const void *p) {uintptr_t v;memcpy(&v,p,sizeof(v));return v;}
static void append_rows(void *tree,const void *first,const void *end) {
    assert(tree==(void *)1 && (const uintptr_t *)end-(const uintptr_t *)first==8);
    const uintptr_t (*pairs)[2]=first;
    for(unsigned i=0;i<4;++i) {
        assert(pairs[i][0]==AF_CARDS_MENU_ROOT+i && pairs[i][1]==(uintptr_t)native.records[i]);
        assert(read32(native.records[i])==pairs[i][0] && read32(native.records[i]+4)==pairs[i][0]);
        assert(read32(native.records[i]+0x7c)==0);
    }
    ++registered_calls;
}
static void append_desc(void *tree,const void *first,const void *end) {
    const uintptr_t *p=first;assert(tree==(void *)2 && (const uintptr_t *)end-p==2);
    assert(p[0]==AF_CARDS_MENU_DESCRIPTOR && p[1]==(uintptr_t)native.descriptor);
    assert(read32(native.descriptor+0x20)==0xd4 && read32(native.descriptor+0x54)==3);
    assert(readptr(native.descriptor+0x58)==(uintptr_t)native.rows);
    assert(readptr(native.descriptor+0x78)==(uintptr_t)af_ap_cards_current);
    assert(readptr(native.descriptor+0x80)==(uintptr_t)af_ap_cards_focus);
    assert(readptr(native.descriptor+0x88)==(uintptr_t)af_ap_cards_action);
    assert(read32(native.descriptor+0x90)==0);
    ++registered_calls;
}
static void append_parent(void *tree,const void *first,const void *end) {
    const uint32_t *p=first;assert(tree==(void *)3 && (const uint32_t *)end-p==2);
    assert(p[0]==AF_CARDS_MENU_ROOT && p[1]==AF_CARDS_MENU_DESCRIPTOR);++registered_calls;
}
static void append_secondary(void *tree,const void *first,const void *end) {
    const uint32_t (*p)[2]=first;
    assert(tree==(void *)4 && (const uint32_t *)end-(const uint32_t *)first==8);
    for(unsigned i=0;i<4;++i)assert(p[i][0]==AF_CARDS_MENU_ROOT+i && p[i][1]==p[i][0]);
    ++registered_calls;
}
static uintptr_t test_va(uintptr_t off) {
    if(off==0x28a87e8)return (uintptr_t)current;
    if(off==0x28b0464)return (uintptr_t)get_language;
    if(off==0x1bdb214)return (uintptr_t)get_parent;
    if(off==0x5915b80)return (uintptr_t)&trees[0];
    if(off==0x59611f8)return (uintptr_t)&trees[1];
    if(off==0x593fbd8)return (uintptr_t)&trees[2];
    if(off==0x59430d0)return (uintptr_t)&trees[3];
    if(off==0x3fe4a00)return (uintptr_t)root_template;
    if(off==0x3f52680)return (uintptr_t)item_template;
    if(off==0x5845f28)return (uintptr_t)desc_template;
    if(off==0x1bd906c)return (uintptr_t)contains;
    if(off==0x1c91e94)return (uintptr_t)append_rows;
    if(off==0x1c91c40)return (uintptr_t)append_desc;
    if(off==0x1c935e0)return (uintptr_t)append_parent;
    if(off==0x1c938a8)return (uintptr_t)append_secondary;
    assert(0);return 0;
}
static void prepare(void) {
    memset(&native,0,sizeof(native));native.base=1;native.registered=native.enabled=1;
    native.result=AF_EMPTY;shown=AF_CARDS_MENU_ROOT;language=0;parent_override=UINT32_MAX;
    for(unsigned i=0;i<4;++i)put32(native.records[i],AF_CARDS_MENU_ROOT+i);
}
/* 此处显式代替真实ENTER成功关闭点；方向和异步leave不得调用本helper。 */
static void choose(uint32_t menu) {shown=menu;assert(af_ap_cards_intent(menu)==AF_OK);af_ap_cards_action(menu);}
static void selection(unsigned slot) {
    prepare();AfApCardSelection out={90,91,92},old=out;
    assert(af_ap_cards_begin(7)==AF_OK);
    assert(af_ap_cards_current()==af_ap_cards_name(AF_CARDS_MENU_CANCEL));
    assert(read32(native.rows[0])==AF_CARDS_MENU_CANCEL);
    assert(af_ap_cards_refresh()==1 && af_ap_cards_refresh()==0);
    assert(af_ap_cards_begin(8)==AF_BUSY);
    for(uint32_t m=AF_CARDS_MENU_SLOT0;m<=AF_CARDS_MENU_CANCEL;++m) {
        shown=m;af_ap_cards_focus(af_ap_cards_name(m));af_ap_cards_action(m);
        assert(native.active && !native.selected && af_ap_cards_result()==AF_EMPTY);
        assert(af_ap_cards_take(7,&out)==AF_EMPTY && !memcmp(&out,&old,sizeof(out)));
    }
    uint32_t menu=slot?AF_CARDS_MENU_SLOT1:AF_CARDS_MENU_SLOT0;shown=menu;
    assert(af_ap_cards_intent(menu)==AF_OK && af_ap_cards_intent(menu)==AF_BUSY);
    af_ap_cards_action(AF_CARDS_MENU_CANCEL);assert(native.active && native.intent==menu);
    assert(af_ap_cards_intent(0)==AF_OK);af_ap_cards_action(menu);assert(!native.selected);
    choose(menu);assert(af_ap_cards_result()==AF_OK && af_ap_cards_disabled());
    af_ap_cards_action(menu);assert(af_ap_cards_begin(8)==AF_BUSY);
    assert(af_ap_cards_take(6,&out)==AF_STALE && !memcmp(&out,&old,sizeof(out)));
    assert(af_ap_cards_take(7,(AfApCardSelection *)&native)==AF_INVALID);
    assert(af_ap_cards_take(7,&out)==AF_OK && out.generation==7 && out.slot==slot && !out.reserved);
    assert(af_ap_cards_take(7,&out)==AF_EMPTY);
    assert(af_ap_cards_begin(7)==AF_STALE && af_ap_cards_begin(8)==AF_OK);
}
static void rejection(void) {
    prepare();AfApCardSelection out={1,2,3},old=out;
    assert(af_ap_cards_begin(0)==AF_INVALID && af_ap_cards_begin(1)==AF_OK);
    uint32_t stale=af_ap_cards_name(AF_CARDS_MENU_SLOT0);
    choose(AF_CARDS_MENU_CANCEL);assert(af_ap_cards_result()==AF_CARDS_CANCELLED);
    assert(af_ap_cards_take(1,&out)==AF_EMPTY && !memcmp(&out,&old,sizeof(out)));
    assert(af_ap_cards_begin(2)==AF_OK);
    af_ap_cards_focus(stale);assert(af_ap_cards_current()==af_ap_cards_name(AF_CARDS_MENU_CANCEL));
    assert(!strcmp(af_ap_cards_text(stale),"List changed"));
    shown=0x15ea;assert(af_ap_cards_intent(AF_CARDS_MENU_SLOT0)==AF_STALE);
    shown=AF_CARDS_MENU_ROOT;assert(af_ap_cards_intent(AF_CARDS_MENU_ROOT)==AF_INVALID);
    shown=AF_CARDS_MENU_SLOT0;parent_override=0x7f;assert(af_ap_cards_intent(shown)==AF_STALE);
    parent_override=UINT32_MAX;assert(af_ap_cards_intent(shown)==AF_OK);
    parent_override=0x7f;af_ap_cards_action(shown);
    assert(af_ap_cards_result()==AF_STALE && af_ap_cards_take(2,&out)==AF_EMPTY);
    parent_override=UINT32_MAX;assert(af_ap_cards_begin(3)==AF_OK);
    shown=AF_CARDS_MENU_SLOT1;assert(af_ap_cards_intent(shown)==AF_OK);
    assert(af_ap_cards_enable(0)==AF_OK && !native.intent && af_ap_cards_disabled());
    af_ap_cards_action(shown);assert(af_ap_cards_take(3,&out)==AF_EMPTY);
    assert(af_ap_cards_enable(1)==AF_OK);
    for(unsigned i=4;i<=255;++i) {assert(af_ap_cards_begin(i)==AF_OK);assert(af_ap_cards_cancel()==AF_OK);}
    assert(af_ap_cards_begin(256)==AF_EXHAUSTED);
}
static void registration_and_text(void) {
    for(unsigned collision=1;collision<=4;++collision) {
        memset(&native,0,sizeof(native));native.base=1;collisions=collision;registered_calls=0;
        assert(af_ap_cards_register()==AF_EXISTS && !registered_calls && !native.registered);
        for(size_t i=0;i<sizeof(native.records);++i)assert(!((uint8_t *)native.records)[i]);
    }
    collisions=0;registered_calls=0;memset(root_template,0xa5,sizeof(root_template));
    memset(item_template,0x5a,sizeof(item_template));memset(desc_template,0,sizeof(desc_template));
    put32(desc_template+0x20,0xd4);put32(desc_template+0x54,8);
    uint8_t before_root[128],before_item[128],before_desc[192];
    memcpy(before_root,root_template,128);memcpy(before_item,item_template,128);memcpy(before_desc,desc_template,192);
    assert(af_ap_cards_register()==AF_OK && registered_calls==4);
    assert(!memcmp(before_root,root_template,128) && !memcmp(before_item,item_template,128) && !memcmp(before_desc,desc_template,192));
    assert(af_ap_cards_register()==AF_BUSY && af_ap_cards_enable(1)==AF_OK && af_ap_cards_begin(1)==AF_OK);
    language=0;assert(!strcmp(af_ap_cards_text(af_ap_cards_name(AF_CARDS_MENU_ROOT)),"Choose SD card"));
    assert(!strcmp(af_ap_cards_text(af_ap_cards_name(AF_CARDS_MENU_SLOT0)),"Card slot 1"));
    assert(!strcmp(af_ap_cards_text(af_ap_cards_compact(AF_CARDS_MENU_SLOT1)),"SD2"));
    language=25;assert(!strcmp(af_ap_cards_text(af_ap_cards_name(AF_CARDS_MENU_ROOT)),"选择SD卡"));
    assert(!strcmp(af_ap_cards_text(af_ap_cards_name(AF_CARDS_MENU_SLOT1)),"卡槽2"));
    assert(!strcmp(af_ap_cards_text(af_ap_cards_compact(AF_CARDS_MENU_SLOT0)),"卡1"));
    assert(!strcmp(af_ap_cards_text(af_ap_cards_name(AF_CARDS_MENU_CANCEL)),"取消"));
    assert(!af_ap_cards_is_id(0x1663) && !af_ap_cards_is_id(0x1668));
    assert(af_ap_cards_parent(AF_CARDS_MENU_ROOT)==0x15e7 && af_ap_cards_parent(AF_CARDS_MENU_SLOT0)==AF_CARDS_MENU_ROOT);
    assert(af_ap_cards_parent(0x1e6)==UINT32_MAX && af_ap_cards_name(0x1e6)==UINT32_MAX);
    assert(!af_ap_cards_text(0x7fcf0001));
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"slot0"))selection(0);
    else if(!strcmp(argv[1],"slot1"))selection(1);
    else if(!strcmp(argv[1],"rejection"))rejection();
    else if(!strcmp(argv[1],"registration"))registration_and_text();
    else assert(0);
    puts("PASS");return 0;
}
'''


@pytest.fixture(scope='module')
def cards_binary(tmp_path_factory):
    out = tmp_path_factory.mktemp('cards-contract')
    resolver = 'static uintptr_t va(uintptr_t off) {return native.base+off;}'
    body = (HERE / 'native/af_ap_cards.c').read_text()
    assert body.count(resolver) == 1
    body = body.replace(resolver, 'static uintptr_t test_va(uintptr_t off);\nstatic uintptr_t va(uintptr_t off) {return test_va(off);}')
    source = out / 'cards.c'
    source.write_text(HARNESS.replace('#include "af_ap_cards.c"', body))
    binary = out / 'cards'
    compiler = shutil.which('clang')
    assert compiler
    subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I', str(HERE / 'native'), '-I', str(SHARED), str(source), '-o', str(binary)],
                   check=True, capture_output=True, text=True)
    return binary


@pytest.mark.parametrize('case', ['slot0', 'slot1', 'rejection', 'registration'])
def test_card_choice_contract(cards_binary, case):
    subprocess.run([str(cards_binary), case], check=True, capture_output=True, text=True)
