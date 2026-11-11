/* 只在独立文件中保存已确认的比例，临时文件与原子改名保护旧记录。 */
#include "ap_state.h"
#include <stddef.h>
extern void *stock_dlsym(void *, const char *);
extern void aspect_model_lock(void), aspect_model_unlock(void);
extern void stock_aspect_dependents(unsigned), stock_aspect_notify(unsigned);
#define LOAD(p) __atomic_load_n((p), __ATOMIC_ACQUIRE)
#define STORE(p,v) __atomic_store_n((p), (v), __ATOMIC_RELEASE)
enum { RESTORE_BUSY = 2, RESTORE_RETRY = 3, ATTEMPTS = 3, RETRY_MS = 1000 };
struct time_value { int64_t sec, ns; };
static void ensure_worker(void);
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
/* AArch64 的 O_DIRECTORY 是 0x4000；0x10000 是 O_DIRECT。 */
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
int r5_aspect_restore_record(const void *data, unsigned bytes, unsigned expected)
{
    const uint8_t *p = data;
    uint32_t record[4];
    if (!p || bytes != sizeof record) return 0;
    for (unsigned i = 0; i < 4; ++i)
        record[i] = (uint32_t)p[4*i] | (uint32_t)p[4*i+1] << 8 |
                    (uint32_t)p[4*i+2] << 16 | (uint32_t)p[4*i+3] << 24;
    if (record[0] != 0x41533552u || record[1] != 1 || !valid(record[2]) ||
        record[3] != ~record[2]) return 0;
    unsigned value = ((expected & ~255u) + 256u) | record[2];
    return __atomic_compare_exchange_n(&aspect_selection, &expected, value, 0,
                                      __ATOMIC_RELEASE, __ATOMIC_ACQUIRE);
}
static int error_number(void)
{
    int *(*get)(void) = (void *)stock_dlsym(0, "__errno_location");
    return get ? *get() : 0;
}
static int now_ms(uint64_t *out)
{
    int (*clock)(int, struct time_value *) = (void *)stock_dlsym(0, "clock_gettime");
    struct time_value t;
    if (!clock || clock(1, &t) || t.sec < 0 || t.ns < 0 || t.ns >= 1000000000 ||
        (uint64_t)t.sec > (UINT64_MAX - 999) / 1000) return 0;
    *out = (uint64_t)t.sec * 1000 + (uint64_t)t.ns / 1000000;
    return 1;
}
unsigned r5_aspect_feedback(void)
{
    unsigned request = LOAD(&aspect_session.save_requested);
    if (request != LOAD(&aspect_session.save_completed)) {
        uint64_t outcome = LOAD(&aspect_session.save_outcome);
        return LOAD(&aspect_session.worker_error) ||
            ((unsigned)(outcome >> 32) == request && (int32_t)outcome < 0) ? 2 : 1;
    }
    unsigned claim = LOAD(&aspect_session.restore_claim);
    if ((claim == RESTORE_BUSY || claim == RESTORE_RETRY) && !LOAD(&aspect_selection))
        return LOAD(&aspect_session.worker_error) ? 4 : 3;
    return !LOAD(&aspect_selection) && LOAD(&aspect_session.restore_error) ? 4 : 0;
}
static void feedback(int restored)
{
    unsigned value = r5_aspect_feedback();
    unsigned before = __atomic_exchange_n(&aspect_session.feedback, value, __ATOMIC_ACQ_REL);
    if (before == value && !restored) return;
    /* 复用原厂属性 0x52b 的锁与通知，不从文件线程操作 UI 指针或伪造 CP 完成。 */
    aspect_model_lock();
    if (restored) stock_aspect_dependents(0x52b);
    stock_aspect_notify(0x52b);
    aspect_model_unlock();
}
static int restore(uint64_t ms)
{
    unsigned epoch = LOAD(&aspect_selection), claim = RESTORE_RETRY;
    if (!__atomic_compare_exchange_n(&aspect_session.restore_claim, &claim, RESTORE_BUSY, 0,
                                    __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return 0;
    struct api a; uint8_t record[17]; size_t used = 0;
    int rc = -1, terminal = 0, restored = 0;
    if (epoch) { terminal = 1; rc = 0; goto done; }
    aspect_session.restore_attempts++;
    if (!resolve(&a)) goto done;
    int dir = a.open("/setting", FLAGS | DIRECTORY_FLAG, 0);
    if (dir < 0) { rc = -2; goto done; }
    int fd = a.openat(dir, FILE_NAME, FLAGS, 0);
    if (fd < 0) {
        terminal = error_number() == 2; /* ENOENT 是无记录，其他错误可限次补读。 */
        rc = terminal ? 0 : -3;
        if (a.close(dir)) { terminal = 0; rc = -3; }
        goto done;
    }
    rc = 0;
    while (used < sizeof record) {
        intptr_t n = a.read(fd, record + used, sizeof record - used);
        if (n < 0 || (size_t)n > sizeof record - used) { rc = -4; break; }
        if (!n) break;
        used += (size_t)n;
    }
    if (a.close(fd)) rc = -4;
    if (a.close(dir)) rc = -4;
    if (!rc) {
        restored = r5_aspect_restore_record(record, used, epoch);
        terminal = 1;
        if (!restored && epoch == LOAD(&aspect_selection)) rc = -4;
    }
done:
    /* 显式选择与读取竞争时，旧结果不得覆盖新选择，也不应留下读取失败提示。 */
    if (LOAD(&aspect_selection) && !restored) { terminal = 1; rc = 0; }
    STORE(&aspect_session.persist_status, rc ? rc : 1);
    STORE(&aspect_session.restore_error, rc);
    aspect_session.restore_after = ms <= UINT64_MAX - RETRY_MS ? ms + RETRY_MS : UINT64_MAX;
    claim = RESTORE_BUSY;
    unsigned next = terminal || aspect_session.restore_attempts >= ATTEMPTS ? 1 : RESTORE_RETRY;
    (void)__atomic_compare_exchange_n(&aspect_session.restore_claim, &claim, next, 0,
                                      __ATOMIC_RELEASE, __ATOMIC_ACQUIRE);
    return restored;
}
void r5_aspect_restore_once(void)
{
    unsigned claim = 0;
    if (__atomic_compare_exchange_n(&aspect_session.restore_claim, &claim, RESTORE_RETRY, 0,
                                   __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        uint64_t ms = 0;
        (void)now_ms(&ms);
        (void)restore(ms); /* 首条配置保留立即恢复；成功时本条原生消息即携带私有值。 */
    }
    if (LOAD(&aspect_session.restore_claim) == RESTORE_RETRY ||
        LOAD(&aspect_session.save_requested) != LOAD(&aspect_session.save_completed)) ensure_worker();
}
static int save_record(unsigned id)
{
    struct api a; int rc = -1, dir = -1, fd = -1; size_t used = 0;
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
    STORE(&aspect_session.persist_status, rc ? rc : 1);
    return rc;
}

int r5_aspect_save(unsigned id)
{
    if (!valid(id)) id = 0;
    unsigned old = __atomic_load_n(&aspect_session.save_requested, __ATOMIC_RELAXED), requested;
    do { requested = ((old & ~255u) + 256u) | id; }
    while (!__atomic_compare_exchange_n(&aspect_session.save_requested, &old, requested, 0,
                                       __ATOMIC_RELEASE, __ATOMIC_RELAXED));
    STORE(&aspect_session.restore_claim, 1);
    /* 不在菜单线程写盘；错误回执和请求同代次绑定，旧失败不能污染新确认。 */
    if (LOAD(&aspect_session.worker_claim) == 0) {
        STORE(&aspect_session.worker_attempts, 0);
        STORE(&aspect_session.worker_error, 0);
    }
    ensure_worker();
    feedback(0);
    return LOAD(&aspect_session.worker_error);
}
static int due(uint64_t ms, uint64_t after)
{
    /* 暖恢复的单调时钟若回退，重新起算；不会留下永不执行的旧期限。 */
    return ms >= after || after - ms > RETRY_MS;
}
int r5_aspect_persist_service(void)
{
    unsigned claim = 0;
    if (!__atomic_compare_exchange_n(&aspect_session.save_claim, &claim, 1, 0,
                                     __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return 0;
    uint64_t ms;
    if (!now_ms(&ms)) {
        STORE(&aspect_session.worker_error, -7);
        STORE(&aspect_session.save_claim, 0);
        feedback(0); return -1;
    }
    int restored = 0;
    if (LOAD(&aspect_session.restore_claim) == RESTORE_RETRY &&
        aspect_session.restore_attempts < ATTEMPTS && due(ms, aspect_session.restore_after))
        restored = restore(ms);
    unsigned request = LOAD(&aspect_session.save_requested);
    if (request != LOAD(&aspect_session.save_completed)) {
        if (request != aspect_session.save_seen) {
            aspect_session.save_seen = request;
            aspect_session.save_attempts = 0;
            aspect_session.save_after = ms;
        }
        if (aspect_session.save_attempts < ATTEMPTS && due(ms, aspect_session.save_after)) {
            int rc = save_record(request & 255u);
            aspect_session.save_attempts++;
            aspect_session.save_after = ms <= UINT64_MAX - RETRY_MS ? ms + RETRY_MS : UINT64_MAX;
            STORE(&aspect_session.save_outcome, (uint64_t)request << 32 | (uint32_t)rc);
            if (!rc) STORE(&aspect_session.save_completed, request);
        }
    }
    STORE(&aspect_session.save_claim, 0);
    feedback(restored);
    return 0;
}
static void *worker(void *unused)
{
    (void)unused;
    unsigned claim = 1;
    (void)__atomic_compare_exchange_n(&aspect_session.worker_claim, &claim, 2, 0,
                                      __ATOMIC_RELEASE, __ATOMIC_ACQUIRE);
    int (*sleep)(const void *, void *) = (void *)stock_dlsym(0, "nanosleep");
    const struct time_value pause = {0, 100000000};
    while (sleep && r5_aspect_persist_service() == 0) {
        if (sleep(&pause, 0) && error_number() != 4) break;
    }
    STORE(&aspect_session.worker_error, -7);
    STORE(&aspect_session.worker_claim, 0);
    feedback(0);
    return 0;
}
static void ensure_worker(void)
{
    uint64_t ms = 0;
    unsigned claim = 0;
    if (LOAD(&aspect_session.worker_claim) || LOAD(&aspect_session.worker_attempts) >= ATTEMPTS) return;
    if (!now_ms(&ms)) {
        __atomic_add_fetch(&aspect_session.worker_attempts, 1, __ATOMIC_RELAXED);
        STORE(&aspect_session.worker_error, -7); return;
    }
    if (LOAD(&aspect_session.worker_attempts) && !due(ms, LOAD(&aspect_session.launch_after))) return;
    if (!__atomic_compare_exchange_n(&aspect_session.worker_claim, &claim, 1, 0,
                                     __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    __atomic_add_fetch(&aspect_session.worker_attempts, 1, __ATOMIC_RELAXED);
    STORE(&aspect_session.launch_after, ms <= UINT64_MAX - RETRY_MS ? ms + RETRY_MS : UINT64_MAX);
    uint64_t attributes[8] = {0}; uintptr_t thread;
    int (*init)(void *) = (void *)stock_dlsym(0, "pthread_attr_init");
    int (*detach)(void *, int) = (void *)stock_dlsym(0, "pthread_attr_setdetachstate");
    int (*stack)(void *, size_t) = (void *)stock_dlsym(0, "pthread_attr_setstacksize");
    int (*create)(uintptr_t *, const void *, void *(*)(void *), void *) = (void *)stock_dlsym(0, "pthread_create");
    int (*destroy)(void *) = (void *)stock_dlsym(0, "pthread_attr_destroy");
    int rc = -1;
    if (init && detach && stack && create && destroy && !init(attributes)) {
        rc = detach(attributes, 1);
        if (!rc) rc = stack(attributes, 131072u);
        if (!rc) {
            STORE(&aspect_session.worker_error, 0);
            rc = create(&thread, attributes, worker, 0);
        }
        (void)destroy(attributes); /* 创建成功后不能因属性销毁失败再启动第二个工作线程。 */
    }
    if (rc) {
        STORE(&aspect_session.worker_error, -7);
        STORE(&aspect_session.worker_claim, 0);
    } else {
        claim = 1;
        (void)__atomic_compare_exchange_n(&aspect_session.worker_claim, &claim, 2, 0,
                                          __ATOMIC_RELEASE, __ATOMIC_ACQUIRE);
    }
}
