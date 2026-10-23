#include "a7r5-lease-retry.h"
#include <assert.h>
#include <stdio.h>
static unsigned int calls, pauses, busy;
static int terminal, sleep_error;
static int attempt(void *context) { assert(context==&calls); ++calls; return calls<=busy?-2:terminal; }
static int pause_us(unsigned int delay) { assert(delay==1000); ++pauses; return sleep_error; }
static void check(unsigned int n,int final,int sleep_fail,int expected,unsigned int expected_calls) {
    calls=pauses=0;busy=n;terminal=final;sleep_error=sleep_fail;unsigned int tries=0;
    assert(a7r5_retry_capture(attempt,&calls,pause_us,&tries)==expected);
    assert(calls==expected_calls && tries==calls);
}
int main(void) {
    check(0,0,0,0,1); check(7,0,0,0,8); check(0,-1,0,-1,1);
    check(999,0,0,0,1000); check(1000,0,0,-1,1000); assert(pauses==999);
    check(2,0,-1,-1,1);
    puts("A7R5_LEASE_RETRY_PASS immediate/busy/error/bound/interrupted");
}
