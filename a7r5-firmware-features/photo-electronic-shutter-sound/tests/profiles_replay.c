#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "r5sound_profiles.h"
static struct {uint8_t bytes[96];size_t size;unsigned fail,writes;} memory;
static int read_file(void *c,const char *name,uint8_t *p,size_t cap,size_t *n){
 (void)c;if(strcmp(name,"R5SOUND.PRO")||!memory.size)return 1;
 if(cap<memory.size)return -1;memcpy(p,memory.bytes,memory.size);*n=memory.size;return 0;
}
static int write_file(void *c,const char *name,const uint8_t *p,size_t n){
 (void)c;assert(!strcmp(name,"R5SOUND.PRO")&&n==96);memory.writes++;
 if(memory.fail)return -1;memcpy(memory.bytes,p,n);memory.size=n;return 0;
}
int main(void){
 r5sound_storage store={0,read_file,write_file,0,0,0};r5sound_catalog c={0};r5sound_profiles p,q;
 c.count=2;memset(c.entries[0].sha,1,32);memset(c.entries[1].sha,2,32);
 assert(!r5sound_profiles_load(&store,&c,&p));
 assert(p.group[0].selected==0&&p.group[1].selected==0&&p.group[0].step==5&&p.group[1].step==5);
 assert(!r5sound_profiles_save(&store,&c,&p,0,1,3));
 assert(!r5sound_profiles_save(&store,&c,&p,1,2,8));
 assert(p.group[0].selected==1&&p.group[0].step==3&&p.group[1].selected==2&&p.group[1].step==8);
 assert(!r5sound_profiles_load(&store,&c,&q)&&!memcmp(&q,&p,sizeof p));
 r5sound_entry swap=c.entries[0];c.entries[0]=c.entries[1];c.entries[1]=swap;
 assert(!r5sound_profiles_load(&store,&c,&q)&&q.group[0].selected==2&&q.group[1].selected==1);
 c.count=1;assert(!r5sound_profiles_load(&store,&c,&q)&&q.group[0].selected==0&&q.group[1].selected==1);
 assert(q.group[0].step==3&&q.group[1].step==8);
 assert(!r5sound_profiles_save(&store,&c,&q,0,0,2));
 assert(!r5sound_profiles_load(&store,&c,&p)&&p.group[0].selected==0&&p.group[1].selected==1&&p.group[0].step==2);
 memory.fail=1;q=p;assert(r5sound_profiles_save(&store,&c,&p,1,0,5)<0&&!memcmp(&q,&p,sizeof p));memory.fail=0;
 unsigned writes=memory.writes;
 assert(r5sound_profiles_save(&store,&c,&p,2,0,5)<0&&r5sound_profiles_save(&store,&c,&p,0,2,5)<0);
 assert(r5sound_profiles_save(&store,&c,&p,0,0,0)<0&&r5sound_profiles_save(&store,&c,&p,0,0,11)<0&&memory.writes==writes);
 memory.bytes[30]^=1;assert(r5sound_profiles_load(&store,&c,&p)<0);
 assert(!p.group[0].selected&&!p.group[1].selected&&p.group[0].step==5&&p.group[1].step==5);
 assert(r5sound_profile_from_native(0)==0&&r5sound_profile_from_native(1)==1);
 assert(r5sound_profile_from_native(2)==R5SOUND_UNKNOWN&&r5sound_profile_from_native(~0u)==R5SOUND_UNKNOWN);
 puts("双组保存、身份重排、缺失关闭、损坏拒绝、写失败保持、未知快门拒绝：通过");return 0;
}
