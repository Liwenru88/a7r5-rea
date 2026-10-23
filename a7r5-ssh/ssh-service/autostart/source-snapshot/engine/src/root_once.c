/* 一次性固定脚本执行器：保留已验证的精确触发门槛和预加载中和机制。 */
#ifdef A7R5_HOST_TEST
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <errno.h>
#else
#include <stddef.h>
typedef long ssize_t;
struct rlimit { unsigned long rlim_cur, rlim_max; };
extern int open(const char *, int, ...), close(int), fsync(int), ftruncate(int, long);
extern long lseek(int, long, int);
extern ssize_t read(int, void *, size_t), write(int, const void *, size_t);
extern int fork(void), setsid(void), setpgid(int, int), dup2(int, int), usleep(unsigned int);
extern int getdtablesize(void), waitpid(int, int *, int), kill(int, int);
extern int setrlimit(int, const struct rlimit *), execve(const char *, char *const[], char *const[]);
extern unsigned int getuid(void), geteuid(void);
extern int snprintf(char *, size_t, const char *, ...), rename(const char *, const char *);
extern int memcmp(const void *, const void *, size_t);
extern void *memset(void *, int, size_t);
extern void _exit(int);
extern int *__errno_location(void);
#define errno (*__errno_location())
#define O_RDONLY 0
#define O_WRONLY 1
#define O_RDWR 2
#define O_CREAT 64
#define O_EXCL 128
/* ARM64独立定义；不能沿用其他架构的数值。 */
#define O_NOFOLLOW 0100000
#define O_CLOEXEC 524288
#define RLIMIT_FSIZE 1
#define RLIMIT_CORE 4
#endif
#include "root_config.h"

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

static int allwrite(int fd, const char *data, size_t size)
{
    while (size) {
        ssize_t n = write(fd, data, size);
        if (n <= 0) return -1;
        data += n;
        size -= (size_t)n;
    }
    return 0;
}

