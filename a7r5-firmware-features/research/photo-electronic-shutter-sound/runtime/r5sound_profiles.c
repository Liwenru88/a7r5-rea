#include "r5sound_profiles.h"
#include <string.h>
static uint32_t word(const uint8_t *p){return p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static void put(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}
unsigned r5sound_profile_from_native(unsigned type){return type<2?type:R5SOUND_UNKNOWN;}
static void defaults(r5sound_profiles *p){memset(p,0,sizeof(*p));for(unsigned g=0;g<2;g++)p->group[g].step=5;}
int r5sound_profiles_load(const r5sound_storage *s,const r5sound_catalog *c,r5sound_profiles *out){
 if(!s||!s->read||!c||c->count>R5SOUND_MAX_FILES||!out)return R5SOUND_BAD;
 defaults(out);uint8_t p[R5SOUND_PROFILE_BYTES];size_t n=0;
 int rc=s->read(s->ctx,"R5SOUND.PRO",p,sizeof p,&n);
 if(rc==1){
  /* 旧单组只恢复到电子快门，机械组默认关闭；读取不迁移、不重写。 */
  unsigned index=0,step=5;
  if(r5sound_selection_load(s,c,&index)||r5sound_volume_load(s,&step))return R5SOUND_BAD;
  out->group[1].step=step;out->group[1].selected=index;
  if(index)memcpy(out->group[1].identity,c->entries[index-1].sha,32);
  return 0;
 }
 if(rc||n!=sizeof p||memcmp(p,"R5SNDPF1",8)||word(p+8)!=1||word(p+92)!=ss_crc32(p,92))return R5SOUND_BAD;
 r5sound_profiles next;defaults(&next);
 for(unsigned g=0;g<2;g++){
  const uint8_t *r=p+12+g*40;uint32_t step=word(r+32),enabled=word(r+36);
  if(step<1||step>10||enabled>1)return R5SOUND_BAD;
  uint8_t zero[32]={0};if(!enabled&&memcmp(r,zero,32))return R5SOUND_BAD;
  next.group[g].step=step;
  if(enabled)for(unsigned i=0;i<c->count;i++)if(!memcmp(r,c->entries[i].sha,32)){
   memcpy(next.group[g].identity,r,32);next.group[g].selected=i+1;break;
  }
 }
 *out=next;return 0;
}
int r5sound_profiles_save(const r5sound_storage *s,const r5sound_catalog *c,r5sound_profiles *state,
                         unsigned g,unsigned index,unsigned step){
 if(!s||!s->write_atomic||!c||!state||g>=2||index>c->count||c->count>R5SOUND_MAX_FILES||step<1||step>10)return R5SOUND_BAD;
 r5sound_profiles next=*state;next.group[g].selected=index;next.group[g].step=step;
 memset(next.group[g].identity,0,32);if(index)memcpy(next.group[g].identity,c->entries[index-1].sha,32);
 uint8_t p[R5SOUND_PROFILE_BYTES]={0};memcpy(p,"R5SNDPF1",8);put(p+8,1);
 for(unsigned i=0;i<2;i++){
  uint8_t *r=p+12+i*40;
  if(next.group[i].step<1||next.group[i].step>10||next.group[i].selected>c->count)return R5SOUND_BAD;
  memcpy(r,next.group[i].identity,32);put(r+32,next.group[i].step);put(r+36,!!next.group[i].selected);
 }
 put(p+92,ss_crc32(p,92));
 if(s->write_atomic(s->ctx,"R5SOUND.PRO",p,sizeof p))return R5SOUND_IO;
 /* 只有工作线程写入；菜单读取的数字逐项原子发布。 */
 for(unsigned i=0;i<2;i++){
  memcpy(state->group[i].identity,next.group[i].identity,32);
  __atomic_store_n(&state->group[i].step,next.group[i].step,__ATOMIC_RELEASE);
  __atomic_store_n(&state->group[i].selected,next.group[i].selected,__ATOMIC_RELEASE);
 }
 return 0;
}
