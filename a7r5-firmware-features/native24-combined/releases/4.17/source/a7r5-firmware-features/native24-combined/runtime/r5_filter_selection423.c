#include "r5_filter_selection423.h"
#include "r5_lut_directory.h"
static uint32_t get32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put32(uint8_t *p,uint32_t v){p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8);p[2]=(uint8_t)(v>>16);p[3]=(uint8_t)(v>>24);}
static uint32_t crc(const uint8_t *p,unsigned n,unsigned at){uint32_t c=~0u;unsigned i,j;for(i=0;i<n;i++){c^=(i>=at && i<at+4)?0:p[i];for(j=0;j<8;j++)c=(c>>1)^((0u-(c&1u))&0xedb88320u);}return ~c;}
int r5_filter_select_is_envelope(const uint8_t *p,size_t n){return p && n>=8 && p[0]==R5_FILTER_SELECT_CLASS && get32(p+4)==R5_FILTER_SELECT_MAGIC;}
int r5_filter_select_encode(const struct r5_filter_select_request *r,uint8_t p[32]){
    unsigned i;uintptr_t a=(uintptr_t)r,b=(uintptr_t)p;
    if(!r || !p || !r->sequence || !r->alias || r->selected>R5_LOOK_SLOTS ||
       (b>=a?b-a<sizeof(*r):a-b<32))return 0;
    for(i=0;i<32;i++)p[i]=0;
    p[0]=R5_FILTER_SELECT_CLASS;p[1]=2;p[2]=R5_FILTER_SELECT_SET;p[3]=32;
    put32(p+4,R5_FILTER_SELECT_MAGIC);put32(p+8,r->sequence);put32(p+12,r->selected);
    put32(p+16,r->payload_crc);put32(p+20,r->alias);put32(p+28,crc(p,32,28));return 1;
}
int r5_filter_select_ack(const struct r5_filter_select_request *r,const uint8_t *p,size_t n){
    uint32_t status;
    if(!r || !r->sequence || !r->alias || r->selected>R5_LOOK_SLOTS || n!=32 ||
       !r5_filter_select_is_envelope(p,n) || p[1]!=2 || p[2]!=R5_FILTER_SELECT_ACK || p[3]!=32 ||
       get32(p+8)!=r->sequence || get32(p+12)!=r->selected || get32(p+16)!=r->payload_crc ||
       get32(p+20)!=r->alias || get32(p+28)!=crc(p,32,28))return -256;
    status=get32(p+24);if(status>R5_F_BAD_BANK)return -256;return status?-(int)status:1;
}
/* 恢复日志和活动选择共享同一受验证目录，日志优先于未完成的活动发布。 */
#include "r5_stable_io425.h"
static uint32_t identity,loaded_identity;
static unsigned loaded_version,recovery;
void r5_filter_selection_identity(uint32_t value){identity=value;}
uint32_t r5_filter_selection_loaded_identity(void){return loaded_identity;}
unsigned r5_filter_selection_loaded_version(void){return loaded_version;}
unsigned r5_filter_selection_recovery(void){return recovery;}
static void encode(unsigned selected,uint8_t p[24]){
    static const uint8_t magic[8]={'R','5','S','E','L','6',0,0};unsigned i;
    for(i=0;i<24;i++)p[i]=0;for(i=0;i<8;i++)p[i]=magic[i];
    put32(p+8,3);put32(p+12,selected);put32(p+16,identity);put32(p+20,crc(p,24,20));
}
static int decode(const uint8_t p[24],unsigned *out){
    unsigned selected=get32(p+12),version=get32(p+8),i;
    static const uint8_t prefix[5]={'R','5','S','E','L'};
    if(selected>R5_LOOK_SLOTS || p[6] || p[7] || get32(p+20)!=crc(p,24,20))return -1;
    for(i=0;i<5;i++)if(p[i]!=prefix[i])return -1;
    if(version==3 && p[5]=='6'){}
    else if(version==1 && p[5]=='4' && selected<=12 && !get32(p+16)){}
    else if(version==2 && p[5]=='5' && selected>=13 && !get32(p+16)){}
    else return -1;
    loaded_version=version;loaded_identity=version==3?get32(p+16):0;*out=selected;return 0;
}
static int read_record(struct r5_lut_directory *d,unsigned id,uint8_t p[25],unsigned *out){
    size_t n=0;int rc=r5_stable_read425(d,id,p,25,&n);
    if(rc==1)return R5_ABSENT;
    if(rc)return R5_IO_ERROR;
    return n==24 && !decode(p,out)?R5_IMPORTED:R5_INVALID;
}
int r5_filter_selection_load(struct r5_lut_directory *d,unsigned *out){
    uint8_t p[25];unsigned n;int rc;
    loaded_version=loaded_identity=recovery=0;if(!out)return R5_INVALID;
    rc=read_record(d,R5_STABLE_RECOVERY,p,&n);
    if(rc==R5_IMPORTED){recovery=1;*out=n;return rc;}
    if(rc!=R5_ABSENT){recovery=2;return rc;}
    rc=read_record(d,R5_STABLE_SELECTION,p,&n);if(rc==R5_IMPORTED)*out=n;return rc;
}
int r5_filter_selection_begin(struct r5_lut_directory *d){
    uint8_t p[25];unsigned n;int rc;
    uint32_t keep_identity=loaded_identity;unsigned keep_version=loaded_version;
    rc=read_record(d,R5_STABLE_RECOVERY,p,&n);
    if(rc==R5_ABSENT){
        rc=read_record(d,R5_STABLE_SELECTION,p,&n);
        if(rc==R5_ABSENT || rc==R5_INVALID){encode(0,p);rc=R5_IMPORTED;}
        if(rc==R5_IMPORTED)rc=r5_stable_publish425(d,R5_STABLE_RECOVERY,p,24)?R5_IO_ERROR:R5_IMPORTED;
    }
    loaded_identity=keep_identity;loaded_version=keep_version;
    return rc==R5_IMPORTED?0:2;
}
int r5_filter_selection_save(struct r5_lut_directory *d,unsigned selected){
    uint8_t expected[24];int rc;
    if(selected>R5_LOOK_SLOTS)return 1;
    /* 覆盖解除后可修复损坏日志；0只表示后台路由，不代表原厂ST。 */
    if(r5_filter_selection_begin(d) && selected)return 2;
    encode(selected,expected);
    rc=r5_stable_publish425(d,R5_STABLE_SELECTION,expected,24);if(rc)return rc;
    rc=r5_stable_remove425(d,R5_STABLE_RECOVERY);if(rc)return 3;
    recovery=0;loaded_identity=identity;loaded_version=3;return 0;
}
