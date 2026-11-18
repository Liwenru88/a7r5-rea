/* SSH 启动的 kit 原生触发器；校验 cmdline、还原 /etc/ld.so.preload 后拉起 service.arm64。 */
typedef long s64;
typedef unsigned long u64;
#include "jit_config.h"
__attribute__((used)) static const char ssh_kit_mode[] = "A7R5_SSH_KIT_TRIGGER_V1";

static s64 sc(s64 n, s64 a, s64 b, s64 c, s64 d, s64 e, s64 f)
{
    register s64 x0 __asm__("x0") = a, x1 __asm__("x1") = b, x2 __asm__("x2") = c;
    register s64 x3 __asm__("x3") = d, x4 __asm__("x4") = e, x5 __asm__("x5") = f;
    register s64 x8 __asm__("x8") = n;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5), "r"(x8) : "memory", "cc");
    return x0;
}

#define P(x) ((s64)(x))
#define RDONLY 0
#define WRONLY 1
#define RDWR 2
#define CREATE 64
#define EXCL 128
#define NOFOLLOW 32768
#define CLOEXEC 524288
#define AT_FDCWD -100

static const char debug_argv[] = "/bin/sh\0-c\0/bin/date -s 070421422017.26\0";

static int same(const char *a, const char *b, u64 n)
{
    for (u64 i = 0; i < n; i++) if (a[i] != b[i]) return 0;
    return 1;
}
static s64 open_file(const char *p, int flags) { return sc(56, AT_FDCWD, P(p), flags, 0600, 0, 0); }
static s64 close_fd(s64 fd) { return sc(57, fd, 0, 0, 0, 0, 0); }
static s64 unlink_file(const char *p) { return sc(35, AT_FDCWD, P(p), 0, 0, 0, 0); }
static void die(int rc) { sc(94, rc, 0, 0, 0, 0, 0); for (;;) {} }
static int write_all(s64 fd, const char *s, u64 n)
{
    while (n) {
        s64 got = sc(64, fd, P(s), n, 0, 0, 0);
        if (got == -4) continue;
        if (got <= 0) return -1;
        s += got;
        n -= (u64)got;
    }
    return 0;
}
static s64 bounded(const char *path, char *raw, u64 cap)
{
    s64 fd = open_file(path, RDONLY | NOFOLLOW | CLOEXEC);
    if (fd < 0) return fd;
    u64 used = 0;
    while (used < cap) {
        s64 got = sc(63, fd, P(raw + used), cap - used, 0, 0, 0);
        if (got == -4) continue;
        if (got < 0) { close_fd(fd); return got; }
        if (!got) break;
        used += (u64)got;
    }
    char extra;
    s64 got = sc(63, fd, P(&extra), 1, 0, 0, 0);
    s64 closed = close_fd(fd);
    return got != 0 || closed < 0 ? -5 : (s64)used;
}

static int disarm_preload(void)
{
    char raw[4096];
    const u64 arm_len = sizeof(ARM_BYTES) - 1;
    const u64 restore_len = sizeof(RESTORE_PRELOAD) - 1;
    s64 n = bounded(PRELOAD_PATH, raw, sizeof(raw));
    if (n != (s64)arm_len || !same(raw, ARM_BYTES, arm_len)) return -1;
    s64 fd = open_file(PRELOAD_PATH, RDWR | NOFOLLOW | CLOEXEC);
    if (fd < 0) return -1;
    u64 used = 0;
    while (used < sizeof(raw)) {
        s64 got = sc(63, fd, P(raw + used), sizeof(raw) - used, 0, 0, 0);
        if (got == -4) continue;
        if (got < 0) { close_fd(fd); return -1; }
        if (!got) break;
        used += (u64)got;
    }
    if (used != arm_len || !same(raw, ARM_BYTES, arm_len)) { close_fd(fd); return -1; }
    int failed = sc(62, fd, 0, 0, 0, 0, 0) != 0
        || sc(46, fd, 0, 0, 0, 0, 0) != 0
        || write_all(fd, RESTORE_PRELOAD, restore_len)
        || sc(82, fd, 0, 0, 0, 0, 0) < 0;
    if (close_fd(fd) < 0) failed = 1;
    n = bounded(PRELOAD_PATH, raw, sizeof(raw));
    return failed || n != (s64)restore_len || !same(raw, RESTORE_PRELOAD, restore_len) ? -1 : 0;
}

static void worker(void)
{
    if (sc(157, 0, 0, 0, 0, 0, 0) < 0) die(80);
    u64 action[4] = {0, 0, 0, 0}, mask = 0, limits[2];
    if (sc(134, 17, P(action), 0, 8, 0, 0) < 0 || sc(135, 2, P(&mask), 0, 8, 0, 0) < 0) die(85);
    if (sc(163, 7, P(limits), 0, 0, 0, 0) < 0 || limits[0] < 3 || limits[0] > 65536) die(86);
    s64 null = open_file("/dev/null", RDWR | CLOEXEC);
    if (null < 0) die(81);
    if (sc(25, null, 2, 0, 0, 0, 0) < 0) die(82);
    for (int i = 0; i < 3; i++) if (null != i && sc(24, null, i, 0, 0, 0, 0) < 0) die(82);
    for (u64 fd = 3; fd < limits[0]; fd++) close_fd((s64)fd);
    const char *files[] = {SERVICE_PATH, SESSION_PATH, SFTP_PATH};
    for (int i = 0; i < 3; i++) {
        s64 fd = open_file(files[i], RDONLY | NOFOLLOW | CLOEXEC);
        if (fd < 0) die(83);
        if (sc(52, fd, 0700, 0, 0, 0, 0) < 0) { close_fd(fd); die(84); }
        close_fd(fd);
    }
    char *argv[] = {SERVICE_PATH, "--launch-original", 0};
    char *env[] = {"PATH=/bin:/sbin:/usr/bin:/usr/sbin", "LC_ALL=C", "HOME=/", 0};
    sc(221, P(SERVICE_PATH), P(argv), P(env), 0, 0, 0);
    die(127);
}

__attribute__((visibility("default"))) void _init(void)
{
    char cmd[256];
    s64 n = bounded(GATE_PATH, cmd, sizeof(cmd));
    if (n != (s64)(sizeof(debug_argv) - 1) || !same(cmd, debug_argv, sizeof(debug_argv) - 1)) return;
    if (disarm_preload()) die(92);
    if (sc(174, 0, 0, 0, 0, 0, 0) || sc(175, 0, 0, 0, 0, 0, 0)) die(97);
    if (unlink_file(KIT_SO_PATH) < 0) die(98);
    s64 pid = sc(220, 17, 0, 0, 0, 0, 0);
    if (!pid) worker();
    if (pid < 0) die(101);
    die(0);
}
