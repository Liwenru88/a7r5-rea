/* av-cam.bin file+0x2ffb14 handler, mapping tables file+0x3320d8/0x3323d8. */
typedef unsigned long long sa_u64;
static const sa_u64 mappings[3][3] = {
    {0x400000000ULL, 0, 0x100000000ULL},
    {0x500000000ULL, 0x100000000ULL, 0x100000000ULL},
    {0xfe000000ULL, 0x3fe000000ULL, 0x6c0000ULL},
};
static sa_u64 read64(const unsigned char *p) {
    sa_u64 value = 0;
    for (unsigned int i = 0; i < 8; ++i) value |= (sa_u64)p[i] << (i * 8);
    return value;
}
int sa_address_reply(const unsigned char *request, unsigned char *reply) {
    if (!request || !reply || request[0] != 0x50 || request[1] != 0xb8) return -1024;
    for (unsigned int i = 0; i < 80; ++i) reply[i] = 0;
    for (unsigned int i = 0; i < 4; ++i) reply[i] = request[i];
    unsigned int count = request[4] | (unsigned int)request[5] << 8;
    unsigned int reverse = request[6] | (unsigned int)request[7] << 8;
    if (count > 8 || reverse > 1) { reply[6] = 1; reply[7] = 0x11; return 0; }
    reply[8] = (unsigned char)count;
    for (unsigned int i = 0; i < count; ++i) {
        sa_u64 input = read64(request + 16 + i * 8), output = 0;
        int found = 0;
        for (unsigned int j = 0; j < 3; ++j) {
            sa_u64 source = mappings[j][reverse], target = mappings[j][1 - reverse];
            if (input >= source && input - source < mappings[j][2]) {
                output = input - source + target;
                found = 1;
                break;
            }
        }
        /* Unmapped inputs fail explicitly; original handler logs then returns zero. */
        if (!found) { reply[6] = 1; reply[7] = 6; return 0; }
        for (unsigned int k = 0; k < 8; ++k) reply[16 + i * 8 + k] = (unsigned char)(output >> (k * 8));
    }
    return 0;
}
#ifdef SA_ADDRESS_SELFTEST
#include <assert.h>
#include <stdio.h>
static void put64(unsigned char *p, sa_u64 value) {
    for (unsigned int i = 0; i < 8; ++i) p[i] = value >> (8 * i);
}
int main(void) {
    unsigned char request[80] = {0x50, 0xb8, 0, 0, 1}, reply[80];
    put64(request + 16, 0x4ffd81000ULL);
    assert(sa_address_reply(request, reply) == 0 && !reply[6] && read64(reply + 16) == 0xffd81000ULL);
    request[6] = 1; put64(request + 16, 0xffd81000ULL);
    assert(sa_address_reply(request, reply) == 0 && !reply[6] && read64(reply + 16) == 0x4ffd81000ULL);
    request[6] = 0; request[4] = 3;
    put64(request + 16, 0x500000000ULL); put64(request + 24, 0x5ffffffffULL); put64(request + 32, 0xfe000020ULL);
    assert(sa_address_reply(request, reply) == 0 && !reply[6]);
    assert(read64(reply + 16) == 0x100000000ULL && read64(reply + 24) == 0x1ffffffffULL);
    assert(read64(reply + 32) == 0x3fe000020ULL);
    request[4] = 1; put64(request + 16, 0x600000000ULL);
    assert(sa_address_reply(request, reply) == 0 && reply[6] == 1);
    request[4] = 9;
    assert(sa_address_reply(request, reply) == 0 && reply[7] == 0x11);
    request[4] = 0; request[6] = 2;
    assert(sa_address_reply(request, reply) == 0 && reply[6] == 1);
    request[6] = 0;
    assert(sa_address_reply(request, reply) == 0 && !reply[6]);
    puts("SA_ADDRESS_SELFTEST_PASS");
}
#endif
