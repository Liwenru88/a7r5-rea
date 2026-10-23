/* Guest-only CP event injector: deliver one 48-byte dataflow notification message
 * through the original osal message APIs, exactly like the physical CP would.
 * The message layout matches the AppFw CP event dispatcher at appFw VA
 * 0x34e65f8..0x34e66b8: halfword[0]=frame (0x2003), halfword[1]=code (0x8201
 * completion), halfword[+0xa]=sub (3), word[+0x1c]=event parameter. The receiving
 * queue is the dataflow port stored at appFw+0x910fa1c (observed 0x81cf618b,
 * received by dataflowInfraFramework.so+0x33c5c). All fields come from argv. */
typedef unsigned long size_t;
extern int printf(const char *, ...);
extern unsigned long strtoul(const char *, char **, int);
extern int osal_valloc_msg_wait(unsigned int, void **, unsigned int, int);
extern int osal_set_msg_src(void *, unsigned int);
extern int osal_snd_msg(unsigned int, void *);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static unsigned int field(const char *text, int *ok) {
    char *end;
    unsigned long value = strtoul(text, &end, 0);
    if (*end || value > 0xffffffffUL) { *ok = 0; return 0; }
    return (unsigned int)value;
}
static int run(int argc, char **argv) {
    /* usage: inject-cp-event <queue> <src> <frame> <code> <sub> <param> */
    if (argc != 7) { printf("INJECT_CP_EVENT_USAGE argc=%d\n", argc); return 2; }
    int ok = 1;
    unsigned int queue = field(argv[1], &ok), src = field(argv[2], &ok);
    unsigned int frame = field(argv[3], &ok), code = field(argv[4], &ok);
    unsigned int sub = field(argv[5], &ok), param = field(argv[6], &ok);
    if (!ok || !queue || (frame & ~0xffff) || (code & ~0xffff) || (sub & ~0xffff)) {
        printf("INJECT_CP_EVENT_BAD_ARGS\n");
        return 2;
    }
    void *message = 0;
    int result = osal_valloc_msg_wait(queue, &message, 48, 1);
    if (result || !message) { printf("INJECT_CP_EVENT_ALLOC=%d\n", result); return 3; }
    unsigned char *bytes = message;
    for (int i = 0; i < 48; ++i) bytes[i] = 0;
    bytes[0] = frame & 0xff; bytes[1] = frame >> 8;
    bytes[2] = code & 0xff;  bytes[3] = code >> 8;
    bytes[0xa] = sub & 0xff; bytes[0xb] = sub >> 8;
    bytes[0x1c] = param & 0xff; bytes[0x1d] = (param >> 8) & 0xff;
    bytes[0x1e] = (param >> 16) & 0xff; bytes[0x1f] = param >> 24;
    bytes[8] = param & 0xff;  /* HDMI hotplug path reads its state byte at +8 */
    bytes[9] = (param >> 8) & 0xff;
    osal_set_msg_src(message, src);
    result = osal_snd_msg(queue, message);
    printf("INJECT_CP_EVENT_SEND queue=%#x src=%#x frame=%#x code=%#x sub=%u param=%#x result=%d\n",
           queue, src, frame, code, sub, param, result);
    return result ? 4 : 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