static int disarm(void)
{
    char raw[1024], blank[512];
    int n = bounded(PRELOAD_PATH, raw, sizeof(raw));
    if (n != (int)sizeof(ARM_BYTES)-1 || memcmp(raw, ARM_BYTES, sizeof(ARM_BYTES)-1)) return -1;
    int fd = open(PRELOAD_PATH, O_RDWR | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -1;
    n = (int)read(fd, raw, sizeof(raw));
    if (n != (int)sizeof(ARM_BYTES)-1 || memcmp(raw, ARM_BYTES, sizeof(ARM_BYTES)-1)) { close(fd); return -1; }
    memset(blank, '\n', sizeof(blank));
    int failed = lseek(fd, 0, 0) != 0 || ftruncate(fd, 0) || allwrite(fd, blank, sizeof(blank)) || fsync(fd);
    if (close(fd)) failed = 1;
    n = bounded(PRELOAD_PATH, raw, sizeof(raw));
    return failed || n != 512 || memcmp(raw, blank, 512) ? -1 : 0;
}

static int state(const char *phase, int code, long bytes)
{
    char row[512];
    int n = snprintf(row, sizeof(row), "A7R5-ROOT-1 %s %s %d uid=%u euid=%u bytes=%ld\n",
                     RUN_ID, phase, code, getuid(), geteuid(), bytes);
    if (n <= 0 || (size_t)n >= sizeof(row)) return -1;
    int fd = open(STATE_PATH ".new", O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0) return -1;
    int failed = allwrite(fd, row, (size_t)n) || fsync(fd);
    if (close(fd)) failed = 1;
    return failed ? -1 : rename(STATE_PATH ".new", STATE_PATH);
}

static void worker(void)
{
    if (setsid() < 0) _exit(86);
    int nullfd = open("/dev/null", O_RDWR | O_CLOEXEC);
    if (nullfd < 0) _exit(80);
    for (int i = 0; i < 3; i++) if (dup2(nullfd, i) < 0) _exit(81);
    int limit = getdtablesize();
    if (limit < 3 || limit > 1048576) _exit(98);
    for (int i = 3; i < limit; i++) close(i);
    int output = open(OUTPUT_PATH, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (output < 0) { state("FAILED", 95, 0); _exit(95); }
    if (state("RUNNING", 0, 0)) _exit(95);
#ifdef A7R5_SSH_PREFLIGHT
    /* 仅新增只读 statvfs 补证，不改变原执行器的触发及中和门槛。 */
    extern int ssh_preflight_fs(int);
    if (ssh_preflight_fs(output)) { close(output); state("FAILED", 96, 0); _exit(96); }
#endif
    int pid = fork();
    if (pid < 0) { close(output); state("FAILED", 94, 0); _exit(94); }
    if (!pid) {
        if (setpgid(0, 0) || dup2(output, 1) < 0 || dup2(output, 2) < 0) _exit(81);
        close(output);
        struct rlimit size = { OUTPUT_LIMIT, OUTPUT_LIMIT }, core = {0, 0};
        if (setrlimit(RLIMIT_FSIZE, &size) || setrlimit(RLIMIT_CORE, &core)) _exit(97);
        char *const argv[] = {"/bin/sh", "-c", TASK_SCRIPT, "a7r5-root-once", NULL};
        char *const env[] = {"PATH=/bin:/sbin:/usr/bin:/usr/sbin", "LC_ALL=C", NULL};
        execve("/bin/sh", argv, env);
        _exit(127);
    }
    /* 双方尝试设置同一进程组，缩小超时发送信号前的竞态窗口。 */
    (void)setpgid(pid, pid);
    int status = 0, done = 0;
    for (unsigned int i = 0; i < TASK_SECONDS * 10; i++) {
        int got = waitpid(pid, &status, 1);
        if (got == pid) { done = 1; break; }
        if (got < 0) break;
        usleep(100000);
    }
    if (!done) {
        kill(-pid, 15);
        for (int i = 0; i < 20; i++) {
            if (waitpid(pid, &status, 1) == pid) { done = 1; break; }
            usleep(100000);
        }
        if (!done) {
            kill(-pid, 9);
            for (int i = 0; i < 20; i++) {
                if (waitpid(pid, &status, 1) == pid) { done = 1; break; }
                usleep(100000);
            }
        }
        /* 即使已终止，也不把超时当作可以自动退出服务的成功回执。 */
        close(output); state("TIMEOUT", 85, 0); _exit(85);
    }
    long bytes = lseek(output, 0, 2);
    int failed = bytes < 0 || bytes >= OUTPUT_LIMIT || fsync(output);
    if (close(output)) failed = 1;
    /* 不接受仍存活的同组后台任务；脱离进程组的任务仍须由使用约束排除。 */
    if (!kill(-pid, 0) || errno != 3) { state("FAILED", 99, bytes); _exit(99); }
    if (failed || (status & 127)) { state("FAILED", 83, bytes); _exit(83); }
    if (state("DONE", (status >> 8) & 255, bytes)) _exit(95);
    _exit(0);
}

static void entry(void)
{
    char raw[256];
    int n = bounded(GATE_PATH, raw, sizeof(raw));
    if (n != (int)sizeof(debug_argv)-1 || memcmp(raw, debug_argv, sizeof(debug_argv)-1)) return;
    if (disarm()) { state("FAILED", 92, 0); _exit(92); }
#ifndef A7R5_HOST_TEST
    if (getuid() || geteuid()) { state("FAILED", 93, 0); _exit(93); }
#endif
    int pid = fork();
    if (!pid) worker();
    if (pid < 0) { state("FAILED", 94, 0); _exit(94); }
    _exit(0);
}

#ifdef A7R5_HOST_TEST
int main(void) { entry(); return 100; }
#else
__attribute__((constructor)) static void start(void) { entry(); }
#endif
