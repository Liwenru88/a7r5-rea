/* 4.29 纵横比持久化（无后台线程、无跨线程 UI 通知、使用 AArch64 O_DIRECTORY=0x4000）。 */
#include "ap_state.h"
#include <stddef.h>

extern void *stock_dlsym(void *, const char *);

struct api {
    int (*open)(const char *, int, unsigned);
    int (*openat)(int, const char *, int, unsigned);
    intptr_t (*read)(int, void *, size_t);
    intptr_t (*write)(int, const void *, size_t);
    int (*close)(int), (*fsync)(int);
    int (*renameat)(int, const char *, int, const char *);
    int (*unlinkat)(int, const char *, int);
};

#define FLAGS (0x8000 | 0x20000 | 0x80000 | 0x800)
/* AArch64 的 O_DIRECTORY 是 0x4000（0x10000 是 O_DIRECT）。 */
#define DIRECTORY_FLAG 0x4000
#define FILE_NAME "r5_aspect10_v1.dat"
#define TEMP_NAME "r5_aspect10_v1.tmp"

static unsigned valid(unsigned id) { return id == 0 || id - 4u < R5_ASPECT_COUNT - 4u; }

static int resolve(struct api *a) {
#define GET(n) a->n = (void *)stock_dlsym(0, #n); if (!a->n) return 0
    GET(open); GET(openat); GET(read); GET(write); GET(close); GET(fsync);
    GET(renameat); GET(unlinkat);
#undef GET
    return 1;
}

int r5_aspect_restore_record(const void *data, unsigned bytes, unsigned expected) {
    const uint8_t *p = data;
    uint32_t record[4];
    if (!p || bytes != sizeof record) return 0;
    for (unsigned i = 0; i < 4; ++i)
        record[i] = (uint32_t)p[4 * i] | (uint32_t)p[4 * i + 1] << 8 |
                    (uint32_t)p[4 * i + 2] << 16 | (uint32_t)p[4 * i + 3] << 24;
    if (record[0] != 0x41533552u || record[1] != 1 || !valid(record[2]) ||
        record[3] != ~record[2])
        return 0;
    unsigned value = ((expected & ~255u) + 256u) | record[2];
    return __atomic_compare_exchange_n(&aspect_selection, &expected, value, 0,
                                       __ATOMIC_RELEASE, __ATOMIC_ACQUIRE);
}

unsigned r5_aspect_feedback(void) {
    return 0;
}

void r5_aspect_restore_once(void) {
    unsigned claim = 0;
    if (!__atomic_compare_exchange_n(&aspect_session.restore_claim, &claim, 1, 0,
                                     __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
        return;
    unsigned epoch = __atomic_load_n(&aspect_selection, __ATOMIC_ACQUIRE);
    if (epoch) return;

    struct api a;
    if (!resolve(&a)) return;
    int dir = a.open("/setting", FLAGS | DIRECTORY_FLAG, 0);
    if (dir < 0) return;
    int fd = a.openat(dir, FILE_NAME, FLAGS, 0);
    if (fd < 0) {
        (void)a.close(dir);
        return;
    }
    uint8_t record[17];
    size_t used = 0;
    int rc = 0;
    while (used < sizeof record) {
        intptr_t n = a.read(fd, record + used, sizeof record - used);
        if (n < 0 || (size_t)n > sizeof record - used) { rc = -1; break; }
        if (!n) break;
        used += (size_t)n;
    }
    if (a.close(fd)) rc = -1;
    if (a.close(dir)) rc = -1;
    if (!rc && r5_aspect_restore_record(record, (unsigned)used, epoch))
        __atomic_store_n(&aspect_session.persist_status, 1, __ATOMIC_RELEASE);
}

int r5_aspect_save(unsigned id) {
    unsigned claim = 0;
    if (!__atomic_compare_exchange_n(&aspect_session.save_claim, &claim, 1, 0,
                                     __ATOMIC_ACQUIRE, __ATOMIC_RELAXED))
        return -7;
    __atomic_store_n(&aspect_session.restore_claim, 1, __ATOMIC_RELEASE);

    struct api a;
    int rc = -1, dir = -1, fd = -1;
    size_t used = 0;
    if (!valid(id)) id = 0;
    uint32_t record[4] = {0x41533552u, 1, id, ~id};
    if (!resolve(&a)) goto done;
    dir = a.open("/setting", FLAGS | DIRECTORY_FLAG, 0);
    if (dir < 0) { rc = -2; goto done; }
    (void)a.unlinkat(dir, TEMP_NAME, 0);
    fd = a.openat(dir, TEMP_NAME, FLAGS | 1 | 0x40 | 0x80, 0600);
    if (fd < 0) { rc = -5; goto done; }
    rc = -6;
    while (used < sizeof record) {
        intptr_t n = a.write(fd, (const uint8_t *)record + used, sizeof record - used);
        if (n <= 0 || (size_t)n > sizeof record - used) goto done;
        used += (size_t)n;
    }
    if (a.fsync(fd)) goto done;
    if (a.close(fd)) { fd = -1; goto done; }
    fd = -1;
    if (a.renameat(dir, TEMP_NAME, dir, FILE_NAME) || a.fsync(dir)) goto done;
    rc = 0;
done:
    if (fd >= 0 && a.close(fd)) rc = -6;
    if (dir >= 0 && a.close(dir)) rc = -6;
    __atomic_store_n(&aspect_session.persist_status, rc ? rc : 1, __ATOMIC_RELEASE);
    __atomic_store_n(&aspect_session.save_claim, 0, __ATOMIC_RELEASE);
    return rc;
}
