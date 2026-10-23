/* Test-only dump of an InfraInput receive context: stops the thread briefly, reads x19,
   then prints the 80-byte-stride handler records it dispatches on.
   Layout comes from libObj.so+0xcdb40 (infra_input_res):
     [x19+0x28] = queue id it polls        (self-check: must match the thread's RCV_SITE queue)
     [x19+0x40] = handler table count
     [x19+0x48] = handler table base
     entry = base + index*80 ; [entry+0x04] = message code matched by the dispatcher
                                [entry+0x14] = value copied into the record
   Read-only: never writes guest memory. */
typedef unsigned long size_t;
struct iovec { void *base; size_t length; };
struct user_regs { unsigned long x[31], sp, pc, pstate; };
extern int printf(const char *, ...);
extern int snprintf(char *, size_t, const char *, ...);
extern unsigned long strtoul(const char *, char **, int);
extern char *strrchr(const char *, int);
extern long syscall(long, ...);
extern int *__errno_location(void);
extern void *fopen(const char *, const char *);
extern int fseek(void *, long, int);
extern size_t fread(void *, size_t, size_t, void *);
extern int fclose(void *);
extern void _exit(int);
extern unsigned int alarm(unsigned int);
extern void (*signal(int, void (*)(int)))(int);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int traced;
static void timeout(int signum) {
    (void)signum;
    if (traced) syscall(117, 17, traced, 0, 0); /* DETACH */
    _exit(6);
}
static int snapshot(int tid, struct user_regs *regs) {
    signal(14, timeout);
    alarm(3);
    if (syscall(117, 16, tid, 0, 0) < 0) { alarm(0); return 3; } /* ATTACH */
    traced = tid;
    int status = 0;
    long waited = syscall(260, tid, &status, 0x40000000, 0); /* wait4, __WALL */
    struct iovec vec = {regs, sizeof *regs};
    long rc = -1;
    if (waited == tid && (status & 255) == 127)
        rc = syscall(117, 0x4204, tid, 1, &vec); /* GETREGSET, NT_PRSTATUS */
    int saved_errno = *__errno_location();
    long detached = syscall(117, 17, tid, 0, 0);
    traced = 0;
    alarm(0);
    if (rc < 0 || detached < 0 || vec.length != sizeof *regs) {
        printf("INPUT_ERROR tid=%d wait=%ld status=%d read=%ld errno=%d detach=%ld bytes=%lu\n",
               tid, waited, status, rc, saved_errno, detached, vec.length);
        return 5;
    }
    return 0;
}
static int read_block(void *mem, unsigned long address, void *out, size_t length) {
    if (fseek(mem, (long)address, 0)) return 0;
    return fread(out, length, 1, mem) == 1;
}
/* The thread is stopped inside libosal_rcv_msg_tmo, and x19 there belongs to that callee's
   own frame - not to infra_input_res. So the receive context is found by scanning the
   thread stack for a word V that satisfies the dispatch structure at once:
   [V+0x28] is one of the known input queue ids, [V+0x40] is a small count and
   [V+0x48] is a plausible user pointer. Three consistent fields; a wrong V has to
   satisfy all three by accident. */
static const unsigned int known_queues[] = {
    0x7ae118, 0x7ae098, 0x7ae096, 0x7ae094, 0x7ae092, 0x7ae090, 0x7ae08e, 0x7ae08c,
    0x7a804c, 0x807a0020, 0x807a0027, 0x807a0028, 0x807a018c,
};
static int is_known_queue(unsigned int id) {
    for (unsigned int i = 0; i < sizeof known_queues / sizeof known_queues[0]; ++i)
        if (known_queues[i] == id) return 1;
    return 0;
}
static int dump_table(void *mem, int tid, unsigned long context) {
    unsigned int queue = 0, count = 0;
    unsigned long base = 0;
    if (!read_block(mem, context + 0x28, &queue, 4) ||
        !read_block(mem, context + 0x40, &count, 4) ||
        !read_block(mem, context + 0x48, &base, 8)) {
        printf("INPUT_UNREADABLE tid=%d context=%#lx\n", tid, context);
        return 0;
    }
    printf("INPUT_CTX tid=%d context=%#lx queue=%#x count=%u base=%#lx\n", tid, context, queue, count, base);
    if (base < 0x1000 || base > 0x7fffffffffffUL || count == 0 || count > 4096) {
        printf("INPUT_TABLE_REJECTED tid=%d base=%#lx count=%u\n", tid, base, count);
        return 0;
    }
    unsigned int shown = count > 4096 ? 4096 : count;
    unsigned int bound = 0, printed = 0;
    for (unsigned int index = 0; index < shown; ++index) {
        unsigned char record[80];
        if (!read_block(mem, base + (unsigned long)index * 80, record, sizeof record)) {
            printf("INPUT_ENTRY_UNREADABLE tid=%d index=%u\n", tid, index);
            break;
        }
        unsigned int code, value;
        unsigned long field20, field28;
        __builtin_memcpy(&code, record + 0x04, 4);
        __builtin_memcpy(&value, record + 0x14, 4);
        __builtin_memcpy(&field20, record + 0x20, 8);
        __builtin_memcpy(&field28, record + 0x28, 8);
        /* 0x7fffffff is the observed unbound marker; only interesting entries are printed so a
           1084 entry table does not drown the console log. */
        if (value != 0x7fffffffU || field20) {
            ++bound;
            printf("INPUT_ENTRY tid=%d index=%u code=%#x value=%#x f20=%#lx f28=%#lx\n",
                   tid, index, code, value, field20, field28);
            ++printed;
        }
    }
    printf("INPUT_SUMMARY tid=%d count=%u scanned=%u interesting=%u\n", tid, count, shown, bound);
    if (count > shown) printf("INPUT_TRUNCATED tid=%d shown=%u count=%u\n", tid, shown, count);
    return 1;
}
static int run(int argc, char **argv) {
    if (argc != 2) return 2;
    char *number = strrchr(argv[1], '/'), *end;
    unsigned long parsed = strtoul(number ? number + 1 : argv[1], &end, 10);
    if (*end || !parsed || parsed > 2147483647UL) return 2;
    int tid = (int)parsed;
    struct user_regs regs;
    int rc = snapshot(tid, &regs);
    if (rc) return rc;
    char path[64];
    snprintf(path, sizeof path, "/proc/%d/mem", tid);
    void *mem = fopen(path, "rb");
    if (!mem) return 3;
    if (dump_table(mem, tid, regs.x[19])) { fclose(mem); return 0; }
    unsigned long stack = regs.sp & ~7UL;
    unsigned long limit = stack + 0x10000UL;
    int found = 0;
    for (unsigned long address = stack; address < limit && !found; address += 8) {
        unsigned long candidate = 0;
        if (!read_block(mem, address, &candidate, 8)) break;
        if (candidate < 0x10000000UL || candidate > 0x7fffffffffffUL) continue;
        unsigned int queue = 0;
        if (!read_block(mem, candidate + 0x28, &queue, 4) || !is_known_queue(queue)) continue;
        printf("INPUT_SEARCH tid=%d slot=%#lx candidate=%#lx queue=%#x\n", tid, address, candidate, queue);
        if (dump_table(mem, tid, candidate)) found = 1;
    }
    if (!found) printf("INPUT_NOT_FOUND tid=%d sp=%#lx x19=%#lx\n", tid, regs.sp, regs.x[19]);
    fclose(mem);
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
