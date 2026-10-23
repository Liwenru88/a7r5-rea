/* Select the firmware's existing file backend, only in an explicit standalone test. */
extern void *dlvsym(void *, const char *, const char *);
extern char *getenv(const char *);
extern int printf(const char *, ...);
extern int fflush(void *);
extern void _exit(int);
static unsigned calls;
extern int a7r5_media_rm_enabled(void);
extern int a7r5_media_record(const char *,...);
#define printf a7r5_media_record

unsigned file_media_configured(void) { return calls; }

void mcmn_param_init(void) {
    void *(*lookup)(void *, const char *) = dlvsym((void *)-1, "dlsym", "GLIBC_2.17");
    void (*original)(void) = lookup ? lookup((void *)-1, "mcmn_param_init") : 0;
    unsigned (*get)(int) = lookup ? lookup((void *)-1, "mcmn_param_getul") : 0;
    void (*set)(int, unsigned) = lookup ? lookup((void *)-1, "mcmn_param_setul") : 0;
    int (*id)(const char *) = lookup ? lookup((void *)-1, "mcmn_param_getidfromdesc") : 0;
    if (!original || original == mcmn_param_init || !get || !set || !id ||
        id("EXISTMEDIADRIVER") != 0x69 || id("DBG_DRV_DUMMY_OMIT_WRITE") != 0xf9) {
        printf("FILE_MEDIA_CONFIG_RESOLVE_FAILED\n"); fflush(0); _exit(126);
    }
    original();
    const char *enabled = getenv("A7C2_FILE_MEDIA_TEST");
    if (enabled && enabled[0] == '1' && !enabled[1]) {
        unsigned before = get(0x69);
        set(0x69, 0);
        calls++;
        printf("FILE_MEDIA_CONFIG call=%u EXISTMEDIADRIVER=%u->%u OMIT_WRITE=%u\n",
               calls, before, get(0x69), get(0xf9));
        fflush(0);
    }
}

/* 仅增加原调用的观测，不替代原厂日志及错误码。 */
void fsysDepLog_FuncOut(unsigned operation, unsigned sequence, int result) {
    void *(*lookup)(void *, const char *) = dlvsym((void *)-1, "dlsym", "GLIBC_2.17");
    void (*original)(unsigned,unsigned,int) = lookup ? lookup((void *)-1,"fsysDepLog_FuncOut") : 0;
    if (!original) _exit(126);
    original(operation,sequence,result);
    printf("FSYS_NATIVE_RESULT operation=%#x sequence=%u result=%#x\n",operation,sequence,(unsigned)result);
    fflush(0);
}

int osal_stat_msgq(unsigned id, unsigned *info) {
    void *(*lookup)(void *, const char *) = dlvsym((void *)-1,"dlsym","GLIBC_2.17");
    int (*original)(unsigned,unsigned *) = lookup ? lookup((void *)-1,"osal_stat_msgq") : 0;
    if (!original) _exit(126);
    int result=original(id,info);
    if (id==0x80d9016e || id==0x80cf016d) {
        printf("MEDIA_QUEUE_OBS id=%#x result=%d info=%#x,%#x\n",id,result,
               (!result && info)?info[0]:0,(!result && info)?info[1]:0);
        fflush(0);
    }
    if (id==0x80d9016e && info && a7r5_media_rm_enabled()) {
        info[0]=0;info[1]=1;
        printf("MEDIA_RM_VIRTUAL_ENDPOINT id=%#x enabled=1\n",id);fflush(0);
        return 0;
    }
    return result;
}
