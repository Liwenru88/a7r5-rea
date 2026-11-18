/* Stateful storage emulation, without an image capture producer. */
#include "capid-service.h"
extern void *memcpy(void *, const void *, unsigned long);
_Static_assert(sizeof(struct cap_table) == 0x4014, "CP table layout");
static cap_u32 word(const unsigned char *p) {
    return (cap_u32)p[0] | (cap_u32)p[1] << 8 | (cap_u32)p[2] << 16 | (cap_u32)p[3] << 24;
}
static void put(unsigned char *p, cap_u32 v) {
    for (unsigned int i = 0; i < 4; ++i) p[i] = (unsigned char)(v >> (i * 8));
}
int cap_control(struct cap_service *s, cap_u32 command, long owner,
                unsigned char *reply, unsigned int *size) {
    if (!s->table || !owner || !reply || !size) return -1024;
    *size = 8;
    switch (command) {
    case 0x1000: /* GetTblAddr */
        put(reply + 8, (cap_u32)s->address);
        put(reply + 12, (cap_u32)(s->address >> 32));
        *size = 16;
        break;
    case 0x1001: /* StartAccess */
        if (s->access_owner) return -1020;
        s->access_owner = owner;
        break;
    case 0x1002: /* StopAccess */
        if (s->access_owner != owner) return -1024;
        s->access_owner = 0;
        break;
    case 0x1003: /* Init End has no completion reply. */
        if (s->access_owner || s->table->header[0] != 1024) return -1024;
        s->initialized = 1;
        *size = 0;
        return 0;
    default: return -1024;
    }
    put(reply, 1);
    put(reply + 4, command);
    return 0;
}
int cap_sync(struct cap_service *s, const unsigned char *request,
             unsigned int size, unsigned char *reply) {
    if (!s->table || !request || !reply || size < 16) return -1024;
    cap_u64 address = word(request) | (cap_u64)word(request + 4) << 32;
    if (address != s->address) return -1024;
    cap_u32 operation = word(request + 8), header[5];
    if (operation != 1 && operation != 2 && operation != 3) return -1024;
    if (operation != 2) {
        if (size < 36) return -1024;
        for (int i = 0; i < 5; ++i) header[i] = word(request + 16 + i * 4);
        if (header[0] != 1024 || header[1] > 1023 || header[2] > 1023 || header[3] > 1023)
            return -1024;
        if (operation == 1) {
            memcpy(s->table->header, header, 20);
        } else {
            unsigned int first = request[12] | (unsigned int)request[13] << 8;
            unsigned int last = request[14] | (unsigned int)request[15] << 8;
            if (first > 1023 || last > 1023) return -1024;
            unsigned int count = ((last - first) & 1023) + 1; /* endpoints inclusive */
            if (count > (size - 36) / 16) return -1024;
            for (unsigned int i = 0; i < count; ++i)
                memcpy(s->table->entries[(first + i) & 1023], request + 36 + i * 16, 16);
            /* CP operation 3 preserves its consumption cursor RP. */
            s->table->header[0] = header[0];
            memcpy(s->table->header + 2, header + 2, 12);
        }
    }
    for (int i = 0; i < 5; ++i) put(reply + i * 4, s->table->header[i]);
    put(reply + 20, 0); /* state/entries have been read or written */
    return 0;
}
#ifdef CAPID_SELFTEST
#include <assert.h>
#include <stdio.h>
int main(void) {
    struct cap_table table = {0};
    struct cap_service service = {&table, 0x4102e0000ULL, 0, 0};
    unsigned char request[100] = {0}, reply[24];
    unsigned int size;
    assert(cap_control(&service, 0x1000, 7, reply, &size) == 0 && size == 16);
    assert(word(reply) == 1 && word(reply + 4) == 0x1000 && word(reply + 12) == 4);
    assert(cap_control(&service, 0x1001, 7, reply, &size) == 0 && service.access_owner == 7);
    assert(cap_control(&service, 0x1001, 8, reply, &size) == -1020);
    assert(cap_control(&service, 0x1002, 8, reply, &size) == -1024);
    put(request, 0x102e0000); put(request + 4, 4); put(request + 8, 1);
    put(request + 16, 1024);
    for (int i = 1; i < 4; ++i) put(request + 16 + i * 4, 1023);
    assert(cap_sync(&service, request, 36, reply) == 0 && table.header[1] == 1023);
    put(request + 8, 3); request[12] = 254; request[13] = 3; /* first=1022, last=1 */
    request[14] = 1;
    put(request + 24, 1); put(request + 28, 1);
    for (int i = 0; i < 4; ++i) put(request + 36 + i * 16, 90 + i);
    assert(cap_sync(&service, request, 100, reply) == 0);
    assert(word(table.entries[1022]) == 90 && word(table.entries[1]) == 93);
    assert(table.header[1] == 1023 && table.header[2] == 1);
    put(request + 8, 2);
    assert(cap_sync(&service, request, 16, reply) == 0 && word(reply + 8) == 1);
    put(request + 8, 3);
    assert(cap_sync(&service, request, 99, reply) == -1024);
    put(request + 8, 4);
    assert(cap_sync(&service, request, 16, reply) == -1024);
    put(request, 0); put(request + 8, 2);
    assert(cap_sync(&service, request, 16, reply) == -1024);
    assert(cap_control(&service, 0x1002, 7, reply, &size) == 0 && !service.access_owner);
    assert(cap_control(&service, 0x1003, 7, reply, &size) == 0 && !size && service.initialized);
    assert(cap_control(&service, 0x1004, 7, reply, &size) == -1024);
    puts("CAPID_STORAGE_SELFTEST_PASS");
}
#endif
