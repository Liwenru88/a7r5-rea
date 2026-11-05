#ifndef SONY_QEMU_DMM_SERVICE_H
#define SONY_QEMU_DMM_SERVICE_H
#define DMM_TEST_PHYSICAL 0x41e000000ULL
#define DMM_TEST_SIZE 0x100000U
struct dmm_slot { unsigned int handle, open_count, generation; int allocated; };
struct dmm_service {
    unsigned char *memory;
    unsigned long long physical;
    struct dmm_slot slots[2];
};
int dmm_service_reply(struct dmm_service *, const unsigned char *, unsigned int, unsigned char *);
#endif
