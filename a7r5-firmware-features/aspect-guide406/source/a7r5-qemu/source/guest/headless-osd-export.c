/* One open inode: concurrent atomic snapshot replacement cannot mix frames. */
#include "headless-osd.h"
extern int open(const char *, int, ...), close(int);
extern long read(int, void *, unsigned long), write(int, const void *, unsigned long);
extern void _exit(int);
#ifdef __APPLE__
#define __errno_location __error
#define HOSD_MONOTONIC_CLOCK 6
#else
#define HOSD_MONOTONIC_CLOCK 1
#endif
extern int *__errno_location(void);
extern long lseek(int, long, int);
extern int strcmp(const char *, const char *), printf(const char *, ...);
struct hosd_time { long sec, nsec; };
extern int clock_gettime(int, struct hosd_time *), nanosleep(const struct hosd_time *, struct hosd_time *);
static int output(const void *data, unsigned long n) {
    const unsigned char *p = data;
    while (n) {
        long written = write(1, p, n);
        if (written < 0 && *__errno_location() == 4) continue;
        if (written <= 0 || (unsigned long)written > n) return -1;
        p += written; n -= written;
    }
    return 0;
}
static unsigned int word(const unsigned char *p, unsigned long i) { return p[2*i] | ((unsigned int)p[2*i+1] << 8); }
static void put16(unsigned char *p, unsigned int v) { p[0] = v; p[1] = v >> 8; }
/* 16位游程与字面量，无损还原整个容器，接收端仍核对原始 FNV/SHA。 */
unsigned long hosd_rle16(const unsigned char *raw, unsigned long bytes, unsigned char *packed) {
    if (bytes != HOSD_BYTES || (bytes & 1)) return 0;
    const char magic[8] = {'H','O','S','D','R','L','0','1'};
    for (unsigned int k = 0; k < 8; ++k) packed[k] = magic[k];
    for (unsigned int k = 0; k < 4; ++k) packed[8+k] = bytes >> (k*8);
    unsigned long i = 0, out = 12, words = bytes / 2;
    while (i < words) {
        unsigned long run = 1;
        while (i+run < words && run < 32767 && word(raw,i+run) == word(raw,i)) ++run;
        if (run >= 3) {
            put16(packed+out, 0x8000U | run); put16(packed+out+2, word(raw,i)); out += 4; i += run;
        } else {
            unsigned long start = i++;
            while (i < words && i-start < 32767) {
                if (i+2 < words && word(raw,i) == word(raw,i+1) && word(raw,i) == word(raw,i+2)) break;
                ++i;
            }
            put16(packed+out, i-start); out += 2;
            for (unsigned long k = start*2; k < i*2; ++k) packed[out++] = raw[k];
        }
    }
    return out;
}
static int export_fd(int fd) {
    static const char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    static unsigned char container[HOSD_BYTES], packed[HOSD_BYTES * 2];
    char encoded[1025];
    unsigned long total = 0;
    while (total < HOSD_BYTES) {
        long n = read(fd, container+total, HOSD_BYTES-total);
        if (n < 0 && *__errno_location() == 4) continue;
        if (n <= 0 || (unsigned long)n > HOSD_BYTES-total) { close(fd); return 1; }
        total += n;
    }
    unsigned char extra;
    if (read(fd, &extra, 1) != 0 || close(fd)) return 1;
    unsigned long bytes = hosd_rle16(container, total, packed);
    if (!bytes || output("\nHEADLESS_OSD_BEGIN\n", 20)) return 1;
    for (unsigned long offset = 0; offset < bytes; offset += 768) {
        unsigned long n = bytes-offset < 768 ? bytes-offset : 768;
        const unsigned char *raw = packed+offset;
        unsigned int k = 0;
        for (long i = 0; i < n; i += 3) {
            unsigned int v = (unsigned int)raw[i] << 16;
            if (i + 1 < n) v |= (unsigned int)raw[i + 1] << 8;
            if (i + 2 < n) v |= raw[i + 2];
            encoded[k++] = alphabet[v >> 18]; encoded[k++] = alphabet[(v >> 12) & 63];
            encoded[k++] = i + 1 < n ? alphabet[(v >> 6) & 63] : '=';
            encoded[k++] = i + 2 < n ? alphabet[v & 63] : '=';
        }
        encoded[k++] = '\n';
        if (output(encoded, k)) return 1;
    }
    return output("HEADLESS_OSD_END\n", 17) ? 1 : 0;
}
int hosd_export(const char *path) {
    int fd = open(path, 0);
    return fd < 0 ? 1 : export_fd(fd);
}
static long monotonic_ms(void) {
    struct hosd_time t;
    return clock_gettime(HOSD_MONOTONIC_CLOCK, &t) ? -1 : t.sec * 1000 + t.nsec / 1000000;
}
static unsigned long u64le(const unsigned char *p) {
    unsigned long v = 0;
    for (int i = 7; i >= 0; --i) v = (v << 8) | p[i];
    return v;
}
/* 等待新提交且像素来源连续 20ms 未变化；元数据持续提交不会阻塞稳定画面。 */
int hosd_wait_export(const char *path, unsigned long after, long timeout_ms) {
    long start = monotonic_ms(), changed = start;
    unsigned long candidate = 0;
    if (start < 0 || timeout_ms <= 0 || timeout_ms > 2000) return 2;
    for (;;) {
        long now = monotonic_ms();
        if (now < start || now - start >= timeout_ms) return 2;
        int fd = open(path, 0);
        if (fd < 0) return 1;
        unsigned char header[HOSD_HEADER];
        long n = read(fd, header, sizeof header);
        if (n != sizeof header || header[0] != 'H' || header[1] != 'O' ||
            header[2] != 'S' || header[3] != 'D' || header[4] != 'A' ||
            header[5] != 'P' || header[6] != '0' || header[7] != '2') { close(fd); return 1; }
        unsigned long seq = u64le(header + 8), source = u64le(header + 120);
        if (!source || source > seq) { close(fd); return 1; }
        if (source != candidate) { candidate = source; changed = now; }
        if (seq > after && now - changed >= 20) {
            if (lseek(fd, 0, 0) != 0) { close(fd); return 1; }
            printf("HEADLESS_OSD_READY after=%lu sequence=%lu wait_ms=%ld\n", after, seq, now-start);
            return export_fd(fd);
        }
        if (close(fd)) return 1;
        struct hosd_time delay = {0, 5000000};
        if (nanosleep(&delay, 0) && *__errno_location() != 4) return 1;
    }
}
#ifndef HOSD_EXPORT_TEST
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc, char **argv) {
    if (argc == 1) return hosd_export(HOSD_PATH);
    if (argc != 3 || strcmp(argv[1], "--after")) return 2;
    unsigned long after = 0;
    if (!*argv[2]) return 2;
    for (const char *p = argv[2]; *p; ++p) {
        if (*p < '0' || *p > '9' || after > (~0UL - (unsigned long)(*p-'0')) / 10) return 2;
        after = after * 10 + (unsigned long)(*p-'0');
    }
    return hosd_wait_export(HOSD_PATH, after, 2000);
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
#endif
