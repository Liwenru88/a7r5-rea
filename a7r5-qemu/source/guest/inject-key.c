/* Guest-only key event injector: deliver one 20-byte InfraInput key message through
 * the original osal message APIs. All fields come from argv so no value is invented
 * by this tool; the caller must supply evidence-backed key_code/status/from_type.
 * The message layout {key_code, sub_key_code, status, ex_info, from_type} matches
 * InfraInput::RecvThread parsing at libObj.so VA 0xd031c..0xd0354. */
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
    /* usage: inject-key <queue> <src> <key_code> <sub_key_code> <status> <ex_info> <from_type> */
    if (argc != 8) { printf("INJECT_KEY_USAGE argc=%d\n", argc); return 2; }
    int ok = 1;
    unsigned int queue = field(argv[1], &ok), src = field(argv[2], &ok);
    unsigned int body[5];
    for (int i = 0; i < 5; ++i) body[i] = field(argv[3 + i], &ok);
    if (!ok || !queue || src == queue) { printf("INJECT_KEY_BAD_ARGS\n"); return 2; }
    void *message = 0;
    int result = osal_valloc_msg_wait(queue, &message, 20, 1);
    if (result || !message) { printf("INJECT_KEY_ALLOC=%d\n", result); return 3; }
    unsigned int *words = message;
    for (int i = 0; i < 5; ++i) words[i] = body[i];
    osal_set_msg_src(message, src);
    result = osal_snd_msg(queue, message);
    /* osal_stat_msgq hits a deliberate null-store trap on this queue family in our
       guest (kernel UIPC service layout), so depth polling was removed again. */
    printf("INJECT_KEY_SEND queue=%#x src=%#x key_code=%#x sub=%#x status=%#x ex=%#x from=%#x result=%d\n",
           queue, src, body[0], body[1], body[2], body[3], body[4], result);
    return result ? 4 : 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
