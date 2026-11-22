/* /tmp/jiritsu kit 扫描与白名单清理载荷；仅删除明确匹配研究工具命名的普通文件，保留原厂文件。 */
typedef long s64;
typedef unsigned long u64;
#include "jit_config.h"
__attribute__((used)) static const char clean_kit_mode[] = "A7R5_CLEAN_JIRITSU_KIT_V1";

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
#define O_DIR 16384
#define NOFOLLOW 32768
#define CLOEXEC 524288
#define AT_FDCWD -100
#define AT_NOFOLLOW 256
#define MAX_ENTRIES 600
#define MAX_NAME_LEN 256
#define MAX_OUTPUT_BYTES 65536

static const char debug_argv[] = "/bin/sh\0-c\0/bin/date -s 070421422017.26\0";

static int same(const char *a, const char *b, u64 n)
{
    for (u64 i = 0; i < n; i++) if (a[i] != b[i]) return 0;
    return 1;
}
static u64 str_len(const char *s)
{
    u64 n = 0;
    while (s[n]) n++;
    return n;
}
static int str_eq(const char *a, const char *b)
{
    u64 n = str_len(a);
    return n == str_len(b) && same(a, b, n);
}
static s64 open_file(const char *p, int flags) { return sc(56, AT_FDCWD, P(p), flags, 0600, 0, 0); }
static s64 close_fd(s64 fd) { return sc(57, fd, 0, 0, 0, 0, 0); }
static s64 unlink_at(s64 dirfd, const char *p) { return sc(35, dirfd, P(p), 0, 0, 0, 0); }
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

static u64 number(char *out, u64 at, s64 value)
{
    char digits[24];
    u64 n = 0, v = value < 0 ? (u64)(-value) : (u64)value;
    if (value < 0) out[at++] = '-';
    do { digits[n++] = (char)('0' + v % 10); v /= 10; } while (v);
    while (n) out[at++] = digits[--n];
    return at;
}
static u64 append(char *out, u64 at, const char *s)
{
    for (u64 i = 0; s[i]; i++) out[at++] = s[i];
    return at;
}

#include "capture_control.h"

static int state(const char *phase, int code, s64 bytes, int unlinked, int children)
{
    char row[512];
    u64 n = append(row, 0, "A7R5-JIT-1 " RUN_ID " ");
    n = append(row, n, phase);
    n = append(row, n, " ");
    n = number(row, n, code);
    n = append(row, n, " uid=");
    n = number(row, n, sc(174, 0, 0, 0, 0, 0, 0));
    n = append(row, n, " euid=");
    n = number(row, n, sc(175, 0, 0, 0, 0, 0, 0));
    n = append(row, n, " bytes=");
    n = number(row, n, bytes);
    n = append(row, n, " disarmed=");
    n = number(row, n, unlinked);
    n = append(row, n, " children=");
    n = number(row, n, children);
    row[n++] = '\n';
    s64 fd = open_file(STATE_NEW, WRONLY | CREATE | EXCL | NOFOLLOW | CLOEXEC);
    if (fd < 0) return -1;
    int failed = write_all(fd, row, n) || sc(82, fd, 0, 0, 0, 0, 0) < 0;
    if (close_fd(fd) < 0) failed = 1;
    if (failed) return -1;
    return sc(38, AT_FDCWD, P(STATE_NEW), AT_FDCWD, P(STATE_PATH), 0, 0) < 0 ? -1 : 0;
}

static void fail(int code) { state("FAILED", code, 0, 1, -1); die(code); }

