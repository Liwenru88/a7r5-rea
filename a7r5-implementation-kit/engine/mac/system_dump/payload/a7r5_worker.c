/* A7R5 一次性工作进程。只执行构建时封存的两个任务，无任意命令邮箱。 */
#ifdef A7R5_HOST_TEST
#define _DARWIN_C_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/wait.h>
#include <signal.h>
#include <errno.h>
#include <sys/statvfs.h>
#else
/* 只声明本文件使用的稳定 libc ABI；不混用 macOS 的系统结构与标志。 */
#include <stddef.h>
typedef long ssize_t;
extern int open(const char *, int, ...), close(int), fsync(int), ftruncate(int, long);
extern long lseek(int, long, int);
extern ssize_t read(int, void *, size_t), write(int, const void *, size_t);
extern int fork(void), setsid(void), dup2(int, int), usleep(unsigned int);
extern int getdtablesize(void);
extern int waitpid(int, int *, int), kill(int, int), execve(const char *, char *const[], char *const[]);
extern unsigned int getuid(void), geteuid(void);
extern void _exit(int);
extern int rename(const char *, const char *), unlink(const char *), ioctl(int, unsigned long, ...);
extern int snprintf(char *, size_t, const char *, ...), sscanf(const char *, const char *, ...);
extern size_t strlen(const char *);
extern int memcmp(const void *, const void *, size_t), strcmp(const char *, const char *);
extern void *memcpy(void *, const void *, size_t), *memset(void *, int, size_t);
extern int *__errno_location(void);
extern int statvfs(const char *, void *);
#define errno (*__errno_location())
#define O_RDONLY 0
#define O_WRONLY 1
#define O_RDWR 2
#define O_CREAT 64
#define O_EXCL 128
#define O_NOFOLLOW 131072
#define O_CLOEXEC 524288
#endif
#include "config.h"

static const char debug_argv[] = "/bin/sh\0-c\0/bin/date -s 070421422017.26\0";
static int bounded(const char *path, char *out, size_t cap)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -1;
    size_t used = 0;
    while (used < cap) {
        ssize_t n = read(fd, out + used, cap - used);
        if (n < 0) { close(fd); return -1; }
        if (!n) break;
        used += (size_t)n;
    }
    char extra;
    ssize_t n = read(fd, &extra, 1);
    if (close(fd) || n != 0) return -1;
    return (int)used;
}

static int allwrite(int fd, const char *data, size_t length)
{
    while (length) {
        ssize_t n = write(fd, data, length);
        if (n <= 0) return -1;
        data += n;
        length -= (size_t)n;
    }
    return 0;
}

static int atomic_state(const char *phase, int code, const char *card)
{
    char data[512];
    int saved_errno = code ? errno : 0;
    int n = snprintf(data, sizeof(data), "A7R5-STATE-1 %s %s %d %s uid=%u euid=%u errno=%d\n",
                     RUN_ID, phase, code, card, getuid(), geteuid(), saved_errno);
    if (n <= 0 || (size_t)n >= sizeof(data)) return -1;
    int fd = open(STATE_PATH ".new", O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0) return -1;
    int result = allwrite(fd, data, (size_t)n);
    if (fsync(fd)) result = -1;
    if (close(fd)) result = -1;
    if (result || rename(STATE_PATH ".new", STATE_PATH)) return -1;
    return 0;
}

static int matches_gate(void)
{
    char raw[256];
    int n = bounded(GATE_PATH, raw, sizeof(raw));
    return n == (int)sizeof(debug_argv)-1 && memcmp(raw, debug_argv, sizeof(debug_argv)-1) == 0;
}

