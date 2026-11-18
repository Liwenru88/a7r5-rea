/* 仅用于QEMU：复用原语言银行和setter，语言写入只发生于Backup_save=0的客体RAM。 */
static unsigned long qemu_chinese_base;
static unsigned qemu_chinese_done;
static void qemu_chinese_prepare(void *symbol){
 Dl_info info;
 if(qemu_chinese_base || !real_dladdr(symbol,&info) ||
    (unsigned long)symbol-(unsigned long)info.dli_fbase!=0x17feac0UL)__builtin_trap();
 unsigned long b=(unsigned long)info.dli_fbase;
 if(*(unsigned *)(b+0x28b0464)!=0xf002b260 || *(unsigned *)(b+0x1c7a31c)!=0xa9b97bfd ||
    *(unsigned *)(b+0x1bd72e4)!=0xa9be7bfd || *(unsigned *)(b+0x3f3cb80+0x34)!=25)__builtin_trap();
 qemu_chinese_base=b;
 record("AF_QEMU_CHINESE_PREPARED ","native language model=25; same-package fonts; Backup_save=0 guest RAM only");
}
static void qemu_chinese_apply(void){
 if(!qemu_chinese_base || qemu_chinese_done)return;
 if(!ui_thread_id || (unsigned)syscall(178)!=ui_thread_id || create_screen_returned)__builtin_trap();
 const unsigned *(*get)(void)=(void *)(qemu_chinese_base+0x28b0464);
 void (*banks)(unsigned)=(void *)(qemu_chinese_base+0x1bd72e4);
 void (*setter)(unsigned)=(void *)(qemu_chinese_base+0x1c7a31c);
 banks(0xb9b);setter(25);if(*get()!=25)__builtin_trap();
 qemu_chinese_done=1;
 record("AF_QEMU_CHINESE_APPLIED ","model=25 through original banks/setter on original first CreateScreen thread");
}
