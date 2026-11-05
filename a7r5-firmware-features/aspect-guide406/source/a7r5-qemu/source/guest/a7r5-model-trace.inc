/* 仅在客体 RAM 中镜像原厂日志；保留原函数和断言行为。 */
extern int vsnprintf(char *, size_t, const char *, __builtin_va_list);
static int a7r5_trace_direct(unsigned int id, void *message) {
    int result = real_send_sync_direct(id, message);
    if (getenv("A7R5_MODEL_TRACE") && (id == 0x80cf016d || id == 0x80d9016e)) {
        const unsigned int *p = message;
        char text[256];
        snprintf(text, sizeof text, "id=%#x result=%d words=%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x", id, result,
                 p[0],p[1],p[2],p[3],p[4],p[5],p[6],p[7],p[8],p[9]);
        record("A7R5_MEDIA_DIRECT ", text);
    }
    return result;
}
int osal_snd_sync_direct(unsigned int id, void *message) { return a7r5_trace_direct(id, message); }
int Backup_read_multi(const unsigned int *ids, void **destinations) {
    int (*original)(const unsigned int *, void **) = real_dlsym((void *)-1, "Backup_read_multi");
    if (!original || original == Backup_read_multi) __builtin_trap();
    int result = original(ids, destinations);
    if (getenv("A7R5_MODEL_TRACE") && ids && (ids[0] >> 16) == 0xcf) {
        char text[240];
        const unsigned char *first = destinations ? destinations[0] : 0;
        snprintf(text, sizeof text, "first=%#x result=%d bytes0_7=%02x%02x%02x%02x%02x%02x%02x%02x", ids[0], result,
                 first ? first[0] : 0, first ? first[1] : 0, first ? first[2] : 0, first ? first[3] : 0,
                 first ? first[4] : 0, first ? first[5] : 0, first ? first[6] : 0, first ? first[7] : 0);
        record("A7R5_BACKUP_MULTI ", text);
    }
    return result;
}
static int (*a7r5_original_log)(const char *, ...);
static unsigned long a7r5_trace_base;
static void (*a7r5_original_media_start)(const unsigned int *, unsigned int *);
static void a7r5_media_start_mirror(const unsigned int *id, unsigned int *out) {
    char text[256];
    unsigned long b = a7r5_trace_base;
    unsigned int count = *(unsigned int *)(b + 0x89bd3d0);
    snprintf(text, sizeof text, "id=%#x configured_count=%u ids0_3=%#x,%#x,%#x,%#x", *id, count,
             *(unsigned int *)(b+0x89bd150), *(unsigned int *)(b+0x89bd178),
             *(unsigned int *)(b+0x89bd1a0), *(unsigned int *)(b+0x89bd1c8));
    record("A7R5_MEDIA_START_BEFORE ", text);
    a7r5_original_media_start(id, out);
    snprintf(text, sizeof text, "id=%#x model_error=%#x", *id, *out);
    record("A7R5_MEDIA_START_AFTER ", text);
}
static int a7r5_log_mirror(const char *format, ...) {
    char text[384];
    __builtin_va_list args;
    __builtin_va_start(args, format);
    vsnprintf(text, sizeof text, format, args);
    __builtin_va_end(args);
    static unsigned int count;
    if (__atomic_fetch_add(&count, 1, __ATOMIC_RELAXED) < 12000)
        record("A7R5_MODEL_LOG ", text);
    return a7r5_original_log("%s", text);
}
static void a7r5_trace_install(unsigned long base) {
    a7r5_trace_base = base;
    unsigned int *entry = (unsigned int *)(base + 0x3692384UL);
    const unsigned int expected[4] = {0xd10803ff, 0xa9be7bfd, 0x910003fd, 0xf9000bf3};
    for (unsigned int i = 0; i < 4; ++i)
        if (entry[i] != expected[i]) { record("A7R5_PATCH_FAILED ", "model logger fingerprint"); __builtin_trap(); }
    unsigned int *stub = mmap(0, 4096, 3, 0x22, -1, 0);
    if (stub == (void *)-1) __builtin_trap();
    for (unsigned int i = 0; i < 4; ++i) stub[i] = entry[i];
    stub[4] = 0x58000050; stub[5] = 0xd61f0200;
    *(unsigned long *)(stub + 6) = (unsigned long)entry + 16;
    clear_cache_range(stub, 32);
    if (mprotect(stub, 4096, 5)) __builtin_trap();
    a7r5_original_log = (void *)stub;
    void *page = (void *)((unsigned long)entry & ~4095UL);
    if (mprotect(page, 4096, 7)) __builtin_trap();
    entry[0] = 0x58000050; entry[1] = 0xd61f0200;
    *(unsigned long *)(entry + 2) = (unsigned long)a7r5_log_mirror;
    clear_cache_range(entry, 16);
    if (mprotect(page, 4096, 5)) __builtin_trap();
    entry = (unsigned int *)(base + 0x350ea3cUL);
    const unsigned int media_expected[4] = {0xa9be7bfd, 0x910003fd, 0xa90153f3, 0xaa0003f3};
    for (unsigned int i = 0; i < 4; ++i) if (entry[i] != media_expected[i]) __builtin_trap();
    stub = mmap(0, 4096, 3, 0x22, -1, 0);
    if (stub == (void *)-1) __builtin_trap();
    for (unsigned int i = 0; i < 4; ++i) stub[i] = entry[i];
    stub[4] = 0x58000050; stub[5] = 0xd61f0200;
    *(unsigned long *)(stub + 6) = (unsigned long)entry + 16;
    clear_cache_range(stub, 32);
    if (mprotect(stub, 4096, 5)) __builtin_trap();
    a7r5_original_media_start = (void *)stub;
    page = (void *)((unsigned long)entry & ~4095UL);
    if (mprotect(page, 4096, 7)) __builtin_trap();
    entry[0] = 0x58000050; entry[1] = 0xd61f0200;
    *(unsigned long *)(entry + 2) = (unsigned long)a7r5_media_start_mirror;
    clear_cache_range(entry, 16);
    if (mprotect(page, 4096, 5)) __builtin_trap();
    record("A7R5_MODEL_TRACE ", "logger mirrored; original model checks and assertions retained");
}