static int disarm(void)
{
    char raw[1024], blank[512];
    int n = bounded(PRELOAD_PATH, raw, sizeof(raw));
    if (n != (int)sizeof(ARM_BYTES)-1 || memcmp(raw, ARM_BYTES, sizeof(ARM_BYTES)-1)) return -1;
    int fd = open(PRELOAD_PATH, O_RDWR | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -1;
    /* 再在将要修改的同一描述符上比较，不以读取失败推断不存在。 */
    n = (int)read(fd, raw, sizeof(raw));
    if (n != (int)sizeof(ARM_BYTES)-1 || memcmp(raw, ARM_BYTES, sizeof(ARM_BYTES)-1)) { close(fd); return -1; }
    memset(blank, '\n', sizeof(blank));
    int result = 0;
    if (lseek(fd, 0, 0) != 0 || ftruncate(fd, 0) || allwrite(fd, blank, sizeof(blank)) || fsync(fd)) result = -1;
    if (close(fd)) result = -1;
    if (result) return -1;
    n = bounded(PRELOAD_PATH, raw, sizeof(raw));
    return n == 512 && memcmp(raw, blank, 512) == 0 ? 0 : -1;
}

static unsigned long number32(const unsigned char *p)
{
    return (unsigned long)p[0] | ((unsigned long)p[1]<<8) | ((unsigned long)p[2]<<16) | ((unsigned long)p[3]<<24);
}

static int card_header_matches(const unsigned char *sb, unsigned long long bytes)
{
    return bytes == CARD_BYTES && sb[56] == 0x53 && sb[57] == 0xef &&
        number32(sb+24) == 2 && number32(sb+4)*4096ULL == CARD_BYTES &&
        number32(sb+92) == 0 && number32(sb+96) == 2 && number32(sb+100) == 3 &&
        sb[88] == 128 && sb[89] == 0 && !memcmp(sb+104, CARD_UUID, 16);
}

static int identify_card(char *out, size_t cap)
{
#ifdef A7R5_HOST_TEST
    char data[256];
    int n = bounded(TEST_CARD_PATH, data, sizeof(data));
    if (n != (int)sizeof(CARD_MARKER)-1 || memcmp(data, CARD_MARKER, sizeof(CARD_MARKER)-1)) return -1;
    return snprintf(out, cap, "%s", TEST_CARD_DEVICE) > 0 ? 0 : -1;
#else
    char lines[32769];
    int n = bounded("/proc/partitions", lines, sizeof(lines)-1);
    if (n < 0) return -1;
    lines[n] = 0;
    int matches = 0;
    char *row = lines;
    while (*row) {
        char name[64] = {0};
        unsigned long major, minor, kib;
        if (sscanf(row, "%lu %lu %lu %63s", &major, &minor, &kib, name) == 4 &&
                strlen(name) == 5 && !memcmp(name, "mmc", 3) &&
                (name[3] == 'a' || name[3] == 'b') && name[4] >= '1' && name[4] <= '4') {
            char path[96];
            snprintf(path, sizeof(path), "/dev/%s", name);
            int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
            if (fd >= 0) {
                unsigned long long bytes = 0;
                unsigned char sb[1024];
                if (!ioctl(fd, 0x80081272UL, &bytes) && bytes == CARD_BYTES &&
                        lseek(fd, 1024, 0) == 1024 && read(fd, sb, sizeof(sb)) == 1024 &&
                        card_header_matches(sb, bytes)) {
                    if (++matches == 1) snprintf(out, cap, "%s", path);
                }
                close(fd);
            }
        }
        while (*row && *row != '\n') row++;
        if (*row) row++;
    }
    if (matches != 1) return -1;
#ifdef EXPECTED_CARD_DEVICE
    /* 新实机材料绑定已诊断的路径；不因另一张卡同样匹配而改挂。 */
    if (strcmp(out, EXPECTED_CARD_DEVICE)) return -1;
#endif
    return 0;
#endif
}

static int source_name(const char *name)
{
#if DUMP_PLAINTEXT_ONLY
    /* 标准模式从选源阶段排除物理节点，不先读取或转存再在主机丢弃。 */
    if (name[0] == 'c') {
        if (strlen(name) <= 8 || name[8] < '0' || name[8] > '9') return 0;
    } else if (strlen(name) <= 8 || memcmp(name, "nflashaB", 8)) return 0;
#endif
    const char *p = name;
    if (*p == 'p' || *p == 'c') p++;
    if (strlen(p) < 7 || memcmp(p, "nflasha", 7)) return 0;
    p += 7;
    if (*p == 'B') {
        if (name[0] != 'n') return 0;
        p++;
        if (!*p) return 0;
    }
    while (*p) { if (*p < '0' || *p > '9') return 0; p++; }
    return 1;
}

static int source_inventory(int verify, unsigned long long *total)
{
    char lines[32769], selected[32768];
    int n = bounded(PARTS_SOURCE, lines, sizeof(lines)-1);
    if (n < 0) return -1;
    lines[n] = 0;
    size_t used = 0;
    unsigned count = 0;
    *total = 0;
    char *row = lines;
    while (*row) {
        char name[64] = {0};
        unsigned long major, minor, kib;
        if (sscanf(row, "%lu %lu %lu %63s", &major, &minor, &kib, name) == 4 && source_name(name)) {
            if (!kib || kib > (1UL<<30) || ++count > 128) return -1;
            char path[1024];
            snprintf(path, sizeof(path), "%s/%s", SOURCE_ROOT, name);
            int fd = open(path, O_RDONLY | O_CLOEXEC);
            if (fd < 0) return -1;
            unsigned long long bytes = 0;
#ifdef A7R5_HOST_TEST
            long length = lseek(fd, 0, 2);
            bytes = length > 0 ? (unsigned long long)length : 0;
            lseek(fd, 0, 0);
            int got_size = 0;
#else
            int got_size = ioctl(fd, 0x80081272UL, &bytes);
#endif
            char prefix[512];
            int valid = !got_size && bytes == (unsigned long long)kib*1024 && read(fd, prefix, sizeof(prefix)) == 512;
            if (close(fd) || !valid) return -1;
            int length2 = snprintf(selected+used, sizeof(selected)-used, "%s %lu %lu %llu\n", name, major, minor, bytes);
            if (length2 <= 0 || (size_t)length2 >= sizeof(selected)-used) return -1;
            used += (size_t)length2;
            *total += bytes;
        }
        while (*row && *row != '\n') row++;
        if (*row) row++;
    }
    if (!count) return -1;
    if (verify) {
        char before[32768];
        n = bounded(SOURCES_PATH, before, sizeof(before));
        return n == (int)used && !memcmp(before, selected, used) ? 0 : -1;
    }
    int fd = open(SOURCES_PATH, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0) return -1;
    int result = allwrite(fd, selected, used);
    if (fsync(fd)) result = -1;
    if (close(fd)) result = -1;
    return result;
}

static int sufficient_space(unsigned long long total)
{
    unsigned long long free_bytes = 0;
#ifdef A7R5_HOST_TEST
    struct statvfs info;
    if (statvfs(MOUNT_PATH, &info)) return 0;
    free_bytes = (unsigned long long)info.f_bavail * info.f_frsize;
#ifdef TEST_FREE_BYTES
    free_bytes = TEST_FREE_BYTES;
#endif
#else
    /* AArch64 glibc 的 statvfs 前五项为 bsize/frsize/blocks/bfree/bavail，均为 64 位。 */
    unsigned long fields[32] = {0};
    if (statvfs(MOUNT_PATH, fields) || !fields[1]) return 0;
    free_bytes = (unsigned long long)fields[4] * fields[1];
#endif
    return free_bytes >= total + total/10 + 134217728ULL;
}

static void detach_stdio(void)
{
    int fd = open("/dev/null", O_RDWR | O_CLOEXEC);
    if (fd < 0) _exit(80);
    for (int i = 0; i < 3; i++) if (dup2(fd, i) < 0) _exit(81);
    if (fd > 2) close(fd);
}

static int task(const char *script, const char *card, unsigned int seconds)
{
    int pid = fork();
    if (pid < 0) return 82;
    if (!pid) {
        /* 所有任务及参数在构建时固定；环境不继承预加载等主进程变量。 */
        char *const argv[] = {"/bin/sh", "-c", (char *)script, "a7r5-fixed-task", (char *)card, NULL};
        char *const env[] = {"PATH=/bin:/sbin:/usr/bin:/usr/sbin", "LC_ALL=C", NULL};
        execve("/bin/sh", argv, env);
        _exit(127);
    }
    for (unsigned int i = 0; i < seconds * 10; i++) {
        int status = 0, got = waitpid(pid, &status, 1);
        if (got == pid) return (status & 127) ? 83 : (status >> 8) & 255;
        if (got < 0) return 84;
        usleep(100000);
    }
    /* 超时只发终止信号，不能保证内核存储调用撤销；不得报告已卸载。 */
    kill(pid, 15);
    return 85;
}

static void worker(void)
{
    char card[96], again[96], token[128];
    unsigned long long total = 0;
    if (setsid() < 0) { atomic_state("FAILED", 86, "-"); _exit(86); }
    detach_stdio();
    int fd_limit = getdtablesize();
    if (fd_limit < 3 || fd_limit > 1048576) { atomic_state("FAILED", 98, "-"); _exit(98); }
    for (int fd = 3; fd < fd_limit; fd++) close(fd);
    if (identify_card(card, sizeof(card))) { atomic_state("FAILED", 87, "-"); _exit(87); }
    if (source_inventory(0, &total)) { atomic_state("FAILED", 97, card); _exit(97); }
    int code = task(PREPARE_SCRIPT, card, 60);
    if (!code && !sufficient_space(total)) code = 35;
    if (code) {
        if (code == 83 || code == 84 || code == 85) {
            /* 子任务可能还有后代或阻塞调用，不能靠一次 umount 宣称撤销。 */
            atomic_state("FAILED", code, card); _exit(code);
        }
        int cleaned = task(CLEANUP_SCRIPT, card, 10);
        atomic_state(cleaned ? "FAILED" : "FAILED_UNMOUNTED", code, card);
        _exit(code);
    }
    if (atomic_state("READY", 0, card)) _exit(88);
    for (unsigned int i = 0; i < WAIT_POLLS; i++) {
        int n = bounded(GO_PATH, token, sizeof(token));
        if (n >= 0) {
            if (n == (int)sizeof(ABORT_BYTES)-1 && !memcmp(token, ABORT_BYTES, sizeof(ABORT_BYTES)-1)) {
                if (unlink(GO_PATH)) { atomic_state("FAILED", 96, card); _exit(96); }
                code = task(CLEANUP_SCRIPT, card, 10);
                atomic_state(code ? "FAILED" : "ABORTED_UNMOUNTED", code, card);
                _exit(code);
            }
            if (n != (int)sizeof(GO_BYTES)-1 || memcmp(token, GO_BYTES, sizeof(GO_BYTES)-1)) {
                atomic_state("FAILED", 89, card); _exit(89);
            }
            if (unlink(GO_PATH) || identify_card(again, sizeof(again)) || strcmp(card, again) ||
                    source_inventory(1, &total) || !sufficient_space(total)) {
                atomic_state("FAILED", 90, card); _exit(90);
            }
            atomic_state("RUNNING", 0, card);
            code = task(DUMP_SCRIPT, card, DUMP_SECONDS);
            /* DONE 只在脚本完成 sync 与成功 umount 后报告。 */
            atomic_state(code ? "FAILED" : "DONE", code, card);
            _exit(code);
        }
        usleep(100000);
    }
    /* 只有未开始转存的空闲过期才尝试固定卸载；不撤销正在运行的转存。 */
    code = task(CLEANUP_SCRIPT, card, 10);
    atomic_state(code ? "EXPIRED" : "EXPIRED_UNMOUNTED", 91, card);
    _exit(91);
}

static void entry(void)
{
    if (!matches_gate()) return;
    if (disarm()) { atomic_state("FAILED", 92, "-"); _exit(92); }
#ifndef A7R5_HOST_TEST
    if (getuid() || geteuid()) { atomic_state("FAILED", 93, "-"); _exit(93); }
#endif
    int pid = fork();
    if (!pid) worker();
    if (pid < 0) { atomic_state("FAILED", 94, "-"); _exit(94); }
    _exit(0);
}

#ifdef A7R5_HOST_TEST
int main(void) { entry(); return 100; }
#else
__attribute__((constructor)) static void a7r5_start(void) { entry(); }
#endif
