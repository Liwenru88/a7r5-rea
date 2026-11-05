/* 仅在虚拟客体中通过原厂 UPM 接口持有 DEBUG 频率锁，不模拟变频完成。 */
extern int printf(const char *, ...);
extern int osal_valloc_msg_wait(unsigned, void **, unsigned, unsigned);
extern int osal_snd_sync_msg(unsigned, void *);
extern int osal_free_msg(unsigned, void *);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
static int call(unsigned command, unsigned argument) {
    unsigned *message = 0;
    int rc = osal_valloc_msg_wait(0x80920901, (void **)&message, 20, 1);
    if (rc || !message) return 3;
    for (unsigned n = 0; n < 5; ++n) message[n] = 0;
    message[0] = command; message[1] = argument; message[4] = 0x7fffffff;
    rc = osal_snd_sync_msg(0x80920901, message);
    int status = (int)message[4];
    printf("N12_UPM_CALL command=%u argument=%u transport=%d status=%d value=%u\n",
           command, argument, rc, status, message[1]);
    int freed = osal_free_msg(0x80920901, message);
    return rc || status || freed;
}
static int run(int argc, char **argv) {
    (void)argv;
    if (argc != 1) return 2;
    /* 原 upm.ko 的 API 表：6=LOCK_MODE；因子表：10=DEBUG。 */
    if (call(6, 10) || call(2, 0) || call(11, 0)) return 4;
    printf("N12_UPM_FREQUENCY_LOCK_HELD factor=DEBUG scope=guest-only\n");
    return 0;
}
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
