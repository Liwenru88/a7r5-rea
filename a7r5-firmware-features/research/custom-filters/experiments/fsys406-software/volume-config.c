/* 独立实验进程选择原厂文件后端；不提供卷API、CP消息或设备模型。 */
extern void *dlvsym(void *,const char *,const char *);
extern char *getenv(const char *);
extern int printf(const char *,...),fflush(void *);
extern void _exit(int);
static unsigned configured;
unsigned af_volume_configured(void){return configured;}
void mcmn_param_init(void){
    void *(*lookup)(void *,const char *)=dlvsym((void *)-1,"dlsym","GLIBC_2.17");
    void (*original)(void)=lookup?lookup((void *)-1,"mcmn_param_init"):0;
    unsigned (*get)(int)=lookup?lookup((void *)-1,"mcmn_param_getul"):0;
    void (*set)(int,unsigned)=lookup?lookup((void *)-1,"mcmn_param_setul"):0;
    int (*id)(const char *)=lookup?lookup((void *)-1,"mcmn_param_getidfromdesc"):0;
    char *enabled=getenv("AF_FSYS_VOLUME_SOFTWARE");
    if(!original||original==mcmn_param_init||!get||!set||!id||!enabled||enabled[0]!='1'||enabled[1]||id("EXISTMEDIADRIVER")!=0x69)_exit(126);
    original();set(0x69,0);if(get(0x69)||get(0xf9))_exit(126);
    ++configured;printf("AF_VOLUME_FILE_BACKEND enabled=1 call=%u\n",configured);fflush(0);
}
