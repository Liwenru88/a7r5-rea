/* Guest-only power-on record preparation; Backup_save=0 keeps writes in VM RAM. */
typedef unsigned long size_t;
extern int printf(const char *, ...);
extern int Backup_nread(unsigned int, void *, int);
extern int Backup_write(unsigned int, unsigned int, const void *);
extern unsigned long strtoul(const char *, char **, int);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc, char **argv) {
    unsigned int boot_type = 1;
    if (argc > 2) return 2;
    if (argc == 2) {
        char *end;
        unsigned long value = strtoul(argv[1], &end, 0);
        if (*end || value < 1 || value > 8) return 2;
        boot_type = value;
    }
    unsigned int record[32] = {0}, verify[32] = {0};
    int result = Backup_nread(0x0051004a, record, sizeof record);
    if (result != sizeof record) { printf("BOOT_RECORD_READ=%d\n", result); return 3; }
    unsigned int old_type = record[2];
    if (!record[1]) record[1] = 2; /* native k_upm_setup_boot_factor_default uses mode 2 */
    record[2] = boot_type;
    /* ponytail: virtual loader descriptors; use a same-model boot dump for exact geometry. */
    if (!record[3]) record[3] = 1; /* native EECAP enum requires 1..4 */
    if (!record[5]) record[5] = 1; /* native BIS descriptor requires 1 or 2 */
    result = Backup_write(0x51, 0x0051004a, record);
    if (result < 0) { printf("BOOT_RECORD_WRITE=%d\n", result); return 4; }
    result = Backup_nread(0x0051004a, verify, sizeof verify);
    if (result != sizeof verify) { printf("BOOT_RECORD_VERIFY=%d\n", result); return 5; }
    for (unsigned int i = 0; i < 32; ++i) if (verify[i] != record[i]) return 6;
    printf("POWER_ON_RECORD_OK mode=%u boot_type=%u old_type=%u eecap=%u bis=%u\n",
           verify[1], verify[2], old_type, verify[3], verify[5]);
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
