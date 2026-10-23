/* Guest-only memory scanner: resolve a library's file offset to a runtime VA
 * via /proc/<pid>/maps, then scan all readable mappings of that process for
 * the 64-bit value. Self-contained to avoid shell-side hex arithmetic. */
typedef unsigned long size_t;
extern int printf(const char *, ...);
extern unsigned long strtoul(const char *, char **, int);
extern int open(const char *, int);
extern long lseek(int, long, int);
extern long read(int, void *, unsigned long);
extern int close(int);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
/* Substring search that stops at the end of the map line: the buffer holds the whole maps
   file, so a plain NUL-terminated search would keep matching into later lines and make every
   earlier mapping look like it belongs to the library. */
static int contains(const char *line, int length, const char *name) {
    if (length <= 0) return 0;
    for (int start = 0; start + 1 <= length; ++start) {
        int i = 0;
        while (i < length - start && name[i] && line[start + i] == name[i]) ++i;
        if (!name[i]) return 1;
    }
    return 0;
}
static unsigned long long parse_hex(const char **p) {
    unsigned long long v = 0;
    int any = 0;
    while (1) {
        char c = **p;
        int d = (c >= '0' && c <= '9') ? c - '0' : (c >= 'a' && c <= 'f') ? c - 'a' + 10 : (c >= 'A' && c <= 'F') ? c - 'A' + 10 : -1;
        if (d < 0) break;
        v = v * 16 + d; any = 1; ++(*p);
    }
    (void)any;
    return v;
}
static void skip_spaces(const char **p) {
    while (**p == ' ' || **p == '\t') ++(*p);
}
/* Scan one mapping via the mem fd. */
static unsigned long long scan_range(int mem, unsigned long long lo, unsigned long long hi,
                                     unsigned long long value, unsigned long long max_hits,
                                     unsigned long long *hits) {
    static unsigned char buf[65536];
    unsigned long long done = 0, found = 0;
    while (lo + done < hi && found < max_hits) {
        unsigned long chunk = hi - (lo + done);
        if (chunk > sizeof buf) chunk = sizeof buf;
        if (lseek(mem, (long)(lo + done), 0) < 0) break;
        long got = read(mem, buf, chunk);
        if (got <= 0) {
            /* demand-paged regions (jemalloc reservations) OOM the tiny guest;
               skip ahead by 1MB instead of stopping the whole scan. */
            done += 0x100000;
            continue;
        }
        for (long i = 0; i + 8 <= got; i += 8) {
            unsigned long long v = 0;
            for (int k = 0; k < 8; ++k) v = (v << 8) | buf[i + 7 - k];
            if (v == value) {
                if (hits) hits[found] = lo + done + i;
                ++found;
                if (found >= max_hits) break;
            }
        }
        done += got;
    }
    return found;
}
static int run(int argc, char **argv) {
    /* usage: menu-scanmem /proc/<pid>/mem <libname> <lib-file-offset> [--chain]
       --chain: for every hit H (a vtable's typeinfo slot), rescan for the vtable pointer
       H-8 and report each object that carries it. Read-only; no guest code is called. */
    if (argc != 4 && argc != 5) { printf("SCANMEM_USAGE argc=%d\n", argc); return 2; }
    int chain = argc == 5 && argv[4][0] == '-' && argv[4][1] == '-' ;
    const char *libname = argv[2];
    char *end;
    unsigned long long want_off = strtoul(argv[3], &end, 0);
    /* derive maps path from mem path: replace trailing "mem" with "maps" */
    char maps[128];
    int n = 0;
    while (argv[1][n] && n < 120) { maps[n] = argv[1][n]; ++n; }
    maps[n] = 0;
    if (n >= 3 && maps[n-3]=='m' && maps[n-2]=='e' && maps[n-1]=='m') {
        maps[n-1] = 0; maps[n-2] = 0; maps[n-3] = 0;
        int m = n - 3;
        const char *tail = "maps";
        for (int k = 0; k < 4; ++k) maps[m + k] = tail[k];
        maps[m + 4] = 0;
    } else { printf("SCANMEM_BAD_MEM_PATH\n"); return 2; }
    int mf = open(maps, 0);
    if (mf < 0) { printf("SCANMEM_MAPS_OPEN=%d\n", mf); return 3; }
    char line[512];
    char chunk[4096];
    long tot = 0;
    /* the process maps file is ~90 KB for the camera app; 64 KB truncated it and made the
       parser match a cut-off line, so keep this comfortably larger than any real maps. */
    static char all[1 << 20];
    long cap = 0;
    while (cap < (long)sizeof all - 1) {
        long got = read(mf, all + cap, sizeof all - 1 - cap);
        if (got <= 0) break;
        cap += got;
    }
    all[cap] = 0;
    int truncated = cap >= (long)sizeof all - 1;
    close(mf);
    if (truncated) printf("SCANMEM_MAPS_TRUNCATED bytes=%ld\n", cap);
    /* find libname's mapping covering want_off: base + (want_off - file_off) */
    unsigned long long target = 0;
    const char *p = all;
    while (*p) {
        const char *e = p;
        while (*e && *e != '\n') ++e;
        int linelen = e - p;
        if (linelen > 0 && linelen < 500 && contains(p, linelen, libname)) {
            const char *q = p;
            unsigned long long lo = parse_hex(&q);
            if (*q == '-') ++q;
            unsigned long long hi = parse_hex(&q);
            skip_spaces(&q);
            while (*q && *q != ' ') ++q;      /* skip the perms field, e.g. "r-xp" */
            skip_spaces(&q);
            unsigned long long file_off = parse_hex(&q);
            if (file_off <= want_off && want_off < file_off + (hi - lo))
                target = lo + (want_off - file_off);
        }
        p = *e ? e + 1 : e;
    }
    if (!target) { printf("SCANMEM_NO_TARGET lib=%s off=%#llx\n", libname, want_off); return 4; }
    printf("SCANMEM_TARGET %#llx\n", target);
    int mem = open(argv[1], 0);
    if (mem < 0) { printf("SCANMEM_MEM_OPEN=%d\n", mem); return 3; }
    unsigned long long hits[32];
    unsigned long long found = 0;
    p = all;
    while (*p && found < 32) {
        const char *e = p;
        while (*e && *e != '\n') ++e;
        int linelen = e - p;
        if (linelen > 0 && linelen < 500) {
            const char *q = p;
            unsigned long long lo = parse_hex(&q);
            if (*q == '-') ++q;
            unsigned long long hi = parse_hex(&q);
            skip_spaces(&q);
            /* readable mappings only: .data.rel.ro (vtables, RELRO) is r--, the heap is rw-p */
            if (*q == 'r' && lo >= 0x400000 && hi - lo <= 0x800000ULL && (q[1] == 'w' || q[1] == '-')) {
                unsigned long long before = found;
                found += scan_range(mem, lo, hi, target, 32 - found, hits + found);
                (void)before;
            }
        }
        p = *e ? e + 1 : e;
    }
    close(mem);
    for (unsigned long long i = 0; i < found; ++i)
        printf("SCANMEM_HIT addr=%#llx\n", hits[i]);
    if (chain) {
        for (unsigned long long i = 0; i < found && i < 4; ++i) {
            unsigned long long vtable = hits[i] - 8;   /* [vtable+8] holds the typeinfo pointer */
            unsigned long long objects[8];
            unsigned long long count = 0;
            printf("SCANMEM_VTABLE va=%#llx\n", vtable);
            int mf2 = open(maps, 0);
            if (mf2 < 0) { printf("SCANMEM_CHAIN_MAPS=%d\n", mf2); return 3; }
            long cap2 = 0;
            while (cap2 < (long)sizeof all - 1) {
                long got = read(mf2, all + cap2, sizeof all - 1 - cap2);
                if (got <= 0) break;
                cap2 += got;
            }
            all[cap2] = 0;
            close(mf2);
            int mem2 = open(argv[1], 0);
            if (mem2 < 0) { printf("SCANMEM_CHAIN_MEM=%d\n", mem2); return 3; }
            const char *q = all;
            while (*q && count < 8) {
                const char *e = q;
                while (*e && *e != '\n') ++e;
                int linelen = e - q;
                if (linelen > 0 && linelen < 500) {
                    const char *r = q;
                    unsigned long long lo = parse_hex(&r);
                    if (*r == '-') ++r;
                    unsigned long long hi = parse_hex(&r);
                    skip_spaces(&r);
                    if (*r == 'r' && lo >= 0x400000 && hi - lo <= 0x800000ULL && (r[1] == 'w' || r[1] == '-'))
                        count += scan_range(mem2, lo, hi, vtable, 8 - count, objects + count);
                }
                q = *e ? e + 1 : e;
            }
            close(mem2);
            printf("SCANMEM_OBJECTS vtable=%#llx count=%llu\n", vtable, count);
            for (unsigned long long k = 0; k < count; ++k)
                printf("SCANMEM_OBJECT addr=%#llx\n", objects[k]);
        }
    }
    printf("SCANMEM_DONE found=%llu\n", found);
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
