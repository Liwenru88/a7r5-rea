"""实际普通目录扫描／读取接到浏览选择；原D4生命周期另由完整客体验证。"""
from pathlib import Path
import subprocess

import pytest

NATIVE=Path(__file__).resolve().parents[1]/'native'
HARNESS=r'''
#define _POSIX_C_SOURCE 200809L
#include "af_ap_media.h"
#include "af_sha256.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static AfMediaList published;
static int browser_status=AF_EMPTY,read_count,show_count,back_count;
static uint32_t page,selected;
static uint8_t source[4096];
static const char cube[]="LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n";
int af_ap_browser_publish(const AfMediaList *list){published=*list;browser_status=AF_EMPTY;page=0;return AF_OK;}
int af_ap_browser_show(void){++show_count;return AF_OK;}
int af_ap_browser_back(void){++back_count;return AF_OK;}
int af_ap_browser_cancel(void){browser_status=AF_BROWSER_CANCELLED;return AF_OK;}
int af_ap_browser_result(void){return browser_status;}
uint32_t af_ap_browser_page(void){return page;}
int af_ap_browser_take(uint64_t generation,AfApBrowserSelection *out){
    assert(generation==published.generation);*out=(AfApBrowserSelection){generation,selected,0};
    browser_status=AF_EMPTY;return AF_OK;
}
static int actual_read(int fd,const AfMediaList *list,uint32_t index,void *out,size_t cap,
                       AfMediaSource *info,AfGridProgress p,void *c){
    ++read_count;return af_media_read(fd,list,index,out,cap,info,p,c);
}
static void put(int fd,const char *bytes,size_t count){int f=openat(fd,"暖光.cube",O_WRONLY|O_CREAT|O_TRUNC,0600);
    assert(f>=0&&write(f,bytes,count)==(ssize_t)count&&close(f)==0);}
int main(int argc,char **argv){
    assert(argc==3);int fd=open(argv[1],O_RDONLY|O_DIRECTORY);assert(fd>=0);put(fd,cube,sizeof(cube)-1);
    AfApMediaBinding b={AF_AP_MEDIA_VERSION,sizeof(b),fd,0,af_media_scan,actual_read,source,sizeof(source)};
    assert(sizeof(b)==48);assert(af_ap_media_open()==AF_MANAGE_NOT_READY);
    AfApMediaBinding bad=b;bad.reserved=1;assert(af_ap_media_bind(&bad)==AF_INVALID);
    assert(af_ap_media_bind(&b)==AF_OK&&af_ap_media_bind(&b)==AF_BUSY);
    assert(af_ap_media_open()==AF_OK&&af_ap_media_phase()==AF_AP_MEDIA_BROWSING);
    assert(af_ap_media_rebind(&b)==AF_BUSY);
    assert(published.count==1&&!strcmp(published.entries[0].name,"暖光.cube"));
    AfApMediaInfo info={0},before=info;
    assert(af_ap_media_snapshot(&info)==AF_EMPTY&&!memcmp(&info,&before,sizeof(info)));
    assert(af_ap_media_open()==AF_BUSY);assert(af_ap_media_refresh()==1&&af_ap_media_refresh()==0);
    assert(af_ap_media_poll()==AF_EMPTY&&show_count==1);
    if(!strcmp(argv[2],"success")){
        page=1;assert(af_ap_media_poll()==AF_OK&&show_count==2);
        browser_status=AF_OK;assert(af_ap_media_poll()==AF_MANAGE_NOT_READY);
        assert(af_ap_media_phase()==AF_AP_MEDIA_READ_READY&&af_ap_media_result()==AF_MANAGE_NOT_READY);
        assert(af_ap_media_snapshot(&info)==AF_OK&&info.generation==1&&info.index==0);
        assert(info.source.bytes==sizeof(cube)-1&&!memcmp(source,cube,sizeof(cube)-1));
        assert(af_ap_media_snapshot((AfApMediaInfo *)source)==AF_INVALID);
        assert(!memcmp(source,cube,sizeof(cube)-1));
        uint8_t hash[32];assert(af_sha256(cube,sizeof(cube)-1,hash)==AF_OK&&!memcmp(hash,info.source.sha256,32));
        assert(unlinkat(fd,"暖光.cube",0)==0&&!strcmp(af_ap_media_name(),"暖光.cube"));
        assert(read_count==1&&back_count==1&&af_ap_media_poll()==AF_EMPTY);
        assert(af_ap_media_cancel()==AF_OK&&af_ap_media_snapshot(&info)==AF_EMPTY);
    }else{
        put(fd,"changed",7);browser_status=AF_OK;
        assert(af_ap_media_poll()==AF_STALE&&af_ap_media_phase()==AF_AP_MEDIA_FAILED);
        assert(af_ap_media_snapshot(&info)==AF_EMPTY&&!memcmp(&info,&before,sizeof(info)));
        assert(!af_ap_media_name()&&read_count==1);
        assert(af_ap_media_open()==AF_OK&&published.generation==2);
        assert(af_ap_browser_cancel()==AF_OK&&af_ap_media_poll()==AF_MANAGE_CANCEL&&read_count==1);
        assert(af_ap_media_open()==AF_OK&&published.generation==3);
        assert(af_ap_media_cancel()==AF_OK&&af_ap_media_poll()==AF_EMPTY&&read_count==1);
        assert(mkdirat(fd,"new-card",0700)==0);int other=openat(fd,"new-card",O_RDONLY|O_DIRECTORY);assert(other>=0);
        put(other,cube,sizeof(cube)-1);AfApMediaBinding next=b;next.directory=other;
        assert(af_ap_media_rebind(&next)==AF_OK&&af_ap_media_phase()==AF_AP_MEDIA_IDLE);
        assert(af_ap_media_snapshot(&info)==AF_EMPTY&&af_ap_media_open()==AF_OK&&published.generation==4);
        assert(af_ap_media_cancel()==AF_OK&&read_count==1);
        int shows=show_count,backs=back_count;
        assert(af_ap_media_prepare()==AF_OK&&published.generation==5&&show_count==shows);
        browser_status=AF_OK;assert(af_ap_media_finish()==AF_MANAGE_NOT_READY);
        assert(show_count==shows&&back_count==backs&&read_count==2);
        assert(af_ap_media_snapshot(&info)==AF_OK&&info.generation==5&&info.source.bytes==sizeof(cube)-1);
        assert(close(other)==0);
    }
    assert(close(fd)==0);return 0;
}
'''


@pytest.fixture(scope='module')
def media_driver(tmp_path_factory):
    folder=tmp_path_factory.mktemp('ap-media');c=folder/'driver.c';c.write_text(HARNESS)
    binary=folder/'media'
    command=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(c),
             *[str(NATIVE/n) for n in ('af_ap_media.c','af_media.c','af_sha256.c','af_slots.c')],'-o',str(binary)]
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return binary


@pytest.mark.parametrize('case',['success','stale-cancel'])
def test_actual_file_browser_bridge(media_driver,tmp_path,case):
    result=subprocess.run([str(media_driver),str(tmp_path),case],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
