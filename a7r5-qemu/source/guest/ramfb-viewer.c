/* Independent HOSDAP02 consumer. No producer ACKs, locks or camera MMIO. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <signal.h>
#include "headless-osd.h"

#define RAMFB_BASE UINT64_C(0x41e100000)
#define RAMFB_SIZE 0x500000U
#define RAMFB_SLOT 0x200000U
#define RAMFB_DMA (RAMFB_SIZE - 0x1000U)
#define RAMFB_CFG (RAMFB_DMA + 64U)
#define FW_BASE UINT64_C(0x09020000)
#define XRGB_BYTES (640U * 480U * 4U)
_Static_assert(HOSD_BYTES == 639458 && XRGB_BYTES <= RAMFB_SLOT, "layout");
#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "ramfb viewer requires a little-endian guest"
#endif

static int reserved(const char *cmdline) {
    static const char token[] = "memrsv=0x00500000@0x41e100000:uc";
    const char *p = strstr(cmdline, token);
    return p && (p == cmdline || p[-1] == ' ') &&
        (p[sizeof token - 1] == 0 || p[sizeof token - 1] == ' ' || p[sizeof token - 1] == '\n');
}

static uint64_t le(const unsigned char *p, unsigned n) {
    uint64_t v = 0;
    for (unsigned i = 0; i < n; ++i) v |= (uint64_t)p[i] << (8 * i);
    return v;
}
static uint64_t be(const unsigned char *p, unsigned n) {
    uint64_t v = 0;
    for (unsigned i = 0; i < n; ++i) v = (v << 8) | p[i];
    return v;
}
static void putbe(unsigned char *p, uint64_t v, unsigned n) {
    while (n) { p[--n] = v; v >>= 8; }
}
static uint64_t fnv(const unsigned char *p, unsigned n, int container) {
    uint64_t h = UINT64_C(14695981039346656037);
    for (unsigned i = 0; i < n; ++i)
        h = (h ^ ((container && i >= 40 && i < 48) ? 0 : p[i])) * UINT64_C(1099511628211);
    return h;
}
static const char *header_error(const unsigned char *p) {
    uint64_t seq = le(p + 8, 8), source = le(p + 120, 8), phys = le(p + 32, 8);
    unsigned cmd = le(p + 56, 4);
    if (memcmp(p, "HOSDAP02", 8)) return "magic";
    if (le(p + 20, 4) != 640 || le(p + 24, 4) != 480 || le(p + 28, 4) != 1 ||
        le(p + 48, 4) != HOSD_PIXELS || le(p + 52, 4) != sizeof(struct hosd_metadata)) return "format/length";
    if (!seq || !source || source > seq || (cmd != 0x1003 && cmd != 0x1005) ||
        (cmd == 0x1003 && source != seq) || phys < UINT64_C(0x410000000) ||
        phys > UINT64_C(0x500000000) - HOSD_PIXELS) return "identity/bounds";
    if (le(p + 64, 2) != 0x1003 || le(p + 72, 4) != le(p + 16, 4) ||
        le(p + 80, 2) || le(p + 84, 2) != 640 || le(p + 86, 2) != 480 ||
        le(p + 100, 2) != 0x1002 || le(p + 108, 4) != cmd ||
        (cmd == 0x1005 && le(p + 112, 2) != 0x1005)) return "descriptor/pairing";
    return NULL;
}
static const char *validate(const unsigned char *p, size_t n) {
    if (n != HOSD_BYTES) return "container length";
    const char *err = header_error(p);
    if (err) return err;
    return fnv(p, n, 1) == le(p + 40, 8) ? NULL : "container hash";
}
static void convert(const unsigned char *p, unsigned char *out) {
    /* Straight RGBA4444 over black, rounded to nearest 8-bit channel; X=0. */
    for (unsigned i = 0; i < HOSD_PIXELS / 2; ++i) {
        unsigned v = le(p + 2 * i, 2), a = v & 15;
        out[4*i] = (((v >> 4) & 15) * 17 * a + 7) / 15;
        out[4*i+1] = (((v >> 8) & 15) * 17 * a + 7) / 15;
        out[4*i+2] = ((v >> 12) * 17 * a + 7) / 15;
        out[4*i+3] = 0;
    }
}
static int config(unsigned char *cfg, unsigned char *dma, unsigned slot, unsigned selector) {
    if (slot > 1 || selector < 0x20 || selector >= 0x4000) return -1;
    putbe(cfg, RAMFB_BASE + slot * RAMFB_SLOT, 8);
    putbe(cfg + 8, 0x34325258, 4); /* DRM_FORMAT_XRGB8888 ('X','R','2','4') */
    putbe(cfg + 12, 0, 4); putbe(cfg + 16, 640, 4);
    putbe(cfg + 20, 480, 4); putbe(cfg + 24, 2560, 4);
    putbe(dma, (selector << 16) | 0x18, 4);
    putbe(dma + 4, 28, 4); putbe(dma + 8, RAMFB_BASE + RAMFB_CFG, 8);
    return 0;
}
static void barrier(void) {
#ifdef __aarch64__
    __asm__ volatile("dsb sy" ::: "memory");
#else
    __sync_synchronize();
#endif
}
/* Narrow test seam: bus accesses only; all protocol decisions remain here. */
struct bus {
    void *ctx;
    void (*select)(void *, uint16_t);
    unsigned char (*data)(void *);
    uint64_t (*signature)(void *);
    void (*kick)(void *, uint64_t);
    void (*pause)(void *);
};
static void bus_read(struct bus *b, unsigned char *p, unsigned n) {
    for (unsigned i = 0; i < n; ++i) p[i] = b->data(b->ctx);
}
static int discover(struct bus *b) {
    unsigned char raw[64];
    b->select(b->ctx, 0); bus_read(b, raw, 4);
    if (memcmp(raw, "QEMU", 4)) return -1;
    b->select(b->ctx, 1); bus_read(b, raw, 4);
    if (!(le(raw, 4) & 2) || b->signature(b->ctx) != UINT64_C(0x51454d5520434647)) return -1;
    b->select(b->ctx, 0x19); bus_read(b, raw, 4);
    unsigned count = be(raw, 4);
    if (!count || count > 256) return -1;
    for (unsigned i = 0; i < count; ++i) {
        bus_read(b, raw, 64);
        if (!memcmp(raw + 8, "etc/ramfb\0", 10)) {
            unsigned sel = be(raw + 4, 2);
            return be(raw, 4) == 28 && sel >= 0x20 && sel < 0x4000 ? (int)sel : -1;
        }
    }
    return -1;
}
static int submit(struct bus *b, unsigned char *pool, unsigned slot, unsigned selector) {
    barrier(); /* Finish the inactive scanout before publishing its descriptor. */
    if (config(pool + RAMFB_CFG, pool + RAMFB_DMA, slot, selector)) return -1;
    barrier();
    b->kick(b->ctx, RAMFB_BASE + RAMFB_DMA);
    for (unsigned i = 0; i < 100; ++i) {
        barrier();
        uint32_t ctl = __builtin_bswap32(*(volatile uint32_t *)(pool + RAMFB_DMA));
        if (!ctl) return 0;
        if (ctl & 1) return -1;
        b->pause(b->ctx);
    }
    return -2;
}
static int read_all(int fd, unsigned char *p, size_t n) {
    while (n) {
        ssize_t got = read(fd, p, n);
        if (got < 0 && errno == EINTR) continue;
        if (got <= 0) return -1;
        p += got; n -= got;
    }
    return 0;
}
struct consumer {
    int fd;
    struct stat st;
    unsigned char header[HOSD_HEADER];
    uint64_t pixel_hash;
};
static int view_stat(int fd, struct stat *st) {
#ifdef __aarch64__
    /* Firmware glibc 2.25 exports the versioned ABI, not glibc 2.33's fstat. */
    extern int __fxstat(int, int, struct stat *);
    return __fxstat(0, fd, st);
#else
    return fstat(fd, st);
#endif
}
/* Caller commits only after successful DMA (or verified retained source). */
static int snapshot(struct consumer *s, int fd, unsigned char *raw, struct stat *st, const char **err) {
    if (view_stat(fd, st) || !S_ISREG(st->st_mode) || st->st_size != HOSD_BYTES ||
        read_all(fd, raw, HOSD_HEADER)) { *err = "read/stat/length"; return -1; }
    *err = header_error(raw);
    if (*err) return -1;
    if (s->fd >= 0 && st->st_dev == s->st.st_dev && st->st_ino == s->st.st_ino &&
        st->st_mtim.tv_sec == s->st.st_mtim.tv_sec && st->st_mtim.tv_nsec == s->st.st_mtim.tv_nsec &&
        st->st_ctim.tv_sec == s->st.st_ctim.tv_sec && st->st_ctim.tv_nsec == s->st.st_ctim.tv_nsec &&
        !memcmp(raw, s->header, HOSD_HEADER)) return 0;
    unsigned char extra;
    if (read_all(fd, raw + HOSD_HEADER, HOSD_BYTES - HOSD_HEADER) || read(fd, &extra, 1) != 0) {
        *err = "read/EOF"; return -1;
    }
    *err = validate(raw, HOSD_BYTES);
    if (*err) return -1;
    if (s->fd >= 0) {
        if (le(raw + 8, 8) == le(s->header + 8, 8) && memcmp(raw, s->header, HOSD_HEADER)) {
            *err = "sequence reused"; return -1;
        }
        if (le(raw + 8, 8) < le(s->header + 8, 8) || le(raw + 120, 8) < le(s->header + 120, 8)) {
            *err = "sequence rollback"; return -1;
        }
        if (le(raw + 120, 8) == le(s->header + 120, 8)) {
            if (memcmp(raw + 16, s->header + 16, 24) || memcmp(raw + 64, s->header + 64, 36) ||
                fnv(raw + HOSD_HEADER + sizeof(struct hosd_metadata), HOSD_PIXELS, 0) != s->pixel_hash) {
                *err = "retained source changed"; return -1;
            }
            return 1;
        }
    }
    return 2;
}
static void commit(struct consumer *s, int fd, struct stat *st, const unsigned char *raw) {
    if (s->fd >= 0) close(s->fd);
    s->fd = fd; s->st = *st; memcpy(s->header, raw, HOSD_HEADER);
    s->pixel_hash = fnv(raw + HOSD_HEADER + sizeof(struct hosd_metadata), HOSD_PIXELS, 0);
}

