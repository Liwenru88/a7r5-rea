/* 在独立 ARM QEMU 中执行冻结 CP 接收器。只有 OSAL 和共享堆为模拟服务。 */
typedef unsigned int u32;
typedef unsigned char u8;
static u32 input_size,output_size,heap_used,heap_count,ack_count;
static u8 input[4112] __attribute__((aligned(8))),output[4096];
static u32 semi(u32 op,void *p){register u32 r0 __asm__("r0")=op;register void *r1 __asm__("r1")=p;__asm__ volatile("svc #0xab":"+r"(r0):"r"(r1):"memory");return r0;}
static void text(const char *s){semi(4,(void *)s);}
static void hex(char **p,u32 v,unsigned n){const char *h="0123456789abcdef";while(n--)*(*p)++=h[(v>>(n*4))&15];}
static void finish(u32 rc){u32 a[2]={0x20026,rc};semi(0x20,a);for(;;){}}
void cp_exception_main(u32 a,u32 b,u32 c,u32 d){char s[96],*p=s;*p++='E';*p++=' ';hex(&p,a,8);hex(&p,b,8);hex(&p,c,8);hex(&p,d,8);*p++='\n';*p=0;text(s);finish(86);}
static void *allocate(u32 n){if(!n||n>1048576-heap_used)return 0;void *p=(void *)(0x04000000+heap_count*0x80000);heap_used+=n;heap_count++;return p;}
static u32 size(const void *p){(void)p;return input_size;}
static int alloc(u32 q,void **out,u32 n,u32 flags){(void)flags;if(q!=0x80020002||n>sizeof(output))return -1;output_size=n;*out=output;return 0;}
static void source(void *p,u32 q){if(p!=output||q!=0x90030001)finish(91);}
static int send(u32 q,void *p){if(q!=0x80020002||p!=output)finish(92);ack_count++;return 0;}
static int free_msg(u32 q,void *p){(void)q;(void)p;return 0;}
static void hook(u32 at,void *fn,int thumb){volatile u32 *p=(void *)at;p[0]=thumb?0xf000f8df:0xe51ff004;p[1]=(u32)fn;}
extern void boot_copy(void);
__asm__(".thumb\n.global boot_copy\n.thumb_func\nboot_copy:\npush {r4,lr}\nmovw r4,#0\nmovt r4,#0x0310\nmovw ip,#0x8f8d\nmovt ip,#0x10\nblx ip\npop {r4,pc}\n");
static int read_all(u32 fd,u8 *p,u32 n){while(n){u32 a[3]={fd,(u32)p,n};u32 left=semi(6,a);if(left>n||left==n)return 0;p+=n-left;n=left;}return 1;}
void cp_probe_main(void){
    u32 vectors=0x03030000;__asm__ volatile("mcr p15,0,%0,c12,c0,0\nisb"::"r"(vectors):"memory");
    /* 明确将128MiB测试RAM设为Normal；MMU关闭的默认Device类型拒绝非对齐STR。 */
    volatile u32 *l1=(void *)0x03000000;
    for(u32 i=0;i<4096;i++)l1[i]=(i<<20)|(i<128?0x11c02u:0xc02u);
    u32 ttbr=0x03000000,zero=0,domains=~0u;
    __asm__ volatile("dsb sy\nmcr p15,0,%0,c2,c0,0\nmcr p15,0,%1,c2,c0,2\nmcr p15,0,%2,c3,c0,0\nmcr p15,0,%1,c8,c7,0\nisb"::"r"(ttbr),"r"(zero),"r"(domains):"memory");
    u32 sctlr;__asm__ volatile("mrc p15,0,%0,c1,c0,0":"=r"(sctlr));sctlr=((sctlr|(1u<<22)|1u)&~2u);
    __asm__ volatile("mcr p15,0,%0,c1,c0,0\nisb"::"r"(sctlr):"memory");
    boot_copy();
    hook(0x5ef69c,allocate,0);hook(0xbaad0c,size,1);hook(0x53c220,alloc,1);
    hook(0xbaaaa0,source,1);hook(0x53bb54,send,1);hook(0x53c31c,free_msg,1);
    __asm__ volatile("dsb sy\nisb":::"memory");
    u32 open_args[3]={(u32)":tt",0,3};u32 fd=semi(1,open_args);
    if(fd==(u32)-1)finish(93);text("N12_CP_READY\n");
    for(;;){
        if(!read_all(fd,(u8 *)&input_size,4))finish(94);
        if(!input_size){text("N12_CP_STOP\n");finish(0);}
        if(input_size>4096||!read_all(fd,input,input_size))finish(95);
        ack_count=0;output_size=0;
        int consumed=((int(*)(const u8 *,u32))0x1195271)(input,0x80020002);
        char s[8400],*p=s;const char *tag="N12_CP_REPLY ";while(*tag)*p++=*tag++;
        hex(&p,(u32)consumed,8);*p++=' ';hex(&p,heap_used,8);*p++=' ';hex(&p,heap_count,8);*p++=' ';
        /* 原CP实际发布的view和选择控制字段，不能用请求中的编号替代。 */
        u32 active=*(volatile u32 *)0x1a39458,selected=0xffffffff;
        if(active>=0x04000000&&active<0x04100000-24&&*(volatile u32 *)active==0x423f17e1)selected=*(volatile u32 *)(active+8);
        hex(&p,active,8);*p++=' ';hex(&p,selected,8);*p++=' ';hex(&p,*(volatile u32 *)0x1a39464,8);*p++=' ';
        if(ack_count>1)finish(96);
        for(u32 i=0;i<(ack_count?output_size:0);i++)hex(&p,output[i],2);
        *p++='\n';*p=0;text(s);
    }
}
