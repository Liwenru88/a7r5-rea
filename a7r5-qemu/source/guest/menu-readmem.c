/* Read-only guest process memory helper for diagnosing an actual IPC wait. */
typedef unsigned long size_t;
extern int printf(const char *, ...);
extern void *fopen(const char *, const char *);
extern int fseek(void *, long, int);
extern size_t fread(void *, size_t, size_t, void *);
extern int fclose(void *);
extern char *fgets(char *, int, void *);
extern int sscanf(const char *, const char *, ...);
extern int snprintf(char *, size_t, const char *, ...);
extern size_t strlen(const char *);
extern char *strstr(const char *, const char *);
extern int strcmp(const char *, const char *);
extern unsigned long strtoul(const char *, char **, int);
extern int *__errno_location(void);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc, char **argv) {
    if (argc < 3 || argc > 8) return 2;
    char *end;
    unsigned long address = strtoul(argv[2], &end, 0);
    if (*end || address > 0x7fffffffffffffffUL) return 2;
    size_t requested = 128;
    if (argc >= 4) {
        requested = strtoul(argv[3], &end, 0);
        if (*end || requested == 0 || requested > 4096) return 2;
    }
    if (argc >= 5) {
        if (!argv[4][0]) return 2;
        char path[256], line[512];
        size_t length = strlen(argv[1]);
        if (length < 4 || length >= 250 || !strstr(argv[1] + length - 4, "/mem")) return 2;
        snprintf(path, sizeof path, "%.*smaps", (int)(length - 3), argv[1]);
        void *maps = fopen(path, "rb");
        if (!maps) return 3;
        unsigned long base = 0;
        while (fgets(line, sizeof line, maps)) {
            unsigned long start, end_address, offset;
            char perms[5];
            if (strstr(line, argv[4]) && sscanf(line, "%lx-%lx %4s %lx", &start, &end_address, perms, &offset) == 4 && offset == 0) {
                base = start;
                break;
            }
        }
        fclose(maps);
        if (!base || address > 0x7fffffffffffffffUL - base) return 3;
        address += base; /* analyzed shared objects have their first PT_LOAD at VA zero */
    }
    void *file = fopen(argv[1], "rb");
    if (!file) { printf("READMEM open error=%d\n", *__errno_location()); return 3; }
    if (fseek(file, address, 0) != 0) {
        printf("READMEM seek error=%d\n", *__errno_location()); fclose(file); return 4;
    }
    if (argc == 6 && (!strcmp(argv[5], "pins") || !strcmp(argv[5], "pins-template"))) {
        /* AppFw+35b7aa0：当前拓扑是 50 个 24 字节记录，只读描述符，不改状态。 */
        if (strcmp(argv[4], "appFw.so") || requested != 1200) { fclose(file); return 2; }
        if (!strcmp(argv[5], "pins-template")) {
            unsigned long pointer;
            if (fread(&pointer,1,8,file)!=8 || !pointer) { fclose(file); return 4; }
            address=pointer;
        }
        printf("PIN_TOPOLOGY_BEGIN kind=%s address=%lx\n",argv[5],address);
        for (unsigned i = 0; i < 50; ++i) {
            unsigned long record[3];unsigned own[4]={0},peer[4]={0};
            if (fseek(file,address+i*24,0) || fread(record,1,24,file)!=24) { fclose(file); return 4; }
            if (record[0] && (fseek(file,record[0],0) || fread(own,1,16,file)!=16)) { fclose(file); return 4; }
            if (record[2] && (fseek(file,record[2],0) || fread(peer,1,16,file)!=16)) { fclose(file); return 4; }
            printf("PIN_ATOM index=%u mode=%u own=%#x,%u,%u,%u peer=%#x,%u,%u,%u\n",
                i,(unsigned)record[1],own[0],own[1],own[2],own[3],peer[0],peer[1],peer[2],peer[3]);
        }
        fclose(file);printf("PIN_TOPOLOGY_DONE count=50 readonly=1\n");return 0;
    }
    if (argc == 6) {
        if (strcmp(argv[5], "follow") != 0) { fclose(file); return 2; }
        unsigned long pointer;
        if (fread(&pointer, 1, sizeof pointer, file) != sizeof pointer || !pointer ||
            pointer > 0x7fffffffffffffffUL || fseek(file, pointer, 0) != 0) {
            fclose(file); return 4;
        }
        address = pointer;
    }
    if (argc >= 5 && argv[4][0] && argc >= 7 && !strcmp(argv[5], "vtscan")) {
        /* vtscan: <addr>=root VA in module, argv[6]=vtable file offset,
           argv[7]=object size. Follow [base+addr] to the object, then report
           every qword in object[0..size) whose pointee starts with the vtable. */
        if (argc < 8) { fclose(file); return 2; }
        unsigned long vtoff = strtoul(argv[6], &end, 0);
        if (*end) { fclose(file); return 2; }
        unsigned long objsize = strtoul(argv[7], &end, 0);
        if (*end || objsize == 0 || objsize > 0x10000) { fclose(file); return 2; }
        /* re-resolve base the same way as above: reopen maps for the module. */
        unsigned long base = 0;
        {
            char path[256], line[512];
            size_t length = strlen(argv[1]);
            if (length < 4 || length >= 250 || !strstr(argv[1] + length - 4, "/mem")) { fclose(file); return 3; }
            snprintf(path, sizeof path, "%.*smaps", (int)(length - 3), argv[1]);
            void *maps = fopen(path, "rb");
            if (!maps) { fclose(file); return 3; }
            while (fgets(line, sizeof line, maps)) {
                unsigned long start, end_address, offset;
                char perms[5];
                if (strstr(line, argv[4]) && sscanf(line, "%lx-%lx %4s %lx", &start, &end_address, perms, &offset) == 4 && offset == 0) {
                    base = start;
                    break;
                }
            }
            fclose(maps);
        }
        if (!base) { fclose(file); return 3; }
        unsigned long vtable = base + vtoff;
        /* address currently = base + root_va (the global holding the object pointer). */
        unsigned long object;
        if (fseek(file, address, 0) != 0 || fread(&object, 1, 8, file) != 8 || !object ||
            object > 0x800000000000UL) { fclose(file); printf("VTSCAN_ROOT_ERROR\n"); return 4; }
        printf("VTSCAN_OBJECT %#lx\n", object);
        unsigned long hits = 0;
        for (unsigned long off = 0; off + 8 <= objsize && hits < 24; off += 8) {
            unsigned long candidate;
            if (fseek(file, object + off, 0) != 0) break;
            if (fread(&candidate, 1, 8, file) != 8) break;
            if (candidate < 0x7f00000000UL || candidate > 0x800000000000UL) continue;
            unsigned long first;
            if (fseek(file, candidate, 0) != 0) continue;
            if (fread(&first, 1, 8, file) != 8) continue;
            if (first == vtable) {
                printf("VTSCAN_MATCH obj_off=%#lx ptr=%#lx\n", off, candidate);
                ++hits;
            }
        }
        fclose(file);
        printf("VTSCAN_DONE vtable=%#lx hits=%lu\n", vtable, hits);
        return hits ? 0 : 6;
    }
    unsigned char data[4096];
    size_t count = fread(data, 1, requested, file);
    fclose(file);
    printf("READMEM %s address=%lx bytes=%lu\n", argv[1], address, count);
    for (size_t row = 0; row < count; row += 16) {
        printf("%016lx:", address + row);
        for (size_t i = row; i < row + 16 && i < count; ++i) printf(" %02x", data[i]);
        printf("\n");
    }
    return count ? 0 : 5;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
