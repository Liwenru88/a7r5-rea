/* 仅宿主函数替身：原UTF8转换器依据另见固定4.06静态收据。 */
#define main original_contract_main
#include "fsys406_contract.c"
#undef main
static unsigned policies,fail_policy;
static int check_policy(void *v){assert(v==&policies);++policies;return policies==fail_policy?AF_STALE:AF_OK;}
static void unicode_setup(void){test_policy=check_policy;test_policy_context=&policies;setup(0);assert(policies==0);}
static void input_hex(char *out,const char *hex){size_t n=strlen(hex);assert(n%2==0&&n/2<768);for(size_t i=0;i<n;i+=2){unsigned c;assert(sscanf(hex+i,"%2x",&c)==1);out[i/2]=(char)c;}out[n/2]=0;}
int main(int argc,char **argv){assert(argc>=2);int which=atoi(argv[1]);unicode_setup();files=1;if(which==0||which==1){assert(argc==3);input_hex(names[0],argv[2]);AfMediaList prior=listing;int r=af_fsys406_scan(&context,1,&work,&listing);if(which==1){assert(r<0&&!memcmp(&listing,&prior,sizeof(prior))&&!context.listing.generation);return 0;}assert(!r&&listing.count==1&&!strcmp(names[0],listing.entries[0].name));uint8_t out[sizeof(data)];AfMediaSource source;assert(!af_fsys406_read(&context,&listing,0,out,sizeof(out),&source,0,0));assert(opens==2&&closes==2&&policies==4&&source.bytes==sizeof(data));assert(!memcmp(out,data,sizeof(data)));return 0;}
 if(which>=2&&which<=5){fail_policy=which==2?1:which==3?2:which==4?3:4;AfMediaList prior=listing;int r=af_fsys406_scan(&context,1,&work,&listing);if(which<=3){assert(r==AF_STALE&&!memcmp(&listing,&prior,sizeof(prior)));return 0;}assert(!r);uint8_t out[sizeof(data)];AfMediaSource source;memset(&source,0xa5,sizeof(source));AfMediaSource before=source;r=af_fsys406_read(&context,&listing,0,out,sizeof(out),&source,0,0);assert(r==AF_STALE&&!memcmp(&source,&before,sizeof(source)));assert(opens==(which==4?0u:2u)&&closes==opens);return 0;}
 if(which==6){context.binding.encoding_context=&work;assert(af_fsys406_scan(&context,1,&work,&listing)==AF_INVALID&&policies==0);context.binding.encoding_context=&listing;assert(af_fsys406_scan(&context,1,&work,&listing)==AF_INVALID&&policies==0);context.binding.encoding_context=&policies;assert(!af_fsys406_scan(&context,1,&work,&listing));uint8_t out[sizeof(data)];AfMediaSource source;context.binding.encoding_context=out;assert(af_fsys406_read(&context,&listing,0,out,sizeof(out),&source,0,0)==AF_INVALID&&policies==2);context.binding.encoding_context=&source;assert(af_fsys406_read(&context,&listing,0,out,sizeof(out),&source,0,0)==AF_INVALID&&policies==2);return 0;}
 assert(0);
}
