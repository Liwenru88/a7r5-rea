/* Seed the InfraIndicator config backup block 0x01120001 with a minimal valid
 * BIN!/CNF! record so the lazy singleton init at libObj+0xc7cfc completes.
 * Parse contract (libObj+0xc77b4..0xc7994): u32[0]=="BIN!", u32[4]==datasize,
 * u32[8]==count1 (array of count1*16), u32[0xc]==count2 (entries of 52 bytes),
 * u32[0x10]=="CNF!". Empty counts allocate zero-length arrays (valid non-null),
 * the factory-empty indicator configuration. Writes stay in VM RAM
 * (Backup_save=0), like seed-power-on. */
typedef unsigned long size_t;
extern int printf(const char *, ...);
extern int Backup_get_datasize(unsigned int);
extern int Backup_write(unsigned int, unsigned int, const void *);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc, char **argv) {
    unsigned char block[20];
    block[0] = 0x42; block[1] = 0x49; block[2] = 0x4e; block[3] = 0x21;       /* "BIN!" */
    block[4] = 20;  block[5] = 0;  block[6] = 0;  block[7] = 0;              /* size == 20 */
    block[8] = 0;   block[9] = 0;  block[10] = 0; block[11] = 0;             /* count1 = 0 */
    block[12] = 0;  block[13] = 0; block[14] = 0; block[15] = 0;             /* count2 = 0 */
    block[16] = 0x43; block[17] = 0x4e; block[18] = 0x46; block[19] = 0x21;  /* "CNF!" */
    int existing = Backup_get_datasize(0x01120001u);
    if (existing > 0) {
        printf("SEED_INDCONF_SKIP existing_datasize=%d\n", existing);
        return 0;
    }
    int result = Backup_write(0x0112, 0x01120001u, block);
    if (result < 0) { printf("SEED_INDCONF_WRITE=%d\n", result); return 3; }
    int verify = Backup_get_datasize(0x01120001u);
    printf("SEED_INDCONF_OK write=%d datasize=%d\n", result, verify);
    return verify > 0 ? 0 : 4;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
