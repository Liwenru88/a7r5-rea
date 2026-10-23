/* CP capture-ID table protocol; see QEMU-COLD-BOOT-WAIT.md for evidence/limits. */
typedef unsigned int cap_u32;
typedef unsigned long long cap_u64;
struct cap_table { cap_u32 header[5]; unsigned char entries[1024][16]; };
struct cap_service {
    struct cap_table *table;
    cap_u64 address;
    long access_owner;
    int initialized;
};
int cap_control(struct cap_service *, cap_u32, long, unsigned char *, unsigned int *);
int cap_sync(struct cap_service *, const unsigned char *, unsigned int, unsigned char *);
