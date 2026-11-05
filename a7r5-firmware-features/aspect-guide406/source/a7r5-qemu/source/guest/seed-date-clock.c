/* Initialize the original udate clock through its boot API, then read it back.
 * The initial epoch comes from the original firmware default, not host wall time.
 * No original library/model is patched; Backup_save=0 confines changes to the VM.
 */
typedef unsigned long size_t;
extern int printf(const char *, ...);
extern void *memcpy(void *, const void *, size_t);
extern unsigned int sleep(unsigned int);
extern int osal_snd_sync_direct(unsigned int, void *);

struct clock_message { unsigned long words[6]; };
static unsigned char *bytes(struct clock_message *m) { return (void *)m; }
static unsigned int get16(const unsigned char *p) { return p[0] | (unsigned int)p[1] << 8; }
static void set16(unsigned char *p, unsigned int value) { p[0] = value; p[1] = value >> 8; }
static int leap(unsigned int y) { return !(y % 4) && (y % 100 || !(y % 400)); }
static const unsigned int days[] = {31,28,31,30,31,30,31,31,30,31,30,31};

static int valid(struct clock_message *m) {
    const unsigned char *p = bytes(m) + 20;
    unsigned int year = get16(p), month = p[2], day = p[3];
    if (year < 2000 || year > 2037 || !month || month > 12 || !day || p[12] != 0)
        return 0;
    return day <= days[month - 1] + (month == 2 && leap(year)) &&
           p[4] < 24 && p[5] < 60 && p[6] < 60 && get16(p + 8) < 1000;
}

static long seconds(struct clock_message *m) {
    const unsigned char *p = bytes(m) + 20;
    long n = 0;
    for (unsigned int y = 2000; y < get16(p); ++y) n += 365 + leap(y);
    for (unsigned int month = 1; month < p[2]; ++month) n += days[month - 1] + (month == 2 && leap(get16(p)));
    return (((n + p[3] - 1) * 24 + p[4]) * 60 + p[5]) * 60 + p[6];
}

static int call(struct clock_message *m, unsigned int operation) {
    set16(bytes(m) + 16, operation);
    set16(bytes(m) + 18, 0x7fff); /* A handler must actually set the response. */
    int result = osal_snd_sync_direct(0x90013d, m);
    int status = (short)get16(bytes(m) + 18);
    printf("DATE_CLOCK_CALL op=%u transport=%d status=%d\n", operation, result, status);
    return result || status;
}

static int read_clock(struct clock_message *m, unsigned int operation) {
    *m = (struct clock_message){{48, 0, 0, 0, 0, 0}};
    return call(m, operation);
}

int seed_date_clock(void) {
    struct clock_message current, initial, verified;
    if (read_clock(&current, 2)) return 3;
    const char *source = "existing";
    if (!valid(&current)) {
        /* The observed cold virtual clock has original state 3 (uninitialized).
         * Unknown states must not silently get overwritten. */
        if (bytes(&current)[32] != 3) return 4;
        if (read_clock(&initial, 3) || !valid(&initial)) return 5;
        if (get16(bytes(&initial) + 36) || get16(bytes(&initial) + 38) || get16(bytes(&initial) + 40))
            return 6; /* Only the verified ALLLANG UTC default is supported. */
        long expected = seconds(&initial);
        bytes(&initial)[32] = 1; /* Native UTC base, advanced by original utimer. */
        set16(bytes(&initial) + 44, 4); /* Original BY_BOOT initialization. */
        if (call(&initial, 0) || read_clock(&current, 2) || !valid(&current)) return 7;
        long elapsed = seconds(&current) - expected;
        if (elapsed < 0 || elapsed > 10) return 8;
        source = "firmware-default";
    }
    sleep(2);
    if (read_clock(&verified, 2) || !valid(&verified)) return 9;
    long elapsed = seconds(&verified) - seconds(&current);
    if (elapsed < 1 || elapsed > 10) return 10;
    const unsigned char *p = bytes(&verified) + 20;
    printf("DATE_CLOCK_READY source=%s date=%04u-%02u-%02uT%02u:%02u:%02u elapsed=%ld\n",
           source, get16(p), p[2], p[3], p[4], p[5], p[6], elapsed);
    return 0;
}

#ifndef DATE_CLOCK_TEST
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc, char **argv) { (void)argv; return argc == 1 ? seed_date_clock() : 2; }
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
#endif
