/* 宿主只测接口契约，不把替身当原Fsys或相机执行证据。 */
#include "af_fsys406.h"
#include "af_sha256.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint8_t snapshot_bytes[0x150],data[32768],original[32768];
static char names[65][800];
static unsigned files,snaps,opens,closes,reads,enum_index;
static int mode,changed,reentered;
static const uint64_t token=UINT64_C(0xfedcba9876543211);
static size_t position;
static unsigned current_file;
static uint8_t *source_out;
static char expected_drive='A';
static const char *expected_root="/Private/Sony/PRO/LUT";
static int (*test_policy)(void *);
static void *test_policy_context;
static AfFsys406 context;
static AfMediaList listing,work;
static void put64(uint8_t *p,uint64_t x){memcpy(p,&x,8);}
static int snapshot(void *p,uint8_t out[0x150]){assert(p==(void *)&snaps);++snaps;memcpy(out,snapshot_bytes,0x150);return 0;}
static int check_path(const char *p){char root[96];snprintf(root,sizeof(root),"%c:%s/",expected_drive,expected_root);assert(strncmp(p,root,strlen(root))==0);return (int)strlen(root);}
static void result(void *v,unsigned at){uint8_t *p=v;memset(p,0,0xc28);put64(p,(uintptr_t)(p+0x5b7));put64(p+8,sizeof(data));memcpy(p+0x5b7,names[at],strlen(names[at])+1);memset(p+0x10,7,22);p[0x26]=0x20;p[0x28]=(uint8_t)expected_drive;put64(p+0x30,at);if(mode==7)put64(p,1);}
static int32_t first(const char *path,uint8_t attr,void *v){int at=check_path(path);assert(attr==0x80);if(mode==6)return (int32_t)0x80000032u;if(!strcmp(path+at,"*.*")){enum_index=0;if(!files)return 2;result(v,0);return 0;}for(unsigned i=0;i<files;++i)if(!strcmp(path+at,names[i])){result(v,i);return 0;}return 2;}
static int32_t next(void *v){if(++enum_index>=files)return 2;result(v,enum_index);return 0;}
static int32_t open_file(const char *path,uint64_t *out,uint32_t flags){int at=check_path(path);assert(flags==1);for(current_file=0;current_file<files;++current_file)if(!strcmp(path+at,names[current_file]))break;assert(current_file<files);++opens;position=0;*out=token+opens;return 0;}
static int32_t read_file(uint64_t h,void *out,int32_t count){assert(h==token+opens);assert(count>0);++reads;if(mode==2)return (int32_t)0x80000032u;if(mode==3)return count+1;if(mode==4)return 0;if(position==sizeof(data))return 0;size_t n=sizeof(data)-position;if(n>(unsigned)count)n=(unsigned)count;memcpy(out,data+position,n);position+=n;return (int32_t)n;}
static int32_t close_file(uint64_t h){assert(h==token+opens);++closes;return mode==5?(int32_t)0x80000032u:0;}
static void setup(unsigned slot){memset(&context,0,sizeof(context));memset(snapshot_bytes,0,sizeof(snapshot_bytes));snapshot_bytes[0x19]='A';snapshot_bytes[0x1c]=3;snapshot_bytes[0x70+0x19]='B';snapshot_bytes[0x70+0x1c]=9;expected_drive=slot?'B':'A';expected_root=slot?"/Sony/PRO/LUT":"/Private/Sony/PRO/LUT";AfFsys406Binding b={1,sizeof(b),slot,0,&snaps,snapshot,{open_file,read_file,close_file,first,next},test_policy_context,test_policy};assert(!af_fsys406_init(&context,&b));assert(snaps==0&&opens==0);AfMediaProvider p;assert(!af_fsys406_provider(&context,&p)&&p.context==&context);files=2;strcpy(names[0],"z.CUBE");strcpy(names[1],"a.cube");memset(data,'A',sizeof(data));memcpy(original,data,sizeof(data));memset(&listing,0xa5,sizeof(listing));}
static int progress(void *p,uint32_t done,uint32_t total){(void)p;assert(total==sizeof(data));if(done&& !reentered){AfMediaList o,w;assert(af_fsys406_scan(&context,9,&w,&o)==AF_BUSY);reentered=1;}if(done==16384&&!changed){if(mode==8){memset(data,'B',sizeof(data));changed=1;}else if(mode==9){snapshot_bytes[0x19]='C';changed=1;}}if(mode==18&&closes==1&&!changed){source_out[0]='Z';changed=1;}if(mode==17&&closes==2){source_out[0]='Z';changed=1;}return mode==10&&done>0;}
static void happy(unsigned slot){setup(slot);assert(!af_fsys406_scan(&context,2,&work,&listing));assert(listing.generation==2&&listing.count==2&&!listing.device&&!listing.inode);assert(!strcmp(listing.entries[0].name,"a.cube"));assert(!listing.entries[0].device&&!listing.entries[0].inode&&!listing.entries[0].mtime&&!listing.entries[0].nanoseconds);uint8_t out[sizeof(data)];AfMediaSource s;memset(&s,0,sizeof(s));assert(!af_fsys406_read(&context,&listing,0,out,sizeof(out),&s,progress,0));assert(s.bytes==sizeof(data)&&!memcmp(out,data,sizeof(data)));uint8_t sha[32];assert(!af_sha256(data,sizeof(data),sha)&&!memcmp(sha,s.sha256,32));assert(opens==2&&closes==2&&reentered);assert(af_fsys406_scan(&context,2,&work,&listing)==AF_STALE);}
static void fail_read(int which){setup(0);assert(!af_fsys406_scan(&context,1,&work,&listing));mode=which;uint8_t out[sizeof(data)];source_out=out;AfMediaSource s;memset(&s,0xa5,sizeof(s));AfMediaSource before=s;int r=af_fsys406_read(&context,&listing,0,out,sizeof(out),&s,progress,0);assert(r<0&&memcmp(&s,&before,sizeof(s))==0);assert(opens==closes);if(mode==8)assert(r==AF_STALE&&changed&&memcmp(out,original,sizeof(data))!=0);if(mode==9)assert(r==AF_STALE&&changed);if(mode==10)assert(r==AF_GRID_CANCELLED);assert(!context.busy);}
static void fail_scan(int which){setup(0);AfMediaList old=listing;mode=which;if(which==11){files=65;for(unsigned i=0;i<files;++i)snprintf(names[i],sizeof(names[i]),"%u.cube",i);}if(which==12)strcpy(names[0],"../bad.cube");if(which==13)strcpy(names[0],"A:bad.cube");if(which==14)strcpy(names[0],"bad?.cube");if(which==15){strcpy(names[0],"\xe4\xb8\xad.cube");}assert(af_fsys406_scan(&context,1,&work,&listing)<0);assert(!memcmp(&listing,&old,sizeof(old))&&!context.listing.generation&&!context.busy);assert(!opens&&!closes);}
static void stale_alias(void){setup(0);assert(!af_fsys406_scan(&context,1,&work,&listing));AfMediaSource s;uint8_t out[sizeof(data)];AfMediaList altered=listing;altered.entries[0].size--;assert(af_fsys406_read(&context,&altered,0,out,sizeof(out),&s,0,0)==AF_STALE);assert(af_fsys406_read(&context,&listing,0,&context,sizeof(context),&s,0,0)==AF_INVALID);assert(af_fsys406_read(&context,&listing,0,out,1,&s,0,0)==AF_MEDIA_CAPACITY);assert(!opens);}
static void mixed_files(void){
 setup(0);files=3;strcpy(names[0],"z.CUBE");strcpy(names[1],"a.A7FILTER");strcpy(names[2],"ignored.BIN");
 assert(!af_fsys406_scan(&context,1,&work,&listing)&&listing.count==2);
 assert(!strcmp(listing.entries[0].name,"a.A7FILTER")&&!strcmp(listing.entries[1].name,"z.CUBE"));
 uint8_t out[sizeof(data)];AfMediaSource metadata;
 assert(!af_fsys406_read(&context,&listing,0,out,sizeof out,&metadata,0,0));
 assert(metadata.bytes==sizeof data&&!memcmp(data,out,sizeof data)&&opens==2&&closes==2);
}
int main(int argc,char **argv){assert(argc==2);int c=atoi(argv[1]);if(c==0||c==1)happy((unsigned)c);else if(c>=2&&c<=10&&c!=6&&c!=7)fail_read(c);else if(c>=6&&c<=15)fail_scan(c);else if(c==16)stale_alias();else if(c==17||c==18)fail_read(c);else if(c==19)mixed_files();else assert(0);printf("PASS fsys406 case=%d; snapshots=%u opens=%u closes=%u reads=%u\n",c,snaps,opens,closes,reads);return 0;}
