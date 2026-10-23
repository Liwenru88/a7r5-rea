/* Guest-only Backup block reader for evidence extraction: reads a block through the
 * original Backup APIs and hex-dumps it to the console. Nothing is invented; the
 * bytes are whatever the seeded original backup storage returns. */
typedef unsigned long size_t;
extern int printf(const char *, ...);
extern unsigned long strtoul(const char *, char **, int);
extern void *malloc(size_t);
extern int Backup_get_datasize(unsigned int);
extern int Backup_read(unsigned int, void *);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc, char **argv) {
    /* usage: backup-dump <block-id> [max-bytes] */
    if (argc < 2 || argc > 3) return 2;
    char *end;
    unsigned int id = strtoul(argv[1], &end, 0);
    if (*end || !id) return 2;
    unsigned int cap = 2048;
    if (argc == 3) {
        cap = strtoul(argv[2], &end, 0);
        if (*end || !cap || cap > 65536) return 2;
    }
    int size = Backup_get_datasize(id);
    printf("BACKUP_DUMP id=%#x datasize=%d\n", id, size);
    if (size <= 0) return 3;
    void *data = malloc((unsigned int)size);
    if (!data) { printf("BACKUP_DUMP malloc failed\n"); return 4; }
    int result = Backup_read(id, data);
    printf("BACKUP_DUMP read=%d\n", result);
    if (result < 0) return 5;
    unsigned char *bytes = data;
    unsigned int shown = (unsigned int)size < cap ? (unsigned int)size : cap;
    for (unsigned int row = 0; row < shown; row += 16) {
        printf("%08x:", row);
        for (unsigned int i = row; i < row + 16 && i < shown; ++i) printf(" %02x", bytes[i]);
        printf("\n");
    }
    printf("BACKUP_DUMP_DONE shown=%u\n", shown);
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