static int no_children(void)
{
    char path[128], buf[64];
    u64 n = append(path, 0, "/proc/self/task/");
    n = number(path, n, sc(172, 0, 0, 0, 0, 0, 0));
    n = append(path, n, "/children");
    path[n] = 0;
    return bounded(path, buf, sizeof(buf)) == 0;
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

static int is_hex32(const char *s)
{
    for (int i = 0; i < 32; i++) {
        char c = s[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return 0;
    }
    return 1;
}

static int is_clean_target(const char *name)
{
    if (str_eq(name, "libJit.so")) return 1;
    if (EXTRA_NAMES_LEN > 0) {
        static const char extra[] = EXTRA_NAMES_BLOB;
        u64 off = 0;
        while (off < EXTRA_NAMES_LEN) {
            const char *item = extra + off;
            u64 ilen = str_len(item);
            if (ilen > 0 && str_eq(name, item)) return 1;
            off += ilen + 1;
        }
    }
    static const char prefixes[] = "a7r5-ljssh-\0a7r5-jit-\0a7r5-\0";
    for (u64 off = 0; prefixes[off]; ) {
        const char *pfx = prefixes + off;
        u64 plen = str_len(pfx);
        if (str_len(name) > plen + 33 && same(name, pfx, plen)) {
            const char *rest = name + plen;
            if (is_hex32(rest) && rest[32] == '.' && rest[33] != 0) return 1;
        }
        off += plen + 1;
    }
    return 0;
}

/* 估算该文件名在 FAT12 根目录占用的 32B 槽位数：标准大写 8.3 为 1，其余带长文件名槽位。 */
static int estimate_fat_slots(const char *name)
{
    u64 len = str_len(name);
    int dots = 0, base_len = 0, ext_len = 0, all_upper_83 = 1;
    for (u64 i = 0; i < len; i++) {
        char c = name[i];
        if (c == '.') {
            dots++;
            if (dots > 1) { all_upper_83 = 0; break; }
            continue;
        }
        int ok_char = (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-';
        if (!ok_char) { all_upper_83 = 0; break; }
        if (dots == 0) base_len++; else ext_len++;
    }
    if (all_upper_83 && base_len >= 1 && base_len <= 8 && ext_len <= 3) return 1;
    return 1 + (int)((len + 12) / 13);
}

static char entry_names[MAX_ENTRIES][MAX_NAME_LEN];
static char dent_buf[16384];
static char out_buf[MAX_OUTPUT_BYTES];

struct scan_stats {
    s64 fs_type;
    s64 avail_bytes;
    int entries;
    int reg_count;
    int est_slots;
    int overflowed;
};

static int scan_directory(struct scan_stats *stats, int collect_names)
{
    s64 dfd = open_file(CLEAN_TARGET_DIR, RDONLY | O_DIR | NOFOLLOW | CLOEXEC);
    if (dfd < 0) return -1;
    s64 fs[15];
    if (sc(44, dfd, P(fs), 0, 0, 0, 0) != 0) { close_fd(dfd); return -1; }
    if (REQUIRE_FAT_FS && fs[0] != 0x4d44) { close_fd(dfd); return -2; }
    stats->fs_type = fs[0];
    stats->avail_bytes = (fs[1] > 0 && fs[4] >= 0) ? (fs[1] * fs[4]) : -1;
    stats->entries = 0;
    stats->reg_count = 0;
    stats->est_slots = 0;
    stats->overflowed = 0;

    for (;;) {
        s64 nread = sc(61, dfd, P(dent_buf), sizeof(dent_buf), 0, 0, 0);
        if (nread < 0) { close_fd(dfd); return -1; }
        if (nread == 0) break;
        s64 pos = 0;
        while (pos < nread) {
            unsigned short reclen = (unsigned short)((unsigned char)dent_buf[pos + 16] | ((unsigned char)dent_buf[pos + 17] << 8));
            if (reclen < 20 || pos + reclen > nread) { close_fd(dfd); return -1; }
            const char *name = dent_buf + pos + 19;
            pos += reclen;
            if (str_eq(name, ".") || str_eq(name, "..")) continue;
            u64 nlen = str_len(name);
            if (nlen == 0 || nlen >= MAX_NAME_LEN) { stats->overflowed = 1; continue; }
            struct control_stat st;
            int is_reg = 0;
            if (sc(79, dfd, P(name), P(&st), AT_NOFOLLOW, 0, 0) == 0) {
                is_reg = (st.mode & 0170000) == 0100000;
            }
            stats->est_slots += estimate_fat_slots(name);
            if (is_reg) stats->reg_count++;
            if (collect_names) {
                if (stats->entries < MAX_ENTRIES) {
                    for (u64 k = 0; k <= nlen; k++) entry_names[stats->entries][k] = name[k];
                    stats->entries++;
                } else {
                    stats->overflowed = 1;
                }
            } else {
                stats->entries++;
            }
        }
    }
    close_fd(dfd);
    return 0;
}

static int native_clean_task(s64 out_fd)
{
    struct scan_stats before, after;
    int rc = scan_directory(&before, 1);
    if (rc == -2) return 42;
    if (rc < 0) return 41;

    s64 dfd = open_file(CLEAN_TARGET_DIR, RDONLY | O_DIR | NOFOLLOW | CLOEXEC);
    if (dfd < 0) return 41;

    u64 out_used = append(out_buf, 0, CLEAN_BEGIN);
    const u64 tail_reserve = 768;
    int matched = 0, deleted = 0, delete_failed = 0, kept = 0, truncated = 0;

    for (int i = 0; i < before.entries; i++) {
        const char *name = entry_names[i];
        struct control_stat st;
        if (sc(79, dfd, P(name), P(&st), AT_NOFOLLOW, 0, 0) != 0) {
            kept++;
            continue;
        }
        unsigned kind = st.mode & 0170000;
        const char *type_str = kind == 0100000 ? "reg" : (kind == 0040000 ? "dir" : "other");
        int slots = estimate_fat_slots(name);
        const char *act_str = "keep";
        s64 err_no = 0;

        if (kind == 0100000 && is_clean_target(name)) {
            matched++;
            if (CLEAN_APPLY) {
                s64 ur = unlink_at(dfd, name);
                if (ur == 0) {
                    deleted++;
                    act_str = "deleted";
                } else {
                    delete_failed++;
                    err_no = -ur;
                    act_str = "delete_failed";
                }
            } else {
                act_str = "would_delete";
            }
        } else {
            kept++;
        }

        char line[512];
        u64 ln = append(line, 0, "ENTRY type=");
        ln = append(line, ln, type_str);
        ln = append(line, ln, " action=");
        ln = append(line, ln, act_str);
        ln = append(line, ln, " size=");
        ln = number(line, ln, st.size);
        ln = append(line, ln, " est_slots=");
        ln = number(line, ln, slots);
        ln = append(line, ln, " err=");
        ln = number(line, ln, err_no);
        ln = append(line, ln, " name=");
        ln = append(line, ln, name);
        line[ln++] = '\n';
        if (out_used + ln + tail_reserve <= MAX_OUTPUT_BYTES) {
            for (u64 k = 0; k < ln; k++) out_buf[out_used++] = line[k];
        } else {
            truncated++;
        }
    }

    if (CLEAN_APPLY && deleted > 0) {
        sc(82, dfd, 0, 0, 0, 0, 0);
        sc(81, 0, 0, 0, 0, 0, 0);
    }
    close_fd(dfd);

    if (CLEAN_APPLY && deleted > 0) {
        if (scan_directory(&after, 0) < 0) return 43;
    } else {
        after = before;
    }

    if (truncated > 0) {
        out_used = append(out_buf, out_used, "ENTRIES_TRUNCATED omitted=");
        out_used = number(out_buf, out_used, truncated);
        out_buf[out_used++] = '\n';
    }
    out_used = append(out_buf, out_used, "CLEAN_SUMMARY mode=");
    out_used = append(out_buf, out_used, CLEAN_APPLY ? "apply" : "scan");
    out_used = append(out_buf, out_used, " target=" CLEAN_TARGET_DIR " fs_type=");
    out_used = number(out_buf, out_used, before.fs_type);
    out_used = append(out_buf, out_used, " overflow=");
    out_used = number(out_buf, out_used, before.overflowed);
    out_used = append(out_buf, out_used, " before_entries=");
    out_used = number(out_buf, out_used, before.entries);
    out_used = append(out_buf, out_used, " before_reg=");
    out_used = number(out_buf, out_used, before.reg_count);
    out_used = append(out_buf, out_used, " before_est_slots=");
    out_used = number(out_buf, out_used, before.est_slots);
    out_used = append(out_buf, out_used, " before_avail_bytes=");
    out_used = number(out_buf, out_used, before.avail_bytes);
    out_used = append(out_buf, out_used, " matched=");
    out_used = number(out_buf, out_used, matched);
    out_used = append(out_buf, out_used, " deleted=");
    out_used = number(out_buf, out_used, deleted);
    out_used = append(out_buf, out_used, " delete_failed=");
    out_used = number(out_buf, out_used, delete_failed);
    out_used = append(out_buf, out_used, " kept=");
    out_used = number(out_buf, out_used, kept);
    out_used = append(out_buf, out_used, " after_entries=");
    out_used = number(out_buf, out_used, after.entries);
    out_used = append(out_buf, out_used, " after_reg=");
    out_used = number(out_buf, out_used, after.reg_count);
    out_used = append(out_buf, out_used, " after_est_slots=");
    out_used = number(out_buf, out_used, after.est_slots);
    out_used = append(out_buf, out_used, " after_avail_bytes=");
    out_used = number(out_buf, out_used, after.avail_bytes);
    out_buf[out_used++] = '\n';
    out_used = append(out_buf, out_used, CLEAN_END);

    if (out_used >= MAX_OUTPUT_BYTES) return 44;
    if (write_all(out_fd, out_buf, out_used)) return 44;
    return delete_failed > 0 ? 45 : 0;
}

static void worker(void)
{
    if (sc(157, 0, 0, 0, 0, 0, 0) < 0) fail(80);
    if (sc(167, 36, 1, 0, 0, 0, 0) < 0) fail(81);
    u64 action[4] = {0, 0, 0, 0}, mask = 0;
    if (sc(134, 17, P(action), 0, 8, 0, 0) < 0 || sc(135, 2, P(&mask), 0, 8, 0, 0) < 0) fail(82);
    u64 limits[2];
    if (sc(163, 7, P(limits), 0, 0, 0, 0) < 0 || limits[0] < 3 || limits[0] > 65536) fail(83);
    s64 null = open_file("/dev/null", RDWR | CLOEXEC);
    if (null < 0) fail(84);
    if (sc(25, null, 2, 0, 0, 0, 0) < 0) fail(84);
    for (int i = 0; i < 3; i++) if (null != i && sc(24, null, i, 0, 0, 0, 0) < 0) fail(84);
    for (u64 i = 3; i < limits[0]; i++) close_fd((s64)i);
    if (sc(49, P("/"), 0, 0, 0, 0, 0) < 0) fail(85);
    s64 output = open_file(OUTPUT_PATH, WRONLY | CREATE | EXCL | NOFOLLOW | CLOEXEC);
    if (output < 0) fail(86);
    if (state("RUNNING", 0, 0, 1, 0)) die(87);
    int rc = native_clean_task(output);
    s64 bytes = sc(62, output, 0, 2, 0, 0, 0);
    if (bytes < 0 || bytes >= MAX_OUTPUT_BYTES || sc(82, output, 0, 0, 0, 0, 0) < 0) { if (!rc) rc = 95; }
    if (close_fd(output) < 0 && !rc) rc = 95;
    int children = no_children() ? 0 : -1;
    if (children && !rc) rc = 94;
    if (state(rc ? "FAILED" : "DONE", rc, bytes, 1, children)) die(96);
    die(rc);
}

__attribute__((visibility("default"))) void _init(void)
{
    char cmd[256];
    s64 n = bounded(GATE_PATH, cmd, sizeof(cmd));
    if (n != (s64)(sizeof(debug_argv) - 1) || !same(cmd, debug_argv, sizeof(debug_argv) - 1)) return;
    if (disarm_preload()) die(92);
    if (sc(174, 0, 0, 0, 0, 0, 0) || sc(175, 0, 0, 0, 0, 0, 0)) die(97);
    if (!capture_control_parent_ready()) die(98);
    if (unlink_at(AT_FDCWD, KIT_SO_PATH) < 0) die(99);
    if (!capture_control_create()) die(100);
    s64 pid = sc(220, 17, 0, 0, 0, 0, 0);
    if (!pid) worker();
    if (pid < 0) { state("FAILED", 101, 0, 1, -1); die(101); }
    die(0);
}
