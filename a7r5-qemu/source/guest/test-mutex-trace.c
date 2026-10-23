extern int pthread_mutex_lock(void *);
extern int pthread_mutex_unlock(void *);
extern int puts(const char *);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc, char **argv) {
    (void)argv;
    if (argc > 1) return pthread_mutex_lock((void *)0x2a0);
    unsigned long mutex[8] = {0};
    for (int i = 0; i < 3; i++)
        if (pthread_mutex_lock(mutex) || pthread_mutex_unlock(mutex)) return 1;
    puts("MUTEX_TRACE_VALID_PASS");
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
