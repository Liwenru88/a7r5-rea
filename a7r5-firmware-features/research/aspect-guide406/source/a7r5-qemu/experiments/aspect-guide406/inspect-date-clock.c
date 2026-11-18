/* 只调用原厂只读操作 2/3，完整记录时钟返回结构，不设置客体时钟。 */
#define DATE_CLOCK_TEST
#include "seed-date-clock.c"
extern int printf(const char *, ...);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int inspect(int argc, char **argv) {
    (void)argv;
    if (argc != 1) return 2;
    for (unsigned int op = 2; op <= 3; ++op) {
        struct clock_message message;
        if (read_clock(&message, op)) return 3;
        printf("ASPECT406_CLOCK_READ op=%u data=", op);
        for (unsigned int i = 0; i < sizeof message; ++i)
            printf("%02x", bytes(&message)[i]);
        printf("\n");
    }
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(inspect, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
