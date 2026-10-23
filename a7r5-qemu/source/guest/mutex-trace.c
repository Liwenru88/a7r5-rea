/* Optional diagnostic: preserve pthread behavior and report only invalid low pointers. */
extern void *dlvsym(void *, const char *, const char *);
extern char *getenv(const char *);
extern int snprintf(char *, unsigned long, const char *, ...);
extern int getpid(void);
extern int open(const char *, int, ...);
extern long write(int, const void *, unsigned long);
extern int close(int);
extern void _exit(int);
static int (*native_lock)(void *);

static int (*resolve(void))(void *) {
    int (*fn)(void *) = dlvsym((void *)-1, "pthread_mutex_lock", "GLIBC_2.17");
    if (!fn) {
        write(2, "MUTEX_TRACE_RESOLVE_FAILED\n", 27);
        _exit(126);
    }
    __atomic_store_n(&native_lock, fn, __ATOMIC_RELEASE);
    return fn;
}
__attribute__((constructor)) static void init(void) { resolve(); }

int pthread_mutex_lock(void *mutex) {
    int (*fn)(void *) = __atomic_load_n(&native_lock, __ATOMIC_ACQUIRE);
    if (!fn) fn = resolve();
    if ((unsigned long)mutex < 4096) {
        char line[160];
        unsigned long *frame = __builtin_frame_address(0);
        unsigned long parent = frame[0], caller2 = 0;
        if (parent >= (unsigned long)frame + 16 && parent - (unsigned long)frame <= 4096 && !(parent & 15))
            caller2 = ((unsigned long *)parent)[1];
        int n = snprintf(line, sizeof line, "MUTEX_TRACE_INVALID pid=%d mutex=%p caller=%p parent=%#lx\n",
                         getpid(), mutex, __builtin_return_address(0), caller2);
        if (n > 0 && (unsigned)n < sizeof line) {
            write(2, line, (unsigned)n);
            const char *console = getenv("MUTEX_TRACE_CONSOLE");
            if (console && console[0] == '1' && !console[1]) {
                int fd = open("/dev/console", 1);
                if (fd >= 0) { write(fd, line, (unsigned)n); close(fd); }
            }
        }
    }
    return fn(mutex);
}
