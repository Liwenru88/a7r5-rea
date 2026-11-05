/* 独立微调目录。UI只改工作值，唯一文件线程捕获快照并发布。 */
#include "r5_tune425.h"
#include "r5_stable_io425.h"
#include "r5_filter_selection423.h"
#define LOAD(p) __atomic_load_n((p),__ATOMIC_ACQUIRE)
#define STORE(p,v) __atomic_store_n((p),(v),__ATOMIC_RELEASE)
#define LIMIT 128u
#define HEADER 64u
#define RECORD 48u
#define FILE_MAX (HEADER+LIMIT*RECORD)
struct entry {uint8_t key[32];int8_t initial[8],saved[8],work[8];uint32_t revision,seeded;};
static struct entry catalog[LIMIT];
static uint16_t slots[R5_LOOK_SLOTS];
static uint32_t count,ready,status,wire_seq,wire_enabled;
static uint64_t wire_receipt;
static uint64_t generation;
static uint8_t wire_key[32],committed_key[32];
static int8_t wire_values[8],committed_values[8];
static uint32_t committed_enabled,committed_seq;
static const int8_t low[8]={-9,-9,-9,0,-9,0,1,0};
static const int8_t high[8]={9,9,9,9,9,9,5,9};
static const uint16_t wire_ids[8]={0x4030,0x40f3,0x40f4,0x40f5,0x4031,0x4032,0x40f6,0x40f7};
static const uint16_t wire_offsets[8]={0x1cc,0x6dc,0x6e8,0x6f4,0x1d8,0x1e4,0x700,0x70c};
static uint32_t get(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put(uint8_t *p,uint32_t x){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(x>>(8*i));}
static void copy(void *to,const void *from,unsigned n){uint8_t *d=to;const uint8_t *s=from;while(n--)*d++=*s++;}
static void zero(void *to,unsigned n){uint8_t *d=to;while(n--)*d++=0;}
static int equal(const void *a,const void *b,unsigned n){const uint8_t *x=a,*y=b;while(n--)if(*x++!=*y++)return 0;return 1;}
static int valid(unsigned p,int v){return p<8 && v>=low[p] && v<=high[p];}
static uint32_t crc(const uint8_t *p,unsigned n){uint32_t x=~0u;for(unsigned i=0;i<n;i++){x^=i>=24&&i<28?0:p[i];for(unsigned k=0;k<8;k++)x=(x>>1)^((0u-(x&1u))&0xedb88320u);}return ~x;}

/* SHA256输入按色彩结构逐字节定义，名称、槽号和填充不参与身份。 */
struct sha {uint32_t h[8];uint64_t bytes;uint8_t block[64];unsigned used;};
static uint32_t rotr(uint32_t x,unsigned n){return (x>>n)|(x<<(32-n));}
static void transform(struct sha *s){
 static const uint32_t k[64]={
 0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
 0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
 0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
 0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
 0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
 0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
 0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
 0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
 uint32_t w[64],a,b,c,d,e,f,g,h;
 for(unsigned i=0;i<16;i++){const uint8_t *p=s->block+4*i;w[i]=(uint32_t)p[0]<<24|(uint32_t)p[1]<<16|(uint32_t)p[2]<<8|p[3];}
 for(unsigned i=16;i<64;i++){uint32_t x=w[i-15],y=w[i-2];w[i]=w[i-16]+(rotr(x,7)^rotr(x,18)^(x>>3))+w[i-7]+(rotr(y,17)^rotr(y,19)^(y>>10));}
 a=s->h[0];b=s->h[1];c=s->h[2];d=s->h[3];e=s->h[4];f=s->h[5];g=s->h[6];h=s->h[7];
 for(unsigned i=0;i<64;i++){uint32_t t=h+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^(~e&g))+k[i]+w[i];uint32_t u=(rotr(a,2)^rotr(a,13)^rotr(a,22))+((a&b)^(a&c)^(b&c));h=g;g=f;f=e;e=d+t;d=c;c=b;b=a;a=t+u;}
 s->h[0]+=a;s->h[1]+=b;s->h[2]+=c;s->h[3]+=d;s->h[4]+=e;s->h[5]+=f;s->h[6]+=g;s->h[7]+=h;
}
static void hash_bytes(struct sha *s,const void *bytes,unsigned n){const uint8_t *p=bytes;s->bytes+=n;while(n--){s->block[s->used++]=*p++;if(s->used==64){transform(s);s->used=0;}}}
void r5_tune_identity(const struct r5_native_look *v,uint8_t out[32]){
 struct sha s={{0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19},0,{0},0};
 static const uint8_t domain[8]={'R','5','C','O','L','O','R','1'};uint8_t tail[72]={0x80};
 hash_bytes(&s,domain,8);hash_bytes(&s,v->cc1,sizeof v->cc1);hash_bytes(&s,v->block13,sizeof v->block13);hash_bytes(&s,v->gamma,sizeof v->gamma);hash_bytes(&s,v->grid,sizeof v->grid);
 uint64_t bits=s.bytes*8;unsigned pad=s.used<56?56-s.used:120-s.used;
 for(unsigned i=0;i<8;i++)tail[pad+i]=(uint8_t)(bits>>(56-8*i));hash_bytes(&s,tail,pad+8);
 for(unsigned i=0;i<32;i++)out[i]=(uint8_t)(s.h[i/4]>>(24-8*(i%4)));
}

static struct entry *lookup(unsigned n){return LOAD(&ready) && !LOAD(&status) && n && n<=R5_LOOK_SLOTS && slots[n-1]<count?&catalog[slots[n-1]]:0;}
static int find(const uint8_t key[32]){for(unsigned i=0;i<count;i++)if(equal(catalog[i].key,key,32))return (int)i;return -1;}
static int file_valid(const uint8_t *p,size_t n,unsigned journal){
 static const uint8_t magic[8]={'R','5','T','U','N','E','1',0};
 if(n<HEADER || !equal(p,magic,8) || get(p+8)!=1 || get(p+12)>LIMIT || n!=HEADER+get(p+12)*RECORD || get(p+28)!=journal || get(p+24)!=crc(p,(unsigned)n))return 0;
 for(unsigned i=56;i<64;i++)if(p[i])return 0;
 if(!journal)for(unsigned i=32;i<56;i++)if(p[i])return 0;
 for(unsigned i=0;i<get(p+12);i++){
  const uint8_t *r=p+HEADER+i*RECORD;
  for(unsigned j=0;j<8;j++)if(!valid(j,(int8_t)r[32+j])||!valid(j,(int8_t)r[40+j]))return 0;
  for(unsigned j=0;j<i;j++)if(equal(r,p+HEADER+j*RECORD,32))return 0;
 }
 return 1;
}
static void decode(const uint8_t *p){
 count=get(p+12);generation=(uint64_t)get(p+16)|(uint64_t)get(p+20)<<32;
 for(unsigned i=0;i<count;i++){struct entry *r=&catalog[i];copy(r,p+HEADER+i*RECORD,RECORD);copy(r->work,r->saved,8);r->revision=2;r->seeded=1;}
}
static size_t encode(unsigned journal,const uint8_t old_selection[24],int override){
 uint8_t *p=r5_stable_scratch425;unsigned total=0;zero(p,HEADER);
 static const uint8_t magic[8]={'R','5','T','U','N','E','1',0};copy(p,magic,8);put(p+8,1);
 uint64_t next=generation+(journal?0:1);if(!journal && !next)return 0;
 put(p+16,(uint32_t)next);put(p+20,(uint32_t)(next>>32));put(p+28,journal);if(journal)copy(p+32,old_selection,24);
 for(unsigned i=0;i<count;i++)if(LOAD(&catalog[i].seeded)){
  const struct entry *r=&catalog[i];uint8_t *out=p+HEADER+total++*RECORD;copy(out,r,RECORD);
  if(override && equal(r->key,wire_key,32))copy(out+40,wire_values,8);
 }
 put(p+12,total);size_t n=HEADER+total*RECORD;put(p+24,crc(p,(unsigned)n));return n;
}
int r5_tune_library(struct r5_lut_directory *d,const struct r5_look_set *set){
 uint8_t selected[25];size_t n=0,sn=0;int rc,restoring=0;STORE(&ready,0);STORE(&status,0);count=0;generation=0;
 for(unsigned i=0;i<R5_LOOK_SLOTS;i++)slots[i]=0xffff;
 if(r5_filter_selection_recovery()==1){
  rc=r5_stable_read425(d,R5_STABLE_RECOVERY,selected,sizeof selected,&sn);
  if(rc || sn!=24){STORE(&status,2);goto bind;}
  rc=r5_stable_read425(d,R5_STABLE_TUNE_RECOVERY,r5_stable_scratch425,FILE_MAX+1,&n);
  if(!rc){
   if(!file_valid(r5_stable_scratch425,n,1) || !equal(r5_stable_scratch425+32,selected,24)){STORE(&status,2);goto bind;}
   decode(r5_stable_scratch425);restoring=1;
  }else if(rc!=1){STORE(&status,2);goto bind;}
 }
 if(!restoring){
  rc=r5_stable_read425(d,R5_STABLE_TUNE,r5_stable_scratch425,FILE_MAX+1,&n);
  if(!rc){if(!file_valid(r5_stable_scratch425,n,0)){STORE(&status,2);goto bind;}decode(r5_stable_scratch425);}
  else if(rc!=1){STORE(&status,2);goto bind;}
 }else{
  n=encode(0,selected,0);
  if(!n || r5_stable_publish425(d,R5_STABLE_TUNE,r5_stable_scratch425,n)){STORE(&status,3);goto bind;}generation++;
 }
bind:
 if(set)for(unsigned i=0;i<R5_LOOK_SLOTS;i++)if(set->valid_mask&(1u<<i)){
  uint8_t key[32];r5_tune_identity(&set->look[i],key);int at=find(key);
  if(at<0 && count<LIMIT){at=(int)count++;zero(&catalog[at],sizeof catalog[at]);copy(catalog[at].key,key,32);}
  if(at>=0)slots[i]=(uint16_t)at;
 }
 STORE(&ready,1);return (int)LOAD(&status);
}
int r5_tune_seed(unsigned n,const int32_t values[8]){
 struct entry *r=lookup(n);if(!r || !values)return -1;if(LOAD(&r->seeded))return 0;
 for(unsigned i=0;i<8;i++)if(!valid(i,values[i]))return -1;
 for(unsigned i=0;i<8;i++)r->initial[i]=r->saved[i]=r->work[i]=(int8_t)values[i];STORE(&r->revision,2);STORE(&r->seeded,1);return 0;
}
int r5_tune_value(unsigned n,unsigned p,int *out){struct entry *r=lookup(n);if(!r || !LOAD(&r->seeded) || p>=8 || !out)return -1;*out=LOAD(&r->work[p]);return 0;}
int r5_tune_default(unsigned n,unsigned p,int *out){struct entry *r=lookup(n);if(!r || !LOAD(&r->seeded) || p>=8 || !out)return -1;*out=r->initial[p];return 0;}
int r5_tune_edit(unsigned n,unsigned p,int value){
 struct entry *r=lookup(n);if(!r || !LOAD(&r->seeded) || !valid(p,value) || LOAD(&r->revision)>0xfffffffcu)return -1;
 if(LOAD(&r->work[p])==value)return 0;__atomic_fetch_add(&r->revision,1,__ATOMIC_ACQ_REL);STORE(&r->work[p],(int8_t)value);__atomic_fetch_add(&r->revision,1,__ATOMIC_RELEASE);return 0;
}
int r5_tune_reset(unsigned n){
 struct entry *r=lookup(n);if(!r || !LOAD(&r->seeded) || LOAD(&r->revision)>0xfffffffcu)return -1;
 __atomic_fetch_add(&r->revision,1,__ATOMIC_ACQ_REL);for(unsigned i=0;i<8;i++)STORE(&r->work[i],r->initial[i]);__atomic_fetch_add(&r->revision,1,__ATOMIC_RELEASE);return 0;
}
static int work_equal(const struct entry *r,const int8_t values[8]){for(unsigned i=0;i<8;i++)if(LOAD(&r->work[i])!=values[i])return 0;return 1;}
/* UI与原生打包线程只能读取完整发布的快照，不混读前后两次事务。 */
static int shared_snapshot(const uint32_t *seq,const uint32_t *flag,const uint8_t key[32],const int8_t values[8],unsigned *enabled,uint8_t out_key[32],int8_t out_values[8]){
 for(unsigned tries=0;tries<8;tries++){
  uint32_t s=LOAD(seq);if(s&1)continue;*enabled=LOAD(flag);
  if(out_key)for(unsigned i=0;i<32;i++)out_key[i]=LOAD(&key[i]);
  for(unsigned i=0;i<8;i++)out_values[i]=LOAD(&values[i]);
  if(s==LOAD(seq))return 1;
 }return 0;
}
unsigned r5_tune_changed(unsigned n){
 struct entry *r=lookup(n);unsigned enabled;uint8_t key[32];int8_t values[8];
 if(n && (!r || !LOAD(&r->seeded)))return 0;
 if(!shared_snapshot(&committed_seq,&committed_enabled,committed_key,committed_values,&enabled,key,values))return 1;
 return n?(!enabled || !equal(r->key,key,32) || !work_equal(r,values)):enabled;
}
unsigned r5_tune_pending_changed(unsigned n){
 struct entry *r=lookup(n);unsigned enabled;uint8_t key[32];int8_t values[8];
 if(!n || !r || !LOAD(&r->seeded))return 0;
 if(!shared_snapshot(&wire_seq,&wire_enabled,wire_key,wire_values,&enabled,key,values))return 1;
 return !enabled || !equal(r->key,key,32) || !work_equal(r,values);
}
unsigned r5_tune_status(void){return LOAD(&status);}
int r5_tune_prepare(unsigned n,int rollback){
 struct entry *r=lookup(n);int8_t values[8];uint8_t key[32];unsigned enabled=0;
 if(n && LOAD(&status))return -1;
 if(r && LOAD(&r->seeded)){
  unsigned valid_snapshot=0;
  for(unsigned tries=0;tries<8;tries++){
   uint32_t seq=LOAD(&r->revision);if(seq&1)continue;
   copy(key,r->key,32);for(unsigned i=0;i<8;i++)values[i]=rollback?r->saved[i]:LOAD(&r->work[i]);
   if(rollback && committed_enabled && equal(key,committed_key,32))copy(values,committed_values,8);
   if(LOAD(&r->revision)==seq){valid_snapshot=1;break;}
  }
  if(!valid_snapshot)return -1;enabled=1;
 }
 unsigned next=__atomic_fetch_add(&wire_seq,1,__ATOMIC_ACQ_REL)+2;STORE(&wire_enabled,enabled);
 if(enabled){for(unsigned i=0;i<32;i++)STORE(&wire_key[i],key[i]);for(unsigned i=0;i<8;i++)STORE(&wire_values[i],values[i]);}
 STORE(&wire_receipt,(uint64_t)next<<32);__atomic_fetch_add(&wire_seq,1,__ATOMIC_RELEASE);return 0;
}
void r5_tune_commit(void){
 __atomic_fetch_add(&committed_seq,1,__ATOMIC_ACQ_REL);STORE(&committed_enabled,LOAD(&wire_enabled));
 if(LOAD(&wire_enabled)){for(unsigned i=0;i<32;i++)STORE(&committed_key[i],LOAD(&wire_key[i]));for(unsigned i=0;i<8;i++)STORE(&committed_values[i],LOAD(&wire_values[i]));}
 __atomic_fetch_add(&committed_seq,1,__ATOMIC_RELEASE);
}
int r5_tune_begin(struct r5_lut_directory *d){
 uint8_t old[25];size_t n=0;int rc;
 if(LOAD(&status))return 0;
 rc=r5_stable_read425(d,R5_STABLE_RECOVERY,old,sizeof old,&n);if(!rc)return 0;if(rc!=1)return 2;
 rc=r5_stable_read425(d,R5_STABLE_SELECTION,old,sizeof old,&n);
 if(rc==1){
  /* 缺少旧选择时先建立合法的0号基线，使两份恢复日志逐字节绑定。 */
  if(r5_filter_selection_save(d,0))return 2;
  rc=r5_stable_read425(d,R5_STABLE_SELECTION,old,sizeof old,&n);
 }
 if(rc || n!=24)return 2;
 n=encode(1,old,0);return n?r5_stable_publish425(d,R5_STABLE_TUNE_RECOVERY,r5_stable_scratch425,n):2;
}
int r5_tune_save(struct r5_lut_directory *d){
 if(!wire_enabled)return 0;if(LOAD(&status))return 2;
 int at=find(wire_key);if(at<0 || !LOAD(&catalog[at].seeded))return 2;
 size_t n=encode(0,0,1);if(!n)return 2;
 int rc=r5_stable_publish425(d,R5_STABLE_TUNE,r5_stable_scratch425,n);
 if(!rc){copy(catalog[at].saved,wire_values,8);generation++;}return rc;
}
void r5_tune_finish(struct r5_lut_directory *d){(void)r5_stable_remove425(d,R5_STABLE_TUNE_RECOVERY);}
unsigned r5_tune_generation425(void){return LOAD(&wire_seq);}
/* 按冻结代次记录实际发送结果；同一属性重复发送不能替代其他七项。 */
void r5_tune_sent425(unsigned generation,unsigned mask,int result){
 if((generation&1) || generation!=LOAD(&wire_seq) || !LOAD(&wire_enabled))return;
 uint64_t observed=LOAD(&wire_receipt),bits=result || !mask || (mask&~255u)?256u:mask;
 /* 代次与回执在同一原子字中发布，防止检查之后跨越下一次prepare。 */
 do{
  if((unsigned)(observed>>32)!=generation)return;
 }while(!__atomic_compare_exchange_n(&wire_receipt,&observed,observed|bits,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE));
}
int r5_tune_verify(void){
 unsigned sequence=LOAD(&wire_seq),enabled=LOAD(&wire_enabled);uint64_t receipt=LOAD(&wire_receipt);
 if((sequence&1) || sequence!=LOAD(&wire_seq))return -1;
 return enabled && ((unsigned)(receipt>>32)!=sequence || (receipt&511u)!=255u)?-1:0;
}
static unsigned packet_mask(const uint8_t *packet,size_t n){
 if(!packet || (n!=12 && n!=0x960))return 0;
 if(n==12){
  if(packet[0]!=5 || packet[1])return 0;
  unsigned id=(unsigned)packet[2]|(unsigned)packet[3]<<8;
  for(unsigned i=0;i<8;i++)if(id==wire_ids[i])return 1u<<i;return 0;
 }
 for(unsigned i=0;i<8;i++){
  const uint8_t *p=packet+wire_offsets[i];
  if(p[0]!=5 || p[1] || ((unsigned)p[2]|(unsigned)p[3]<<8)!=wire_ids[i])return 0;
 }return 255;
}
/* 在真正的OSAL发送前识别当前冻结快照；不改消息、不持有已移交的指针。 */
unsigned r5_tune_observe425(const uint8_t *packet,size_t n,unsigned *generation){
 unsigned mask=packet_mask(packet,n),enabled=0,sequence=LOAD(&wire_seq);int8_t values[8];
 if(!mask || !generation || (sequence&1) ||
    !shared_snapshot(&wire_seq,&wire_enabled,wire_key,wire_values,&enabled,0,values) ||
    !enabled || sequence!=LOAD(&wire_seq))return 0;
 for(unsigned i=0;i<8;i++)if(mask&(1u<<i)){
  unsigned at=n==12?8:wire_offsets[i]+8;
  if(packet[at]!=(uint8_t)values[i]){
   r5_tune_sent425(sequence,0,-1);return 0;
  }
 }
 *generation=sequence;return mask;
}
int r5_tune_overlay(uint8_t *packet,size_t n){
 int8_t values[8];unsigned enabled=0,good=0,sequence=LOAD(&wire_seq);
 good=shared_snapshot(&wire_seq,&wire_enabled,wire_key,wire_values,&enabled,0,values);
 if(!good || sequence!=LOAD(&wire_seq)){r5_tune_sent425(sequence,0,-1);return -1;}if(!enabled)return 0;
 unsigned mask=packet_mask(packet,n);if(!mask)goto bad;
 if(n==12){
  for(unsigned i=0;i<8;i++)if(mask&(1u<<i)){packet[8]=(uint8_t)values[i];return (int)mask;}
 }
 for(unsigned i=0;i<8;i++)packet[wire_offsets[i]+8]=(uint8_t)values[i];return 255;
bad:r5_tune_sent425(sequence,0,-1);return -1;
}
