/* Host protocol tests: no QEMU or shared runtime state. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define DATE_CLOCK_TEST
#define sleep clock_test_sleep
#include "seed-date-clock.c"
#undef sleep

static unsigned char clock_date[16];
static int mode, sets;
unsigned int clock_test_sleep(unsigned int duration) {
    if (mode != 4) clock_date[6] += duration;
    return 0;
}
int osal_snd_sync_direct(unsigned int sid, void *message) {
    struct clock_message *m = message;
    unsigned char *p = bytes(m);
    assert(sid == 0x90013d && m->words[0] == 48 && m->words[1] == 0);
    unsigned int operation = get16(p + 16);
    if (mode == 2 && operation == 3) return -1020;
    if (mode == 7 && operation == 3) return 0; /* Missing handler leaves response sentinel. */
    set16(p + 18, 0);
    if (operation == 2) {
        memcpy(p + 20, clock_date, 16);
    } else if (operation == 3) {
        set16(p + 20, 2023);
        p[22] = mode == 1 ? 2 : 1;
        p[23] = mode == 1 ? 30 : 1;
        if (mode == 5) set16(p + 36, 60);
    } else {
        assert(operation == 0 && get16(p + 44) == 4 && p[32] == 1);
        sets++;
        if (mode != 3) {
            memcpy(clock_date, p + 20, 16);
            clock_date[12] = 0; /* Original GET reply exposes local calendar form. */
        }
    }
    return 0;
}
static void reset(int scenario) {
    mode = scenario;
    sets = 0;
    memset(clock_date, 0, sizeof clock_date);
    clock_date[12] = scenario == 6 ? 2 : 3;
}
int main(void) {
    reset(0);
    assert(seed_date_clock() == 0 && sets == 1 && clock_date[6] == 2);
    for (int scenario = 1; scenario <= 7; ++scenario) {
        reset(scenario);
        assert(seed_date_clock() != 0);
        if (scenario != 3 && scenario != 4) assert(sets == 0);
    }
    reset(0);
    set16(clock_date, 2030);
    clock_date[2] = 3; clock_date[3] = 2; clock_date[12] = 0;
    assert(seed_date_clock() == 0 && sets == 0 && get16(clock_date) == 2030);
    puts("DATE_CLOCK_TEST_PASS: read-back, advancement, invalid data, transport/status errors, existing clock preservation");
    return 0;
}
