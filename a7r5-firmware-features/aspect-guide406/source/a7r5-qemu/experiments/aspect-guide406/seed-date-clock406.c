/* 当前 ALLLANG 种子默认 UTC+09:00；通过原厂 BY_BOOT API 启动时钟，保留时区。 */
#define DATE_CLOCK_TEST
#include "seed-date-clock.c"
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");

static int run406(int argc, char **argv) {
    (void)argv;
    if (argc != 1) return 2;
    struct clock_message current, initial, verified;
    if (read_clock(&current, 2)) return 3;
    if (valid(&current)) return 4; /* 本实验只接受已观察到的冷启动未初始化状态。 */
    if (bytes(&current)[32] != 3) return 5;
    if (read_clock(&initial, 3) || !valid(&initial)) return 6;
    if (get16(bytes(&initial)+36) != 540 || get16(bytes(&initial)+38) ||
        get16(bytes(&initial)+40)) return 7;
    long expected_local = seconds(&initial);
    unsigned char *p = bytes(&initial)+20;
    unsigned int year = get16(p), month = p[2], day = p[3];
    int minute = (int)p[4]*60+p[5]-540;
    /* 内核 udate_get_localtime 在运行的 UTC 基准上加时区；先把默认本地日期转成 UTC。 */
    while (minute < 0) {
        minute += 1440;
        if (day > 1) --day;
        else {
            if (month > 1) --month;
            else { month = 12; --year; }
            day = days[month-1]+(month == 2 && leap(year));
        }
    }
    if (year < 2000 || year > 2037) return 8;
    set16(p, year); p[2] = month; p[3] = day;
    p[4] = (unsigned int)minute/60; p[5] = (unsigned int)minute%60;
    bytes(&initial)[32] = 1;
    set16(bytes(&initial)+44, 4);
    printf("ASPECT406_CLOCK_PROFILE timezone_minutes=540 dst_minutes=0 source=original-default UTC=%04u-%02u-%02uT%02u:%02u\n",
           year, month, day, p[4], p[5]);
    if (call(&initial, 0) || read_clock(&current, 2) || !valid(&current)) return 9;
    if (get16(bytes(&current)+36) != 540 || get16(bytes(&current)+38) ||
        get16(bytes(&current)+40)) return 10;
    long elapsed = seconds(&current)-expected_local;
    if (elapsed < 0 || elapsed > 10) return 11;
    sleep(2);
    if (read_clock(&verified, 2) || !valid(&verified)) return 12;
    elapsed = seconds(&verified)-seconds(&current);
    if (elapsed < 1 || elapsed > 10) return 13;
    printf("ASPECT406_CLOCK_READY timezone_preserved=540 elapsed=%ld original_api=BY_BOOT\n", elapsed);
    return 0;
}

__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run406, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
