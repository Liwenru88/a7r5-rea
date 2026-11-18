/* 原厂选择页，两组各自确认；浏览不访问存储或调用音频接口。 */
#include "r5_sound_menu437.h"
#include "../import/r5sound_profiles.h"
extern const unsigned char r5_native_menu_template[0xc0],r5_native_row_template[0x80];
extern void r5_native_menu_insert(void *,const void *,const void *);
extern void r5_native_row_insert(void *,const void *,const void *);
struct pair {uint64_t key;const void *pointer;};
unsigned char r5sound_menu_descriptor[0xc0] __attribute__((aligned(8)));
unsigned char r5sound_volume_descriptor[0xc0] __attribute__((aligned(8)));
unsigned char r5sound_mechanical_descriptor[0xc0] __attribute__((aligned(8)));
unsigned char r5sound_mechanical_volume_descriptor[0xc0] __attribute__((aligned(8)));
static unsigned char rows[2][61][0x80] __attribute__((aligned(8)));
static unsigned char volume_rows[2][10][0x80] __attribute__((aligned(8)));
static struct pair menus[4],pairs[2][61],volumes[2][10];
static unsigned initialized,staged[2],gui_revision;
static unsigned first(unsigned g){return g?0x1680u:0x1700u;}
static unsigned vfirst(unsigned g){return g?0x16c0u:0x1740u;}
static unsigned resource(unsigned g){return g?0x02ff4600u:0x02ff4700u;}
static unsigned count(void){unsigned n=r5sound_count();return n>60?60:n;}
static void copy(unsigned char *d,const unsigned char *s,unsigned n){while(n--)*d++=*s++;}
static void word(unsigned char *d,unsigned at,uint32_t v){for(unsigned i=0;i<4;i++)d[at+i]=(unsigned char)(v>>(i*8));}
static void pointer(unsigned char *d,unsigned at,const void *p){uintptr_t v=(uintptr_t)p;for(unsigned i=0;i<sizeof v;i++)d[at+i]=(unsigned char)(v>>(i*8));}
static void refresh(void){if(__atomic_load_n(&initialized,__ATOMIC_ACQUIRE)){
 __atomic_store_n((uint32_t *)(void *)(r5sound_menu_descriptor+0x54),count()+1,__ATOMIC_RELEASE);
 __atomic_store_n((uint32_t *)(void *)(r5sound_mechanical_descriptor+0x54),count()+1,__ATOMIC_RELEASE);
}}
static unsigned yes(void){refresh();return 1;}
static unsigned no(void){return 0;}
static unsigned selected(unsigned g){refresh();unsigned n=r5sound_profile_selected(g);return n<=count()?n:0;}
static unsigned volume(unsigned g){unsigned v=staged[g];if(!v)v=r5sound_profile_volume(g);return (v>=1&&v<=10?v:5)-1;}
unsigned r5sound_menu_selected(void){return selected(1);}
static unsigned mechanical_selected(void){return selected(0);}
void r5sound_menu_stage(unsigned raw){(void)raw;}
static int commit(unsigned g,unsigned alias){unsigned n=alias-first(g);return n<=count()?r5sound_profile_request(g,n):-1;}
int r5sound_menu_commit(unsigned alias){return commit(1,alias);}
static int mechanical_commit(unsigned alias){return commit(0,alias);}
unsigned r5sound_volume_menu_get(void){return volume(1);}
static unsigned mechanical_volume(void){return volume(0);}
void r5sound_volume_menu_stage(unsigned n){if(n<10)staged[1]=n+1;}
static void mechanical_stage(unsigned n){if(n<10)staged[0]=n+1;}
static int volume_commit(unsigned g,unsigned alias){unsigned n=alias-vfirst(g);staged[g]=0;return n<10?r5sound_profile_volume_request(g,n+1):-1;}
int r5sound_volume_menu_commit(unsigned alias){return volume_commit(1,alias);}
static int mechanical_volume_commit(unsigned alias){return volume_commit(0,alias);}
static unsigned electronic_blocked(void){return r5sound_profile_blocked(1)||!r5sound_profile_selected(1);}
static unsigned mechanical_blocked(void){return r5sound_profile_blocked(0)||!r5sound_profile_selected(0);}
unsigned r5sound_menu_gui_changed(void){unsigned r=r5sound_revision(),changed=staged[0]||staged[1]||r!=gui_revision;staged[0]=staged[1]=0;gui_revision=r;return changed;}
unsigned r5sound_menu_row_available(unsigned id){for(unsigned g=0;g<2;g++){
 if(id-vfirst(g)<10)return !(g?electronic_blocked():mechanical_blocked());
 if(id-first(g)<61)return id-first(g)<=count()&&!r5sound_profile_blocked(g);
}return 0;}
static void table(unsigned char *d,unsigned char rows[][0x80],struct pair *p,unsigned first,unsigned names,unsigned total,
                  const void *get,const void *stage,const void *commit,const void *blocked){
 copy(d,r5_native_menu_template,0xc0);word(d,0,names-1);word(d,4,~0u);word(d,8,~0u);
 word(d,0xc,names+63);word(d,0x10,~0u);word(d,0x18,0x20000001);word(d,0x1c,0x20000001);
 word(d,0x20,0x2ed);word(d,0x24,0x4cf);word(d,0x54,total);pointer(d,0x58,rows);
 word(d,0x60,0x020048eb);word(d,0x64,0x39fc);pointer(d,0x70,(void *)yes);pointer(d,0x78,get);
 pointer(d,0x80,stage);pointer(d,0x88,commit);pointer(d,0x90,0);pointer(d,0x98,0);
 pointer(d,0xa0,0);pointer(d,0xa8,blocked);pointer(d,0xb0,0);
 for(unsigned n=0;n<total;n++){
  unsigned char *r=rows[n];copy(r,r5_native_row_template,0x80);
  word(r,0,first+n);word(r,4,first+n);word(r,8,names+n);word(r,0xc,~0u);word(r,0x10,names+63);
  word(r,0x14,~0u);word(r,0x18,0x4cf);word(r,0x20,~0u);word(r,0x24,~0u);word(r,0x28,~0u);word(r,0x2c,~0u);
  word(r,0x34,n);word(r,0x38,0x39fc);r[0x6c]=r[0x6e]=0x36;r[0x6d]=r[0x6f]=0;
  r[0x74]=0x86;r[0x75]=0x10;r[0x76]=0x12;r[0x77]=0;r[0x78]=0x4f;r[0x79]=0;word(r,0x7c,0);
  p[n]=(struct pair){first+n,r};
 }
}
static void initialize(void){if(__atomic_load_n(&initialized,__ATOMIC_ACQUIRE))return;
 table(r5sound_menu_descriptor,rows[1],pairs[1],first(1),resource(1)+1,61,(void *)r5sound_menu_selected,(void *)r5sound_menu_stage,(void *)r5sound_menu_commit,(void *)no);
 table(r5sound_volume_descriptor,volume_rows[1],volumes[1],vfirst(1),resource(1)+0x51,10,(void *)r5sound_volume_menu_get,(void *)r5sound_volume_menu_stage,(void *)r5sound_volume_menu_commit,(void *)electronic_blocked);
 table(r5sound_mechanical_descriptor,rows[0],pairs[0],first(0),resource(0)+1,61,(void *)mechanical_selected,(void *)r5sound_menu_stage,(void *)mechanical_commit,(void *)no);
 table(r5sound_mechanical_volume_descriptor,volume_rows[0],volumes[0],vfirst(0),resource(0)+0x51,10,(void *)mechanical_volume,(void *)mechanical_stage,(void *)mechanical_volume_commit,(void *)mechanical_blocked);
 menus[0]=(struct pair){0x636,r5sound_menu_descriptor};menus[1]=(struct pair){0x637,r5sound_volume_descriptor};
 menus[2]=(struct pair){0x638,r5sound_mechanical_descriptor};menus[3]=(struct pair){0x639,r5sound_mechanical_volume_descriptor};
 __atomic_store_n(&initialized,1,__ATOMIC_RELEASE);refresh();
}
void r5sound_menu_catalog_changed(void){refresh();}
void r5sound_menu_register_extra(void *m){initialize();r5_native_menu_insert(m,menus,menus+4);}
void r5sound_rows_register_extra(void *m){initialize();for(unsigned g=0;g<2;g++){
 r5_native_row_insert(m,pairs[g],pairs[g]+61);r5_native_row_insert(m,volumes[g],volumes[g]+10);
}}
const char *r5sound_menu_text(unsigned id){
 static const char levels[10][5]={"10%","20%","30%","40%","50%","60%","70%","80%","90%","100%"};
 for(unsigned g=0;g<2;g++){
  unsigned b=resource(g),n=id-b;
  if(!n)return g?"电子快门自定义声音":"机械快门自定义声音";
  if(n==0x50)return g?"电子快门自定义音量":"机械快门自定义音量";
  if(n==0x40)return r5sound_profile_status(g);
  if(n==0x90)return "各组独立保存；默认50%；静音优先";
  if(n>=0x51&&n<0x5b)return levels[n-0x51];
  if(n>=1&&n<=61){if(n==1)return "关闭";return n-1<=count()?r5sound_name(n-1):"";}
 }
 return 0;
}
