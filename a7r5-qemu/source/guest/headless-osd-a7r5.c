extern int strcmp(const char *, const char *);
#include "a7r5-lease-retry.h"
#include "headless-osd.h"
typedef unsigned long size_t;
extern void *memcpy(void *, const void *, size_t);
extern void *memset(void *, int, size_t);
extern int memcmp(const void *, const void *, size_t);
extern void *malloc(size_t);
extern void free(void *);
extern int open(const char *, int, ...), close(int), fsync(int);
extern int rename(const char *, const char *), unlink(const char *);
extern long write(int, const void *, size_t), pread(int, void *, size_t, long);
extern long read(int, void *, size_t);
extern int *__errno_location(void);
extern int snprintf(char *, size_t, const char *, ...);
extern void *mmap(void *, size_t, int, int, int, unsigned long);
extern int munmap(void *, size_t);
/* Linux O_NOFOLLOW differs between the firmware AArch64 ABI and the x86 host tests. */
#ifdef __aarch64__
#define HOSD_NOFOLLOW 0x8000
#else
#define HOSD_NOFOLLOW 0x20000
#endif
static unsigned int u16(const unsigned char *p) { return p[0] | (unsigned int)p[1] << 8; }
static unsigned int u32(const unsigned char *p) { return u16(p) | u16(p + 2) << 16; }
static void put32(unsigned char *p, unsigned int n) { for (int i = 0; i < 4; ++i) p[i] = n >> (8 * i); }
static void put64(unsigned char *p, unsigned long n) { for (int i = 0; i < 8; ++i) p[i] = n >> (8 * i); }
unsigned long hosd_hash(const unsigned char *p, unsigned long n) {
    unsigned long h = 14695981039346656037UL;
    while (n--) { h ^= *p++; h *= 1099511628211UL; }
    return h;
}
int hosd_persist(const char *path, const unsigned char *bytes, unsigned long length) {
    char temp[256];
    int n = snprintf(temp, sizeof temp, "%s.part", path);
    if (n < 0 || n >= (int)sizeof temp) return -1;
    /* O_CREAT|O_EXCL creates a new regular inode; never truncate/follow an existing path. */
    int fd = open(temp, HOSD_NOFOLLOW | 0xc2, 0600);
    if (fd < 0) return -1;
    int ok = 1;
    for (size_t offset = 0; offset < length;) {
        long nwrite = write(fd, bytes + offset, length - offset);
        if (nwrite < 0 && *__errno_location() == 4) continue; /* EINTR */
        if (nwrite <= 0 || (size_t)nwrite > length - offset) { ok = 0; break; }
        offset += nwrite;
    }
    if (ok) {
        int result;
        do { result = fsync(fd); } while (result && *__errno_location() == 4);
        ok = result == 0;
    }
    unsigned char verify[4096];
    for (unsigned long offset = 0; ok && offset < length;) {
        unsigned long count = length - offset;
        if (count > sizeof verify) count = sizeof verify;
        long nread = pread(fd, verify, count, offset);
        if (nread < 0 && *__errno_location() == 4) continue;
        ok = nread > 0 && (size_t)nread <= count && !memcmp(verify, bytes + offset, nread);
        if (ok) offset += nread;
    }
    if (close(fd)) ok = 0;
    if (ok && rename(temp, path) == 0) return 0;
    unlink(temp);
    return -1;
}
int hosd_claim(const char *path, const char *modules,
               int (*stat_queue)(unsigned int, unsigned int *), void (*log)(const char *, const char *)) {
    /* Persistent marker forbids automatic restart into queues without a protocol epoch. */
    int fd = open(path, HOSD_NOFOLLOW | 0xc1, 0600);
    if (fd < 0) { log("OSD_HEADLESS_FAILED ", "startup claim exists/unavailable; no queue consumed"); return -1; }
    if (close(fd)) return -1;
    if (!stat_queue) { log("OSD_HEADLESS_FAILED ", "osal_stat_msgq unavailable"); return -1; }
    fd = open(modules, 0);
    if (fd < 0) { log("OSD_HEADLESS_FAILED ", "cannot inspect loaded modules"); return -1; }
    char line[512]; size_t used = 0; int ok = 1;
    for (;;) {
        char c; long n = read(fd, &c, 1);
        if (n < 0 && *__errno_location() == 4) continue;
        if (n < 0) { ok = 0; break; }
        if (!n || c == '\n') {
            if (used >= 5 && !memcmp(line, "liro ", 5)) ok = 0;
            used = 0;
            if (!ok || !n) break;
        } else if (used == sizeof line) { ok = 0; break; }
        else line[used++] = c;
    }
    if (close(fd)) ok = 0;
    if (!ok) { log("OSD_HEADLESS_FAILED ", "LIRO present or modules inspection failed"); return -1; }
    const unsigned int queues[] = {HOSD_CONTROL, HOSD_UPDATE, HOSD_META_UPDATE};
    for (unsigned int i = 0; i < 3; ++i) {
        unsigned int state[4] = {0};
        int result = stat_queue(queues[i], state);
        char text[160];
        snprintf(text, sizeof text, "queue=%#x status=%d pending=%u clients=%u state2=%u state3=%u",
                 queues[i], result, state[0], state[1], state[2], state[3]);
        log("OSD_HEADLESS_STARTUP_QUEUE ", text);
        if (result || state[1] || state[2] || state[3]) return -1;
    }
    return 0;
}
static int peek(int fd, unsigned long address, void *data, size_t length) {
    if (address < 4096 || address >= 0x8000000000UL || length > 0x8000000000UL - address) return -1;
    return pread(fd, data, length, address) == (long)length ? 0 : -1;
}
static int identity(int fd, unsigned long base, struct hosd_frame *f, unsigned long *fb_out, unsigned long *bitmap_out) {
    unsigned long mgr, fb, on, off, bitmap;
    unsigned short geometry[2];
    if (peek(fd, base + 0x2d1588, &mgr, 8) || peek(fd, mgr + 8, &fb, 8) ||
        peek(fd, fb + 0x68, &on, 8) || peek(fd, fb + 0x70, &off, 8) ||
        !((on == fb + 0x20 && off == fb + 0x40) || (on == fb + 0x40 && off == fb + 0x20)) ||
        peek(fd, on, &bitmap, 8) || !bitmap || peek(fd, on + 0x10, &f->id, 4) ||
        peek(fd, on + 0x18, &f->physical, 8) || peek(fd, fb + 8, geometry, 4) ||
        peek(fd, fb + 12, &f->format, 4)) return -1;
    f->width = geometry[0]; f->height = geometry[1]; *fb_out = fb;
    if (bitmap_out) *bitmap_out = bitmap;
    return f->width == 640 && f->height == 480 && f->format == 1 &&
        f->physical >= 0x410000000UL && f->physical <= 0x500000000UL - HOSD_PIXELS ? 0 : -1;
}
int hosd_read_frame(unsigned long base, struct hosd_frame *f, unsigned char *pixels) {
    int mem = open("/proc/self/mem", 0);
    if (mem < 0) return -1;
    unsigned long fb = 0, fb_after = 0;
    struct hosd_frame after = {0};
    int ok = !identity(mem, base, f, &fb, 0);
    int physical = ok ? open("/dev/mem", 0) : -1;
    if (physical < 0) ok = 0;
    if (ok) {
        unsigned long start = f->physical & ~4095UL, offset = f->physical - start;
        size_t span = (offset + HOSD_PIXELS + 4095) & ~4095UL;
        void *mapped = mmap(0, span, 1, 1, physical, start);
        if (mapped == (void *)-1) ok = 0;
        else { memcpy(pixels, (unsigned char *)mapped + offset, HOSD_PIXELS); if (munmap(mapped, span)) ok = 0; }
        if (close(physical)) ok = 0;
        /* Identity diagnostics only: this does not establish a producer-obeyed read lease. */
        if (identity(mem, base, &after, &fb_after, 0) || fb != fb_after ||
            f->id != after.id || f->physical != after.physical || f->width != after.width ||
            f->height != after.height || f->format != after.format) ok = 0;
    }
    if (close(mem)) ok = 0;
    return ok ? 0 : -1;
}
static int a7r5_capture_attempt(unsigned long base, const struct hosd_native *api, struct hosd_frame *requested, unsigned char *pixels) {
    int fd = open("/proc/self/mem", 0);
    if (fd < 0) return -1;
    unsigned long mgr = 0, fb = 0, locked_fb = 0, bitmap = 0, vptr = 0;
    unsigned int sid = 0;
    int ok = !peek(fd, base + 0x2d1588, &mgr, 8) && !peek(fd, mgr + 8, &fb, 8) &&
             !peek(fd, fb + 0x98, &sid, 4) && sid;
    int semaphore = 0, reference = 0, reader = 0, raster = 0;
    const char *phase = "framebuffer";
    int status = -1;
    const void *bits = 0;
    struct hosd_frame current = {0};
    if (ok) { phase = "FB90-poll"; status = api->wait_sem(sid, 0); semaphore = status == 0; ok = semaphore; }
    if (ok) phase = "identity";
    if (ok) ok = !identity(fd, base, &current, &locked_fb, &bitmap) && locked_fb == fb &&
        current.id == requested->id && current.width == requested->width &&
        current.height == requested->height && current.format == requested->format &&
        !peek(fd, bitmap, &vptr, 8) && vptr == base + 0x2555a0;
    if (ok) { phase = "AddRef"; status = api->addref((void *)bitmap); reference = status == 0; ok = reference; }
    if (ok) { phase = "ReadLock-poll"; status = api->read_lock((void *)bitmap, 0, &bits); reader = status == 0; ok = reader && bits; }
    if (ok) { phase = "raster-trylock"; status = api->try_raster(); raster = status == 0; ok = raster; }
    unsigned long physical = 0, bytes = 0;
    short rows = 0;
    if (ok) phase = "geometry/mapping";
    if (ok) ok = !api->physical((void *)bitmap, &physical) && !api->row_pixels((void *)bitmap, &rows) &&
        !api->size((void *)bitmap, &bytes) && physical == current.physical && rows == 640 && bytes == HOSD_PIXELS;
    if (ok) {
        /* All supported CPU writers share raster; FB90 excludes same-phys bitmap replacement. */
        memcpy(pixels, bits, HOSD_PIXELS);
        *requested = current;
    }
    int retryable = !ok && status == 16 && !strcmp(phase, "raster-trylock");
    if (raster && api->unlock_raster()) { phase = "raster-unlock"; ok = 0; retryable = 0; }
    if (reader && api->read_unlock((void *)bitmap)) { phase = "ReadUnlock"; ok = 0; retryable = 0; }
    if (reference && api->release((void *)bitmap)) { phase = "Release"; ok = 0; retryable = 0; }
    if (semaphore && api->signal_sem(sid)) { phase = "FB90-signal"; ok = 0; retryable = 0; }
    if (close(fd)) { ok = 0; retryable = 0; }
    if (retryable) return -2;
    if (!ok && api->log) {
        char text[224];
        snprintf(text, sizeof text, "phase=%s last_lock_status=%d requested_id=%#x current_id=%#x bitmap=%#lx row=%d bytes=%lu phys=%#lx; no ACK",
                 phase, status, requested->id, current.id, bitmap, rows, bytes, physical);
        api->log("OSD_HEADLESS_LEASE_FAILED ", text);
    }
    return ok ? 0 : -1;
}
static int stopping(const struct hosd_ops *o) {
    return o->stop && __atomic_load_n(o->stop, __ATOMIC_ACQUIRE);
}
static int consume(struct hosd_state *s, const struct hosd_ops *o, const char *path) {
    s->phase = "validate-frame";
    const unsigned char *d = s->pending == 0x1005 ? s->retained_descriptor : s->descriptor;
    if (s->pending == 0x1005 && !s->pixel_source_seq) return -1;
    if (!s->have_descriptor || u16(d + 0x10) != 0 || u16(d + 0x14) != 640 || u16(d + 0x16) != 480 ||
        u16(d + 0x18) > 640 || u16(d + 0x1a) > 480 ||
        u16(d + 0x1c) > 640 - u16(d + 0x18) || u16(d + 0x1e) > 480 - u16(d + 0x1a)) return -1;
    unsigned char *snapshot = malloc(HOSD_BYTES);
    if (!snapshot) return -1;
    memset(snapshot, 0, HOSD_HEADER);
    struct hosd_frame f = s->retained_frame;
    unsigned char *pixels = snapshot + HOSD_HEADER + sizeof s->frozen;
    int ok = 1;
    if (s->pending == 0x1005) memcpy(pixels, s->retained_pixels, HOSD_PIXELS);
    else {
        f = (struct hosd_frame){u32(d + 8), 640, 480, 1, 0};
        s->phase = "capture"; ok = !stopping(o) && !o->frame(&f, pixels);
    }
    ok = ok &&
        f.id == u32(d + 8) && f.width == 640 && f.height == 480 && f.format == 1 &&
        f.physical >= 0x410000000UL && f.physical <= 0x500000000UL - HOSD_PIXELS;
    if (ok) {
        memcpy(snapshot, "HOSDAP02", 8);
        put64(snapshot + 8, s->sequence + 1); put32(snapshot + 16, f.id);
        put32(snapshot + 20, f.width); put32(snapshot + 24, f.height); put32(snapshot + 28, f.format);
        put64(snapshot + 32, f.physical);
        put32(snapshot + 48, HOSD_PIXELS); put32(snapshot + 52, sizeof s->frozen);
        put32(snapshot + 56, s->pending);
        memcpy(snapshot + 64, d, 36); memcpy(snapshot + 100, s->fix, 12); memcpy(snapshot + 112, s->update, 8);
        unsigned long pixel_source_seq = s->pending == 0x1003 ? s->sequence + 1 : s->pixel_source_seq;
        put64(snapshot + 120, pixel_source_seq);
        memcpy(snapshot + HOSD_HEADER, &s->frozen, sizeof s->frozen);
        /* Hash includes identity, sequence and raw metadata/pixels; checksum field is zero. */
        unsigned long hash = hosd_hash(snapshot, HOSD_BYTES);
        put64(snapshot + 40, hash);
        s->phase = "commit";
        ok = hosd_persist(path, snapshot, HOSD_BYTES) == 0;
        if (ok) {
            ++s->sequence;
            if (s->pending == 0x1003) {
                memcpy(s->retained_pixels, pixels, HOSD_PIXELS);
                memcpy(s->retained_descriptor, d, 36);
                s->retained_frame = f;
                s->pixel_source_seq = pixel_source_seq;
            }
            char text[256];
            snprintf(text, sizeof text, "seq=%lu pixel_source_seq=%lu id=%#x phys=%#lx geometry=640x480 bytes=%u fnv1a64=%016lx mode=AP-RGBA4444-experimental path=%s",
                     s->sequence, s->pixel_source_seq, f.id, f.physical, HOSD_PIXELS, hash, path);
            if (s->sequence <= 8 || !(s->sequence & (s->sequence - 1))) o->log("OSD_HEADLESS_PERSISTED ", text);
        }
    }
    free(snapshot);
    return ok ? 0 : -1;
}
int hosd_step(struct hosd_state *s, const struct hosd_ops *o, const char *path) {
    if (s->failed) return -1;
    if (stopping(o)) { o->log("OSD_HEADLESS_STOPPED ", "shutdown requested; no further receive"); return -1; }
    s->phase = "receive";
    unsigned int queue = !s->pending ? HOSD_CONTROL : s->pending == 0x1003 ? HOSD_UPDATE : HOSD_META_UPDATE;
    void *message = 0;
    int result = o->receive(queue, &message, s->pending ? HOSD_PAIR_MS : HOSD_IDLE_MS);
    if (stopping(o)) {
        if (!result && message) o->release(queue, message);
        o->log("OSD_HEADLESS_STOPPED ", "shutdown after receive; no capture/ACK"); return -1;
    }
    if (result == HOSD_TIMEOUT && !message && !s->pending) return 0;
    if (result || !message) {
        char text[192];
        snprintf(text, sizeof text, "receive status=%d queue=%#x expected=%#x seq=%lu pixel_source_seq=%lu; stopped, no ACK",
                 result, queue, s->pending, s->sequence, s->pixel_source_seq);
        s->failed = 1; o->log("OSD_HEADLESS_FAILED ", text); return -1;
    }
    const unsigned char *p = message;
    unsigned int size = o->size(message), source = o->source(message), cmd = size >= 2 ? u16(p) : 0;
    int ok = 0, complete = 0;
    s->phase = "bare-body-whitelist";
    /* Exact bare-body whitelist only. Dataflow envelopes/multi-body are unsupported. */
    if (size >= 8 && u32(p + 4) == 0xa0a0a0a0U) {
        o->log("OSD_HEADLESS_REJECTED ", "Dataflow envelope unsupported; expected one exact bare body");
    } else if (!s->pending && source == HOSD_GUI) {
        if (cmd == 0x1000 && size == 80 && u32(p + 12) <= 16) {
            memcpy(s->working.gui, p, 80); s->working.present[256] = 1; ok = 1;
        } else if (cmd == 0x1001 && size == 96 && u16(p + 8) < 256 && u32(p + 28) <= 16) {
            unsigned int index = u16(p + 8);
            memcpy(s->working.widgets[index], p, 96); s->working.present[index] = 1; ok = 1;
        } else if (cmd == 0x1004 && size == 16) {
            memcpy(s->working.extra, p, 16); s->working.present[257] = 1; ok = 1;
        }
    } else if (!s->pending && source == HOSD_AP && cmd == 0x1002 && size == 12 &&
               (u32(p + 8) == 0x1003 || u32(p + 8) == 0x1005)) {
        memcpy(s->fix, p, 12); s->frozen = s->working; s->pending = u32(p + 8); ok = 1;
    } else if (s->pending && source == HOSD_AP && cmd == s->pending) {
        if (cmd == 0x1003 && size == 36) {
            memcpy(s->descriptor, p, 36); s->have_descriptor = 1; memset(s->update, 0, 8); complete = 1;
        } else if (cmd == 0x1005 && size == 8 && s->pixel_source_seq) {
            memcpy(s->update, p, 8); complete = 1;
        }
        if (complete) ok = consume(s, o, path) == 0;
    }
    if (o->release(queue, message)) { ok = 0; s->phase = "release-request"; }
    if (ok && complete && stopping(o)) { s->phase = "shutdown-before-ack"; ok = 0; }
    if (ok && complete) {
        void *reply = 0;
        s->phase = "allocate-ack";
        result = o->allocate(HOSD_AP, &reply, 8, 1);
        if (result || !reply) ok = 0;
        else {
            memset(reply, 0, 8); ((unsigned char *)reply)[0] = s->pending & 255; ((unsigned char *)reply)[1] = 0x60;
            o->set_source(reply, HOSD_CONTROL);
            s->phase = "send-ack";
            result = o->send(HOSD_AP, reply);
            if (result) { o->release(HOSD_AP, reply); ok = 0; }
            else {
                s->pending = 0;
                if (s->sequence <= 8 || !(s->sequence & (s->sequence - 1))) {
                    char text[144];
                    snprintf(text, sizeof text, "seq=%lu persisted AP snapshot consumed; CP composition/panel unimplemented", s->sequence);
                    o->log("OSD_HEADLESS_ACK ", text);
                }
            }
        }
    }
    if (!ok) {
        char text[256];
        snprintf(text, sizeof text, "phase=%s queue=%#x source=%#x cmd=%#x bytes=%u pending=%#x seq=%lu pixel_source_seq=%lu errno=%d envelopes=unsupported; stopped, no ACK",
                 s->phase, queue, source, cmd, size, s->pending, s->sequence, s->pixel_source_seq, *__errno_location());
        s->failed = 1; o->log("OSD_HEADLESS_FAILED ", text); return -1;
    }
    return 0;
}
void *hosd_worker(void *argument) {
    const struct hosd_ops *ops = argument;
    struct hosd_state *state = malloc(sizeof *state);
    if (!state) { ops->log("OSD_HEADLESS_FAILED ", "state allocation failed; no ACK"); return 0; }
    memset(state, 0, sizeof *state);
    ops->log("OSD_HEADLESS_STARTED ", "serial 74d->84d/84e; AP software consumer; no CP hardware");
    while (!hosd_step(state, ops, HOSD_PATH)) {}
    free(state);
    return 0;
}

extern int usleep(unsigned int);
struct a7r5_capture_context { unsigned long base; const struct hosd_native *api; struct hosd_frame *frame; unsigned char *pixels; };
static int a7r5_capture_once(void *context) {
    struct a7r5_capture_context *c=context;
    return a7r5_capture_attempt(c->base,c->api,c->frame,c->pixels);
}
int hosd_capture_frame(unsigned long base,const struct hosd_native *api,struct hosd_frame *frame,unsigned char *pixels) {
    struct a7r5_capture_context context={base,api,frame,pixels}; unsigned int tries;
    int result=a7r5_retry_capture(a7r5_capture_once,&context,usleep,&tries);
    if (tries>1 && api->log) { char text[128]; snprintf(text,sizeof text,"attempts=%u result=%d; every busy attempt released all leases",tries,result); api->log("A7R5_FRAME_LEASE_RETRY ",text); }
    return result;
}
