/* Test-only register snapshot: briefly stop a guest thread, read, detach. */
typedef unsigned long size_t;
struct iovec { void *base; size_t length; };
struct user_regs { unsigned long x[31], sp, pc, pstate; };
extern int printf(const char *, ...);
extern int snprintf(char *, size_t, const char *, ...);
extern unsigned long strtoul(const char *, char **, int);
extern char *strrchr(const char *, int);
extern int strcmp(const char *, const char *);
extern long syscall(long, ...);
extern int *__errno_location(void);
extern void *fopen(const char *, const char *);
extern int fseek(void *, long, int);
extern size_t fread(void *, size_t, size_t, void *);
extern int fclose(void *);
extern int fork(void);
extern int getpid(void);
extern int kill(int, int);
extern int waitpid(int, int *, int);
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
static int snapshot(int tid, int already_traced, struct user_regs *regs) {
    signal(14, timeout);
    alarm(3);
    if (!already_traced && syscall(117, 16, tid, 0, 0) < 0) { alarm(0); return 3; }
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
        printf("REGS_ERROR tid=%d wait=%ld status=%d read=%ld errno=%d detach=%ld bytes=%lu\n",
               tid, waited, status, rc, saved_errno, detached, vec.length);
        return 5;
    }
    return 0;
}
static int run(int argc, char **argv) {
    if (argc != 2) return 2;
    struct user_regs regs;
    if (!strcmp(argv[1], "--selftest")) {
        int child = fork();
        if (child < 0) return 3;
        if (!child) {
            if (syscall(117, 0, 0, 0, 0) < 0) _exit(3); /* TRACEME */
            kill(getpid(), 19); /* SIGSTOP */
            _exit(0);
        }
        int rc = snapshot(child, 1, &regs), status = 0;
        if (rc) kill(child, 9);
        waitpid(child, &status, 0);
        if (rc || status || !regs.pc || !regs.sp) return 5;
        printf("REGS_SELFTEST_PASS\n");
        return 0;
    }
    char *number = strrchr(argv[1], '/'), *end;
    unsigned long parsed = strtoul(number ? number + 1 : argv[1], &end, 10);
    if (*end || !parsed || parsed > 2147483647UL) return 2;
    int tid = (int)parsed;
    int rc = snapshot(tid, 0, &regs);
    if (rc) return rc;
    printf("REGS tid=%d pc=%lx lr=%lx sp=%lx fp=%lx\n", tid, regs.pc, regs.x[30], regs.sp, regs.x[29]);
    char path[64];
    snprintf(path, sizeof path, "/proc/%d/mem", tid);
    void *mem = fopen(path, "rb");
    if (!mem) return 3;
    unsigned long fp = regs.x[29];
    for (int i = 0; i < 32; ++i) {
        unsigned long frame[2];
        if (fp < regs.sp || fp - regs.sp > 1048576 || fp % 16 ||
            fseek(mem, fp, 0) || fread(frame, sizeof frame, 1, mem) != 1) break;
        printf("FRAME tid=%d fp=%lx savedfp=%lx lr=%lx\n", tid, fp, frame[0], frame[1]);
        if (frame[0] <= fp) break;
        fp = frame[0];
    }
    fclose(mem);
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