#ifndef RAMFB_TEST
static void fault(int signo) {
    (void)signo;
    static const char line[] = "RAMFB_FAIL reason=MMIO/memory signal fault; no display proof\n";
    int fd = open("/tmp/ramfb-viewer.log", O_CREAT | O_WRONLY | O_APPEND, 0600);
    if (fd >= 0) { ssize_t ignored = write(fd, line, sizeof line - 1); (void)ignored; }
    fd = open("/tmp/ramfb-viewer.status", O_CREAT | O_WRONLY | O_TRUNC, 0600);
    if (fd >= 0) { ssize_t ignored = write(fd, line, sizeof line - 1); (void)ignored; }
    _exit(1);
}
static void mm_select(void *ctx, uint16_t key) {
    *(volatile uint16_t *)((unsigned char *)ctx + 8) = __builtin_bswap16(key); barrier();
}
static unsigned char mm_data(void *ctx) { return *(volatile unsigned char *)ctx; }
static uint64_t mm_signature(void *ctx) {
    return __builtin_bswap64(*(volatile uint64_t *)((unsigned char *)ctx + 16));
}
static void mm_kick(void *ctx, uint64_t addr) {
    *(volatile uint64_t *)((unsigned char *)ctx + 16) = __builtin_bswap64(addr); barrier();
}
static void mm_pause(void *ctx) { (void)ctx; usleep(1000); }
static void record(const char *event, const char *reason, const unsigned char *h, unsigned slot) {
    char line[512];
    int n = snprintf(line, sizeof line,
        "RAMFB_%s reason=%s errno=%d seq=%llu pixel_source=%llu source_phys=0x%llx hash=%016llx scanout=0x%llx\n",
        event, reason, errno, (unsigned long long)le(h+8,8), (unsigned long long)le(h+120,8),
        (unsigned long long)le(h+32,8), (unsigned long long)le(h+40,8),
        (unsigned long long)(RAMFB_BASE + slot * RAMFB_SLOT));
    int fd = open("/tmp/ramfb-viewer.log", O_CREAT | O_WRONLY | O_APPEND, 0600);
    if (fd >= 0) {
        if (lseek(fd, 0, SEEK_END) > 65536 - n) ftruncate(fd, 0);
        if (write(fd, line, n) != n) dprintf(2, "RAMFB_LOG_WRITE_FAILED\n");
        close(fd);
    }
    fd = open("/tmp/ramfb-viewer.status", O_CREAT | O_WRONLY | O_TRUNC, 0600);
    if (fd >= 0) { if (write(fd, line, n) != n) dprintf(2, "RAMFB_STATUS_WRITE_FAILED\n"); close(fd); }
    if (!strcmp(event, "FAIL")) dprintf(2, "%s", line);
}
static int run(void) {
    static unsigned char raw[HOSD_BYTES];
    struct consumer s = {.fd = -1};
    signal(SIGBUS, fault); signal(SIGSEGV, fault);
    int lock = open("/tmp/ramfb-viewer.lock", O_CREAT | O_RDWR, 0600);
    if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB)) { record("FAIL", "already running/lock", raw, 0); return 1; }
    char cmdline[8192];
    int command = open("/proc/cmdline", O_RDONLY);
    ssize_t count = command >= 0 ? read(command, cmdline, sizeof cmdline - 1) : -1;
    if (command >= 0) close(command);
    if (count <= 0 || count == sizeof cmdline - 1) { record("FAIL", "read cmdline", raw, 0); return 1; }
    cmdline[count] = 0;
    if (!reserved(cmdline)) { record("FAIL", "scanout reservation missing", raw, 0); return 1; }
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) { record("FAIL", "open /dev/mem", raw, 0); return 1; }
    void *mmio = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, FW_BASE);
    if (mmio == MAP_FAILED) { record("FAIL", "mmap fw_cfg", raw, 0); return 1; }
    struct bus b = {mmio, mm_select, mm_data, mm_signature, mm_kick, mm_pause};
    int selector = discover(&b);
    if (selector < 0) { record("FAIL", "fw_cfg signature/DMA/etc/ramfb", raw, 0); return 1; }
    unsigned char *pool = mmap(NULL, RAMFB_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, RAMFB_BASE);
    close(fd);
    if (pool == MAP_FAILED) { record("FAIL", "mmap reserved scanout", raw, 0); return 1; }
    char init[160];
    snprintf(init, sizeof init, "fw_cfg=0x9020000 selector=0x%x DMA=0x%llx config=0x%llx awaiting snapshot",
             selector, (unsigned long long)(RAMFB_BASE + RAMFB_DMA),
             (unsigned long long)(RAMFB_BASE + RAMFB_CFG));
    record("INIT", init, raw, 0);
    unsigned slot = 1, ticks = 0;
    for (;;) {
        usleep(100000); ++ticks;
        int next = open(HOSD_PATH, O_RDONLY | O_NONBLOCK | O_NOFOLLOW);
        if (next < 0) {
            if (ticks == 1 || ticks % 100 == 0) record("WAIT", "snapshot unavailable", s.header, slot);
            continue;
        }
        struct stat st;
        const char *err = NULL;
        int action = snapshot(&s, next, raw, &st, &err);
        if (action <= 0) {
            close(next);
            if (action < 0) record("REJECT", err, raw, slot);
            continue;
        }
        if (action == 2) {
            unsigned target = slot ^ 1;
            convert(raw + HOSD_HEADER + sizeof(struct hosd_metadata), pool + target * RAMFB_SLOT);
            int result = submit(&b, pool, target, selector);
            if (result) {
                record("FAIL", result == -2 ? "DMA timeout; state uncertain" : "DMA error", raw, slot);
                close(next); return 1;
            }
            slot = target;
        }
        commit(&s, next, &st, raw);
        record(action == 2 ? "SUBMITTED" : "RETAINED", "DMA is not screenshot proof", raw, slot);
    }
}
void _start(void) { _exit(run()); }
#endif
