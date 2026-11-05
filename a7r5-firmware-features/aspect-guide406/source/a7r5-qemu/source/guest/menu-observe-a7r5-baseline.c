#include "a7r5-services.h"
/* Test-only tracing, scheduling, and opt-in CP storage/address services. */
#include "capid-service.h"
#include "hdmi-format-service.h"
#include "dmm-service.h"
#include "headless-osd.h"
typedef unsigned long size_t;
typedef unsigned long pthread_t;
extern void *dlvsym(void *, const char *, const char *);
extern int open(const char *, int, ...);
extern long write(int, const void *, size_t);
extern long read(int, void *, size_t);
extern long syscall(long, ...);
extern int close(int);
extern char *getenv(const char *);
extern char *strstr(const char *, const char *);
extern int snprintf(char *, size_t, const char *, ...);
extern int sscanf(const char *, const char *, ...);
extern void *mmap(void *, size_t, int, int, int, unsigned long);
extern int munmap(void *, size_t);
extern int mprotect(void *, size_t, int);
static unsigned char *memory_log;
static void *(*real_dlsym)(void *, const char *);
static void *(*real_dlopen)(const char *, int);
static int (*real_attr_policy)(void *, int);
static int (*real_attr_param)(void *, const void *);
static int (*real_thread_param)(pthread_t, int, const void *);
static int (*real_scheduler)(int, int, const void *);
static void *(*real_application_init)(void *);
static void *(*real_uxengine_init2)(void *);
static unsigned long appfw_base;
/* MENU_BB_READY_LATE=1 defers the single 0x2003/0x8201 fulfilment away from the plane-table
   completion (see screen-blocker/REPORT.md E2): on real hardware CP sends it after the output
   pipeline has started, i.e. after the cold-boot chain, not in the middle of it. The event is
   then delivered on the first app-side send that follows an injected key. */
static int bb_ready_pending;
static int bb_key_seen;
static int (*real_updater_init)(void);
static int (*real_updater_exit)(void);
static int (*real_dynamic_id)(unsigned int, unsigned int, unsigned long);
static int (*real_reg_sync)(unsigned int, void **, void *, unsigned long);
static int (*real_reg_async)(unsigned int, void **, void *, unsigned long);
static int (*real_send_msg)(unsigned int, void *);
static int (*real_send_sync)(unsigned int, void *);
static int (*real_send_sync_direct)(unsigned int, void *);
static int (*real_allocate_msg)(unsigned int, void **, unsigned int, unsigned int);
static int (*real_free_msg)(unsigned int, void *);
/* Lens-version virtual service: 0x912503d0 has no kernel queue in QEMU, so requests
   valloc'd by libInfraGetVersion.so+0xe08 borrow the always-present ulog queue pool
   (0x8f013a) and are remembered here so the matching free returns them to that pool. */
#define LENS_POOL_SLOTS 8
static struct { void *message; unsigned int borrowed_from; int live; } lens_pool[LENS_POOL_SLOTS];
static unsigned long lens_pool_lock[6];
static unsigned int backup_service_count;
static int backup_service_enabled;
static unsigned int sensor_service_count;
static unsigned int (*real_get_source)(void *);
static void (*real_set_source)(void *, unsigned int);
static unsigned int (*real_msg_size)(void *);
static int (*real_rcv_msg_tmo)(unsigned int, void **, long);
typedef struct { const char *dli_fname; void *dli_fbase; const char *dli_sname; void *dli_saddr; } Dl_info;
static int (*real_dladdr)(void *, Dl_info *);
extern int pthread_mutex_lock(void *);
extern int pthread_mutex_unlock(void *);
extern int pthread_mutex_trylock(void *);
static unsigned long cap_lock[6]; /* AArch64 glibc 2.25 pthread_mutex_t is 48 bytes */
static struct cap_service capid;
static int capid_enabled;
static int sa_address_enabled;
static int hdmi_format_enabled;
static struct hdmi_format_state hdmi_format;
static int hdmi_photo_enabled;
static struct hdmi_photo_state hdmi_photo;
static int display_info_enabled;
static int subscription_enabled;
static unsigned long captured_menu_controller;
/* The thread that runs the application's UI (learned from create_screen). Activating a mode controller
   from an arbitrary worker thread aborted the guest, so the message-loop path only fires on this tid. */
static unsigned int ui_thread_id;
static unsigned int create_screen_active, create_screen_returned;
static int sequence_event_enabled;
/* Our own 'BB output ready' fulfilment: on real hardware the CP sends it. Fulfilling a promise the
   application has already completed throws future_error(2) and aborts IWrapperBBSub, so this is now
   opt-in only (MENU_BB_READY_INJECT=1) instead of firing on every plane-config request. */
static int bb_ready_inject_enabled;
/* Panel/EVF geometry reported to the model. The retail UI resources are authored for a
   720x480 LCD and a 1024x768 EVF (master_normal.uxc contains 768 fifty times and 480 not at
   all), so 640x480 is a placeholder that may not match any layout. Override with
   QEMU_DISPLAY_SIZE="<panel_w>x<panel_h>,<evf_w>x<evf_h>" and QEMU_DISPLAY_ASPECT="p,e". */
static struct display_info virtual_display = {640, 480, 640, 480, 1, 1};
static int dmm_enabled;
static struct dmm_service dmm;
int sa_address_reply(const unsigned char *, unsigned char *);
static int (*real_kikilog_notify)(unsigned int);
static int (*real_gpe_fill)(int, int, unsigned int *, const void *);
/* MonLib monitor-console guard: MonDrv::Init fails in QEMU (/dev/mem absent at
   devtmpfs and unusable via mknod without the kernel mem driver), leaving the
   console queue pointers NULL; any later MonDrv output then SEGVs inside
   libMWF+0x409d0 (run-y3ruwbci/yol1gsix/podfartv/2jqg0nsj/4vxgchsa). libMWF
   calls its own exports through the PLT, so redirecting the queue probes to
   "queue full" reproduces the real camera's drop-output behavior safely. */
#if 0 /* dq0o3yjm reconstruction: post-good-build additions disabled */
static int (*real_monqueue_isfull)(void *);
static int (*real_monqueue_nearlyfull)(void *);
static int (*real_monqueue_isempty)(void *);
static unsigned long (*real_monqueue_remain)(void *);
static int (*real_monqueue_enqueue)(void *, unsigned char);
static unsigned long (*real_monqueue_dequeue)(void *);
int _ZN8MonQueue6IsFullEv(void *queue) {
    if (!queue) return 1;  /* full: MonDrv::SetInputChar/Putchar drop and return -1 */
    return real_monqueue_isfull ? real_monqueue_isfull(queue) : 0;
}
int _ZN8MonQueue12IsNearlyFullEv(void *queue) {
    if (!queue) return 1;  /* full: MonDrv::PutcharSub drops the character */
    return real_monqueue_nearlyfull ? real_monqueue_nearlyfull(queue) : 0;
}
int _ZN8MonQueue7IsEmptyEv(void *queue) {
    if (!queue) return 1;  /* empty: output drain loops sleep instead of deref */
    return real_monqueue_isempty ? real_monqueue_isempty(queue) : 1;
}
unsigned long _ZN8MonQueue14GetQueueRemainEv(void *queue) {
    if (!queue) return 0x40;  /* default ring capacity headroom */
    return real_monqueue_remain ? real_monqueue_remain(queue) : 0x40;
}
int _ZN8MonQueue7EnQueueEh(void *queue, unsigned char value) {
    if (!queue) return -1;  /* drop */
    return real_monqueue_enqueue ? real_monqueue_enqueue(queue, value) : -1;
}
unsigned long _ZN8MonQueue7DeQueueEv(void *queue) {
    if (!queue) return 0xffffffff;  /* empty marker */
    return real_monqueue_dequeue ? real_monqueue_dequeue(queue) : 0xffffffff;
}
#endif /* dq0o3yjm reconstruction */
static int (*real_gpe_blit)(int, int, unsigned int *, const void *);
static unsigned int gpe_capture_count;
static int software_gpe;
static int software_rgba4444;
static int raster_fd = -1;
static int (*real_draw_initialize)(int);
int software_draw_initialize(int) __asm__("_ZN5mpgpe14InitializeDrawENS_3GpeE");
static int (*real_gperm_initialize)(const void *);
int software_gperm_initialize(const void *) __asm__("_ZNK5mpgpe5Gperm4InitEv");
static int (*real_worker_fill)(int, int, unsigned int, unsigned int, const void *);
static int (*real_worker_blit)(int, int, unsigned int, unsigned int, const void *);
static int (*real_worker_flush)(int, int, unsigned int, unsigned int, const void *);
static int raster_failed;
static unsigned long headless_raster_mutex[6], headless_lifecycle_mutex[6];
#include "gpe-copy.h"
#include "gpe-sprite.h"
#include "sony-lz77.h"
int software_flush_worker(int, int, unsigned int, unsigned int, const void *)
    __asm__("_ZN5mpgpe5FlushENS_3GpeENS_7IntCoreEjjRKNS_10FlushParamE");
static int (*real_draw_complete)(unsigned int, const void *, size_t);
int gpe_uniform_fill(unsigned char *, size_t, const unsigned int *);
int software_fill_worker(int, int, unsigned int, unsigned int, const void *)
    __asm__("_ZN5mpgpe8FillRectENS_3GpeENS_7IntCoreEjjRKNS_13FillRectParamE");
int software_blit_worker(int, int, unsigned int, unsigned int, const void *)
    __asm__("_ZN5mpgpe7BitBlitENS_3GpeENS_7IntCoreEjjRKNS_12BitBlitParamE");
static int same_name(const char *, const char *);
static void record(const char *, const char *);
static void install_osd_observers(void *);
static void install_frame_observers(unsigned long);
static unsigned long (*real_notify_draw)(void *), (*real_draw_framebuffer)(void *);
static int headless_osd_enabled;
static void start_headless_osd(void);
int observe_gpe_fill(int, int, unsigned int *, const void *)
    __asm__("_ZN5mpgpe13GpermFillRectENS_3GpeENS_7IntCoreEPjRKNS_13FillRectParamE");
int observe_gpe_blit(int, int, unsigned int *, const void *)
    __asm__("_ZN5mpgpe12GpermBitBlitENS_3GpeENS_7IntCoreEPjRKNS_12BitBlitParamE");

/* Resolve on the initial thread, before dlopen constructors create IPC threads.
 * Repeated dlsym from those threads could block on the constructor's loader lock.
 */
#ifndef MENU_OBSERVE_TRANSPORT_SELFTEST
__attribute__((constructor))
#endif
static void initialize(void) {
    real_dlsym = dlvsym((void *)-1, "dlsym", "GLIBC_2.17");
    real_dlopen = real_dlsym((void *)-1, "dlopen");
    real_attr_policy = real_dlsym((void *)-1, "pthread_attr_setschedpolicy");
    real_attr_param = real_dlsym((void *)-1, "pthread_attr_setschedparam");
    real_thread_param = real_dlsym((void *)-1, "pthread_setschedparam");
    real_scheduler = real_dlsym((void *)-1, "sched_setscheduler");
    real_dynamic_id = real_dlsym((void *)-1, "osal_dynamic_id");
    real_reg_sync = real_dlsym((void *)-1, "osal_reg_sync_msg_queue_cb");
    real_reg_async = real_dlsym((void *)-1, "osal_reg_msg_queue_cb");
    real_send_msg = real_dlsym((void *)-1, "osal_snd_msg");
    real_send_sync = real_dlsym((void *)-1, "osal_snd_sync_msg");
    real_send_sync_direct = real_dlsym((void *)-1, "osal_snd_sync_direct");
    real_allocate_msg = real_dlsym((void *)-1, "osal_valloc_msg_wait");
    real_free_msg = real_dlsym((void *)-1, "osal_free_msg");
    real_get_source = real_dlsym((void *)-1, "osal_get_msg_src");
    real_set_source = real_dlsym((void *)-1, "osal_set_msg_src");
    real_msg_size = real_dlsym((void *)-1, "osal_msg_size");
    real_rcv_msg_tmo = real_dlsym((void *)-1, "osal_rcv_msg_tmo");
    real_dladdr = real_dlsym((void *)-1, "dladdr");
    capid_enabled = getenv("QEMU_CAPID_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    (void)0;
    sa_address_enabled = getenv("QEMU_SA_ADDRESS_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    hdmi_format_enabled = getenv("QEMU_HDMI_FORMAT_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    hdmi_photo_enabled = getenv("QEMU_HDMI_PHOTO_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    display_info_enabled = getenv("QEMU_DISPLAY_INFO_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    subscription_enabled = getenv("QEMU_SUBSCRIPTION_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    sequence_event_enabled = getenv("MENU_SEQ_EVENT") && !getenv("MENU_OBSERVE_SELFTEST");
    bb_ready_inject_enabled = getenv("MENU_BB_READY_INJECT") && !getenv("MENU_OBSERVE_SELFTEST");
    if (display_info_enabled && !getenv("MENU_OBSERVE_SELFTEST")) {
        const char *size = getenv("QEMU_DISPLAY_SIZE");
        const char *aspect = getenv("QEMU_DISPLAY_ASPECT");
        unsigned int panel_width = 0, panel_height = 0, evf_width = 0, evf_height = 0, panel_aspect = 0, evf_aspect = 0;
        if (size && sscanf(size, "%ux%u,%ux%u", &panel_width, &panel_height, &evf_width, &evf_height) == 4 &&
            panel_width && panel_height && evf_width && evf_height && panel_width < 8192 && evf_width < 8192) {
            virtual_display.panel_width = panel_width;
            virtual_display.panel_height = panel_height;
            virtual_display.evf_width = evf_width;
            virtual_display.evf_height = evf_height;
        }
        if (aspect && sscanf(aspect, "%u,%u", &panel_aspect, &evf_aspect) == 2 &&
            panel_aspect <= 3 && evf_aspect <= 3) {
            virtual_display.panel_aspect = panel_aspect;
            virtual_display.evf_aspect = evf_aspect;
        }
        char text[120];
        snprintf(text, sizeof text, "reported panel=%ux%u aspect=%u evf=%ux%u aspect=%u",
                 virtual_display.panel_width, virtual_display.panel_height, virtual_display.panel_aspect,
                 virtual_display.evf_width, virtual_display.evf_height, virtual_display.evf_aspect);
        record("DISPLAY_INFO_GEOMETRY ", text);
    }
    dmm_enabled = getenv("QEMU_DMM_SERVICE") && !getenv("MENU_OBSERVE_SELFTEST");
    software_gpe = getenv("QEMU_SOFTWARE_GPE") && !getenv("MENU_OBSERVE_SELFTEST");
    software_rgba4444 = software_gpe && getenv("QEMU_GPE_RGBA4444");
    headless_osd_enabled = getenv("MENU_HEADLESS_OSD") &&
        same_name(getenv("MENU_HEADLESS_OSD"), "1") && !getenv("MENU_OBSERVE_SELFTEST");
    if (0) { /* A7R5 基线不写入未经验证的物理日志地址。 */
        int fd = open("/dev/mem", 2);
        if (fd >= 0) {
            void *area = mmap(0, 65536, 3, 1, fd, 0x4102d0000UL);
            if (area != (void *)-1) memory_log = area;
            if (capid_enabled) {
                capid.address = 0x4102e0000ULL; /* dedicated test reservation, not a real CP address */
                area = mmap(0, 0x5000, 3, 1, fd, (unsigned long)capid.address);
                if (area != (void *)-1) {
                    capid.table = area;
                    unsigned char *bytes = area;
                    for (size_t i = 0; i < sizeof *capid.table; ++i) bytes[i] = 0;
                }
            }
            close(fd);
        }
    }

    if (capid_enabled) {
        char arguments[4097] = {0};
        int fd = open("/proc/cmdline", 0);
        if (fd >= 0) { long count = read(fd, arguments, 4096); if (count > 0) arguments[count] = 0; close(fd); }
        fd = strstr(arguments, "memrsv=0x00010000@0x41d000000:uc") ? open("/dev/mem", 2) : -1;
        if (fd >= 0) {
            capid.address = 0x41d000000ULL;
            void *area = mmap(0, 0x5000, 3, 1, fd, (unsigned long)capid.address);
            if (area != (void *)-1) {
                capid.table = area;
                unsigned char *bytes = area;
                for (size_t i = 0; i < sizeof *capid.table; ++i) bytes[i] = 0;
            }
            close(fd);
        }
        record("A7R5_CAPID_POOL ", capid.table ? "reserved 0x41d000000+0x10000" : "unavailable");
    }

    if (dmm_enabled) {
        char arguments[4097] = {0};
        int fd = open("/proc/cmdline", 0);
        if (fd >= 0) { long count = read(fd, arguments, 4096); if (count > 0) arguments[count] = 0; close(fd); }
        fd = strstr(arguments, "memrsv=0x00100000@0x41e000000:uc") ? open("/dev/mem", 2) : -1;
        if (fd >= 0) {
            void *area = mmap(0, DMM_TEST_SIZE, 3, 1, fd, DMM_TEST_PHYSICAL);
            if (area != (void *)-1) { dmm.memory = area; dmm.physical = DMM_TEST_PHYSICAL; }
            close(fd);
        }
        record("DMM_SERVICE_INIT ", dmm.memory ? "pool=0x41e000000 CP=0x1e000000 slots=2 size=0x80000" : "pool unavailable");
    }
    int command = open("/proc/self/cmdline", 0);
    if (command >= 0) {
        char text[257];
        long length = read(command, text, 256);
        close(command);
        if (length > 0) {
            for (long i = 0; i < length; ++i) if (!text[i]) text[i] = ' ';
            text[length] = 0;
            record("PROGRAM_ARGS ", text);
        }
    }
}
static void record(const char *prefix, const char *name) {
    /* Mirror a few high-value prefixes to stderr so they survive a guest abort: the console capture
       keeps them even when diag.sh never runs. */
    if (prefix) {
        static const char *mirrored[] = { "MENU_CONTROLLER_SEEN ", "MENU_CTOR_PROBE", "BUILD2_", "MENU_INIT_SKIPPED ", "MODE_SENTINELS", "MODE_SLOT4 ", "POINTER_SCAN ", "MODE_ACTIVATE", "FORCE_OPEN_", "FORCE_OPEN_FIELDS ", "FORCE_OPEN_SKIPPED ", "OBSERVER_READY ", "FORCE_SET_ENTER ", "MENU_BUILD_", "MENU_OPEN_", "MENU_INIT_", "MENU_APPLY_", "MANAGER_", "FORCE_SET_BEGIN ", "FORCE_SET ", "CREATE_SCREEN_", "VIEW_SLOT_CALLED ", "FACTORY_CALL ", "CTOR_", "BLIT", "OPEN_SET", "SCREEN_REGISTRY", "OSD_", "FRAME_", "VIEW_CONTENT", "RESOURCE_", "GPE_RGBA_", "A7R5_", "BB_CONFIG_", "PLANE_CONFIG_", "BEGIN ", "LOADED ", "FAILED " };
        for (unsigned int i = 0; i < sizeof mirrored / sizeof mirrored[0]; ++i) {
            const char *want = mirrored[i];
            unsigned int k = 0;
            while (want[k] && prefix[k] == want[k]) ++k;
            if (!want[k]) {
                char line[512];
                int n = snprintf(line, sizeof line, "OBS %s%s\n", prefix, name ? name : "");
                if (n > 0) {
                    /* stderr is redirected into /tmp/im.log by the launcher, so mirror into the kernel
                       log instead: /dev/kmsg lines land in the console capture even if the guest aborts. */
                    static int kmsg = -2;
                    /* /dev/kmsg drops messages under printk_ratelimit; /dev/console does not. */
                    if (kmsg == -2) kmsg = open("/dev/console", 1);
                    if (kmsg >= 0) { long ignored = write(kmsg, line, (unsigned long)n); (void)ignored; }
                    else { long ignored = write(2, line, (unsigned long)n); (void)ignored; }
                }
                break;
            }
        }
    }
#ifdef MENU_OBSERVE_TRANSPORT_SELFTEST
    return;
#endif
    if (!name) return;
    size_t length = 0, plen = 0;
    while (name[length] && length < 1024) ++length;
    while (prefix[plen]) ++plen;
    if (memory_log) {
        unsigned int count = (unsigned int)(plen + length + 1);
        unsigned int offset = __atomic_fetch_add((unsigned int *)memory_log, count,
                                                 __ATOMIC_RELAXED) + 8;
        if (offset + count < 65536) {
            for (size_t i = 0; i < plen; ++i) memory_log[offset + i] = prefix[i];
            for (size_t i = 0; i < length; ++i) memory_log[offset + plen + i] = name[i];
            memory_log[offset + count - 1] = '\n';
        }
    }
    int fd = open("/tmp/menu-load.log", 0x441, 0644);
    if (fd >= 0) {
        write(fd, prefix, plen); write(fd, name, length);
        write(fd, "\n", 1); close(fd);
    }
}
void *dlopen(const char *name, int flags) {
    if (!real_dlopen) initialize();
    record("BEGIN ", name);
    if (flags & 8) { /* RTLD_DEEPBIND hides a library's osal IPC calls from these hooks; strip it. */
        char text[100];
        snprintf(text, sizeof text, "stripped DEEPBIND for %s (requested=%#x)", name, flags);
        record("LOADER_DEEPBIND ", text);
        flags &= ~8;
    }
    if (same_name(name, "libgpe.so") || same_name(name, "/usr/lib/libgpe.so")) {
        char text[100];
        snprintf(text, sizeof text, "requested=%#x effective=%#x software=%d", flags, flags, software_gpe);
        record("GPE_LOADER_FLAGS ", text);
    }
    void *handle = real_dlopen(name, flags);
    record(handle ? "LOADED " : "FAILED ", name);
    if (handle && (getenv("MENU_FRAME_OBSERVE") || headless_osd_enabled) &&
        (same_name(name, "libObj.so") || same_name(name, "/usr/lib/libObj.so"))) {
        real_notify_draw = real_dlsym(handle, "_ZN2ux6wgtsys12WidgetSystem10notifyDrawEv");
        real_draw_framebuffer = real_dlsym(handle, "_ZN2ux6gfxeng14GraphicsEngine15drawFramebufferEv");
        start_headless_osd();
    }
    if (handle && getenv("MENU_OSD_OBSERVE") &&
        (same_name(name, "libObj.so") || same_name(name, "/usr/lib/libObj.so")))
        install_osd_observers(handle);
    if (handle && (same_name(name, "libInfraKikiLogGenerator.so") ||
                   same_name(name, "/usr/lib/libInfraKikiLogGenerator.so"))) {
        void *notify = real_dlsym(handle, "kikilog_set_notify_cb");
        if (notify) real_kikilog_notify = notify;
    }
    if (handle && (same_name(name, "libgpe.so") || same_name(name, "/usr/lib/libgpe.so"))) {
        real_gpe_fill = real_dlsym(handle, "_ZN5mpgpe13GpermFillRectENS_3GpeENS_7IntCoreEPjRKNS_13FillRectParamE");
        real_gpe_blit = real_dlsym(handle, "_ZN5mpgpe12GpermBitBlitENS_3GpeENS_7IntCoreEPjRKNS_12BitBlitParamE");
        real_worker_fill = real_dlsym(handle, "_ZN5mpgpe8FillRectENS_3GpeENS_7IntCoreEjjRKNS_13FillRectParamE");
        real_worker_blit = real_dlsym(handle, "_ZN5mpgpe7BitBlitENS_3GpeENS_7IntCoreEjjRKNS_12BitBlitParamE");
        real_worker_flush = real_dlsym(handle, "_ZN5mpgpe5FlushENS_3GpeENS_7IntCoreEjjRKNS_10FlushParamE");
        real_draw_complete = real_dlsym(handle, "_ZN5mpgpe7message12SendDrawCompEjPKvm");
        real_draw_initialize = real_dlsym(handle, "_ZN5mpgpe14InitializeDrawENS_3GpeE");
        real_gperm_initialize = real_dlsym(handle, "_ZNK5mpgpe5Gperm4InitEv");
        if (software_gpe && real_gpe_fill) {
            unsigned long base = (unsigned long)real_gpe_fill - 0xa758;
            char text[180];
            snprintf(text, sizeof text, "init=%#lx fill=%#lx blit=%#lx",
                     *(unsigned long *)(base + 0x29670), *(unsigned long *)(base + 0x29680), *(unsigned long *)(base + 0x29160));
            record("GPE_WORKER_BIND_BEFORE ", text);
            if (mprotect((void *)(base + 0x29000), 4096, 3) == 0) {
                *(unsigned long *)(base + 0x29670) = (unsigned long)software_draw_initialize;
                *(unsigned long *)(base + 0x29680) = (unsigned long)software_fill_worker;
                *(unsigned long *)(base + 0x29160) = (unsigned long)software_blit_worker;
                *(unsigned long *)(base + 0x29540) = (unsigned long)software_gperm_initialize;
                *(unsigned long *)(base + 0x29110) = (unsigned long)software_flush_worker;
                record("GPE_WORKER_BIND ", "five verified PLT slots mapped to actual CPU raster backend; files unchanged");
            } else record("GPE_WORKER_BIND_FAILED ", "GOT page cannot be made writable");
        }
    }
    return handle;
}
/* appFw reaches uxengine_init2 through its own lazy PLT stub at appFw+0x165fe30
   (R_AARCH64_JUMP_SLOT at appFw+0x5bc2720, verified in the original file). The stub
   is rewritten to an indirect jump through this wrapper so entry and return are
   directly observable. The library file is not modified; the loaded text page is
   patched in place after the expected stub bytes are verified. */
static void *observe_uxengine_init2(void *argument) {
    record("ENTER ", "uxengine_init2");
    void *result = real_uxengine_init2(argument);
    record("RETURN ", "uxengine_init2");
    return result;
}
/* No libgcc __clear_cache/outline-atomics helpers in this guest root, so the
   instruction cache is maintained with the architectural maintenance ops. */
static void clear_cache_range(void *start, size_t length) {
    unsigned long ctr;
    unsigned long step;
    unsigned long address = (unsigned long)start & ~63UL;
    unsigned long end = (unsigned long)start + length;
    __asm__ __volatile__("mrs %0, ctr_el0" : "=r"(ctr));
    step = 4UL << ((ctr >> 16) & 0xf);
    if (!step) step = 64;
    __asm__ __volatile__("dsb ish" ::: "memory");
    for (; address < end; address += step)
        __asm__ __volatile__("ic ivau, %0" :: "r"(address) : "memory");
    __asm__ __volatile__("dsb ish; isb" ::: "memory");
}
static unsigned int patch_uxengine_init2(unsigned long base) {
    unsigned char *stub = (unsigned char *)(base + 0x165fe30UL);
    unsigned long page = (unsigned long)stub & ~0xfffUL;
    unsigned int expected[2] = {0xf0022b10u, 0xf9439211u}; /* adrp x16,#0x5bc2000 ; ldr x17,[x16,#0x720] */
    unsigned int jump[2] = {0x58000051u, 0xd61f0220u};   /* ldr x17, #8 ; br x17 */
    unsigned long target = (unsigned long)observe_uxengine_init2;
    if (!real_uxengine_init2) {
        void *symbol = real_dlsym(0, "uxengine_init2");
        if (!symbol) return 2;
        real_uxengine_init2 = symbol;
    }
    if (*(unsigned int *)stub != expected[0] || *(unsigned int *)(stub + 4) != expected[1]) return 3;
    if (mprotect((void *)page, 4096, 7) != 0) return 4;
    ((unsigned int *)stub)[0] = jump[0];
    ((unsigned int *)stub)[1] = jump[1];
    for (int i = 0; i < 8; ++i) stub[8 + i] = (unsigned char)(target >> (8 * i));
    clear_cache_range(stub, 16);
    if (mprotect((void *)page, 4096, 5) != 0) return 5;
    return 1;
}
/* Zero-injection sentinel for "did the model ever create a screen?". The view vtable is at
   RUNTIME VA base+0x58dbf38 (its file offset is 0x58cbf38: everything from .data.rel.ro onward is
   mapped +0x10000 in memory, so the earlier sentinel at 0x58cbf38 landed on a plain data table and
   could never fire - see force-screen/REPORT.md section 0). .rela.dyn confirms
   *0x58dbf38 = base+0x17cdb00 = view::create_screen, so slot 0 is patched here; replacing that slot with this wrapper
   logs the call without touching any library file or guest state. Signature per the debug name:
   virtual void view::create_screen(int, const ds_create_screen_param*, size_t,
                                    display_orientation_t, const bool*, const char*, const uint32_t*);
   - so the first eight integer arguments are forwarded verbatim. */
static void *(*real_create_screen)(void *, void *, void *, void *, void *, void *, void *, void *);
/* Read-only reconnaissance of the screen factory table. The dispatcher 0x1e4bacc loads its base
   from the GOT slot VA 0x5b4cfd0 -> VA 0x51f7810 and indexes 96-byte entries (per force-screen/REPORT.md
   section 2); entry+0x00 is the factory and entry+0x10 the numeric screen id. The real device's screen
   id counter sits at 604/605, so ids in 480..700 are the menu candidates. No writes, no calls. */
static void dump_factory_table(void) {
    if (!appfw_base) return;
    const unsigned char *table = (const unsigned char *)(appfw_base + 0x51f7810UL);
    unsigned int total = 0, shown = 0;
    for (unsigned int i = 0; i < 864; ++i) {
        const unsigned char *entry = table + (unsigned long)i * 96;
        unsigned long fn = *(const unsigned long *)entry;
        unsigned int id = *(const unsigned int *)(entry + 0x10);
        if (!fn) continue;
        ++total;
        if (id < 480 || id > 700) continue;
        char text[160];
        snprintf(text, sizeof text, "idx=%u fn=appFw+%#lx id=%u", i, fn - appfw_base, id);
        record("FACTORY_ENTRY ", text);
        if (++shown >= 60) break;
    }
    /* The id field at +0x10 is zero in the file image (the loader fills it), so the only way to learn
       the real screen ids is to read the table at runtime. Emit every id compactly: 12 per line. */
    char line[160];
    unsigned int written = 0;
    line[0] = 0;
    for (unsigned int i = 0; i < 864; ++i) {
        const unsigned char *entry = table + (unsigned long)i * 96;
        if (!*(const unsigned long *)entry) continue;
        unsigned int id = *(const unsigned int *)(entry + 0x10);
        char piece[16];
        int n = snprintf(piece, sizeof piece, "%s%u", written ? "," : "", id);
        if (n <= 0) break;
        for (int k = 0; piece[k]; ++k) line[written++] = piece[k];
        if (written > sizeof line - 24) {
            line[written] = 0;
            record("FACTORY_IDS ", line);
            written = 0;
            line[0] = 0;
        }
    }
    if (written) { line[written] = 0; record("FACTORY_IDS ", line); }
    char text[128];
    snprintf(text, sizeof text, "scanned=864 non_null=%u logged=%u (id window 480..700)", total, shown);
    record("FACTORY_TABLE ", text);
}
/* Injectable BB/CP event sequence aimed at the task_main thread (queue [appFw+0x910fa20]).
   bb-events/REPORT.md decoded that switch: only {frame=0x200d, code=0x1148} calls
   promise set_value (hash node 0x910f960), 0x1118 pushes internal event 0xd1 and 0x132b pushes 0x75
   while decrementing [0x910fa24]. Inject them in order and log the surrounding state so we can see
   whether any waiting caller wakes up. */
static void log_app_state(const char *tag) {
    if (!appfw_base) return;
    char text[256];
    snprintf(text, sizeof text,
             "%s promise_flag=%lu promise_ptr=%#lx hash_910f960=%#lx counter_910fa24=%lu hm_910fa1c=%#x tm_910fa20=%#x",
             tag,
             (unsigned long)*(volatile unsigned int *)(appfw_base + 0x910f9fc),
             (unsigned long)*(volatile unsigned long *)(appfw_base + 0x910fa00),
             (unsigned long)*(volatile unsigned long *)(appfw_base + 0x910f960),
             (unsigned long)*(volatile unsigned int *)(appfw_base + 0x910fa24),
             *(volatile unsigned int *)(appfw_base + 0x910fa1c),
             *(volatile unsigned int *)(appfw_base + 0x910fa20));
    record("APP_STATE ", text);
}
static int deliver_bb_event(unsigned int queue, unsigned int frame, unsigned int code, unsigned int extra) {
    void *msg = 0;
    if (real_allocate_msg(queue, &msg, 48, 1)) return -1;
    unsigned char *b = msg;
    for (int i = 0; i < 48; ++i) b[i] = 0;
    b[0] = frame & 0xff; b[1] = frame >> 8;
    b[2] = code & 0xff; b[3] = code >> 8;
    b[4] = 48; b[5] = 1;
    b[6] = extra & 0xff; b[7] = (extra >> 8) & 0xff;
    real_set_source(msg, 0x91ca0816);
    int result = real_send_msg(queue, msg);
    char text[128];
    snprintf(text, sizeof text, "frame=%#x code=%#x to queue %#x result=%d", frame, code, queue, result);
    record(result ? "TASK_MAIN_EVENT_FAILED " : "TASK_MAIN_EVENT ", text);
    if (result) real_free_msg(queue, msg);
    return result;
}
static void task_main_probe(void) {
    if (!appfw_base || !real_allocate_msg || !real_send_msg || !real_set_source || !real_free_msg) return;
    unsigned int queue = *(volatile unsigned int *)(appfw_base + 0x910fa20);
    if (!queue) { record("TASK_MAIN_EVENT ", "queue [0x910fa20] is zero"); return; }
    log_app_state("before");
    deliver_bb_event(queue, 0x200d, 0x1148, 0);
    log_app_state("after_1148");
    deliver_bb_event(queue, 0x200d, 0x1118, 0);
    log_app_state("after_1118");
    deliver_bb_event(queue, 0x200d, 0x132b, 0);
    log_app_state("after_132b");
}
/* Direct render poke: the model builds 28 screens but nothing is ever painted (the software GPE only
   sees one 640x480 fill and a flush). WidgetSystem is the ux widget root; driving its draw entry after
   the screens exist is the cheapest way to find out whether a populated widget tree can paint at all. */
/* The dispatcher's third argument is *(mgr+0x38) for idx <= 0x35f, so the value our factory hook sees
   cannot be turned back into mgr. The one function that receives the real manager (mov x22, x0 at
   0x1e770f0) is at 0x1e770e4 and is called from a single site. Patch its entry with a 16-byte stub
   (ldr x16,#8 / br x16 / .quad trampoline) and have the trampoline capture x0, replay the original
   prologue and continue at 0x1e770e4+16. Loaded literally, so no +-128 MB branch range limit. */
static unsigned long captured_manager;
static void *manager_continue_address __attribute__((used));
/* An entry probe must preserve the original LR and all ABI argument registers across its C call. */
#define PROBE_SAVE_ARGS \
"    sub sp, sp, #0xe0\n" \
"    stp x0, x1, [sp, #0]\n" \
"    stp x2, x3, [sp, #16]\n" \
"    stp x4, x5, [sp, #32]\n" \
"    stp x6, x7, [sp, #48]\n" \
"    stp x8, x30, [sp, #64]\n" \
"    stp q0, q1, [sp, #80]\n" \
"    stp q2, q3, [sp, #112]\n" \
"    stp q4, q5, [sp, #144]\n" \
"    stp q6, q7, [sp, #176]\n" \
"    mrs x16, nzcv\n" \
"    str x16, [sp, #208]\n"
#define PROBE_RESTORE_ARGS \
"    ldr x16, [sp, #208]\n" \
"    msr nzcv, x16\n" \
"    ldp q6, q7, [sp, #176]\n" \
"    ldp q4, q5, [sp, #144]\n" \
"    ldp q2, q3, [sp, #112]\n" \
"    ldp q0, q1, [sp, #80]\n" \
"    ldp x8, x30, [sp, #64]\n" \
"    ldp x6, x7, [sp, #48]\n" \
"    ldp x4, x5, [sp, #32]\n" \
"    ldp x2, x3, [sp, #16]\n" \
"    ldp x0, x1, [sp, #0]\n" \
"    add sp, sp, #0xe0\n"
void capture_manager(unsigned long candidate) {
    captured_manager = candidate;
    char text[128];
    snprintf(text, sizeof text, "manager=%#lx (captured at 0x1e770e4 entry)", candidate);
    record("MANAGER_CAPTURED ", text);
}
__asm__(
".text\n"
".globl manager_probe_trampoline\n"
".type manager_probe_trampoline, %function\n"
"manager_probe_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_manager\n"
PROBE_RESTORE_ARGS
"    stp x29, x30, [sp, #-0x80]!\n"      /* 原函数前 4 条指令 */
"    mov x29, sp\n"
"    stp x21, x22, [sp, #0x20]\n"
"    mov x22, x0\n"
"    adrp x16, manager_continue_address\n"
"    ldr x16, [x16, #:lo12:manager_continue_address]\n"
"    br x16\n"
);
extern void manager_probe_trampoline(void);
static void install_manager_probe(unsigned long base) {
    unsigned long target = base + 0x1e770e4UL;
    manager_continue_address = (void *)(target + 16);
    unsigned long page = target & ~0xfffUL;
    if (mprotect((void *)page, 4096, 7) != 0) {
        record("MANAGER_PROBE_FAILED ", "code page not writable");
        return;
    }
    unsigned int *code = (unsigned int *)target;
    code[0] = 0x58000050;                       /* ldr x16, [pc, #8] */
    code[1] = 0xd61f0200;                       /* br  x16 */
    *(unsigned long *)(target + 8) = (unsigned long)manager_probe_trampoline;
    clear_cache_range((void *)target, 16);
    char text[160];
    snprintf(text, sizeof text, "patched 0x1e770e4 -> trampoline=%p continue=%p",
             (void *)manager_probe_trampoline, manager_continue_address);
    record("MANAGER_PROBE_ARMED ", text);
}
/* libc entry points this file uses that are not declared elsewhere (freestanding build). */
extern char *strchr(const char *, int);
extern int dup2(int, int);
extern int sscanf(const char *, const char *, ...);

/* Menu-open attempt: rep_menu_controller is constructed by the framework through its vtable
   (runtime VA base+0x5b0c558, typeinfo base+0x5b0c530); init is slot 4 = base+0x20633c8 and it opens
   one of the menu screens 0x2c8/0x2c9/0x2ca chosen by *(u32*)(base+0x7ed79a8). Nothing in the app
   instantiates it in QEMU, so find an existing instance by scanning writable memory for a pointer to
   that vtable and, if one exists, drive it ourselves. */
static unsigned long find_pointer_in_memory(unsigned long want) {
    int maps = open("/proc/self/maps", 0);
    if (maps < 0) return 0;
    char buffer[8192];
    unsigned long found = 0;
    unsigned long scanned = 0;
    int used = 0;
    for (;;) {
        int n = read(maps, buffer + used, sizeof buffer - 1 - used);
        if (n <= 0) break;
        used += n;
        buffer[used] = 0;
        char *line = buffer;
        char *next;
        while ((next = strchr(line, '\n'))) {
            *next = 0;
            unsigned long start = 0, end = 0;
            char perms[8] = {0};
            if (sscanf(line, "%lx-%lx %7s", &start, &end, perms) == 3 && perms[0] == 'r' && perms[1] == 'w') {
                /* No address window: the instance sat ~1.2 GB away from appFw, which an earlier
                   ±512 MB heuristic wrongly excluded. Bound the scan by total bytes instead. */
                if (scanned < 0x60000000UL && end > start && end - start <= 0x40000000UL) {
                    unsigned long cursor = (start + 7) & ~7UL;
                    while (cursor + 8 <= end && scanned < 0x60000000UL) {
                        unsigned long value = *(volatile unsigned long *)cursor;
                        scanned += 8;
                        if (value == want) { found = cursor; break; }
                        cursor += 8;
                    }
                }
            }
            if (found) break;
            line = next + 1;
        }
        if (found) break;
        used = 0;
    }
    close(maps);
    {
        char text[96];
        snprintf(text, sizeof text, "scanned=%lu MB found=%#lx", scanned >> 20, found);
        record("POINTER_SCAN ", text);
    }
    return found;
}
/* Narrower menu-open attempt: skip rep_menu_controller::init (it runs transactions and constructs
   locals, and aborted when driven out of band) and call its last step directly, open_screen(this,
   &id1, &id2, &id3), with the id the application's own selector already points at. */
static unsigned int menu_open_attempts;
static void try_menu_open_screen(unsigned long instance) {
    if (!appfw_base || menu_open_attempts || !instance) return;
    if (!getenv("MENU_OPEN_SCREEN")) return;
    menu_open_attempts = 1;
    unsigned int selector = *(volatile unsigned int *)(appfw_base + 0x7ed79a8UL);
    unsigned int ids[3];
    ids[0] = selector <= 2 ? 0x2c8u + selector : 0x4b7u;
    ids[1] = 0x4b7u;
    ids[2] = 0x4b7u;
    char text[200];
    snprintf(text, sizeof text, "instance=%#lx selector=%u -> opening id1=%#x id2=%#x id3=%#x",
             instance, selector, ids[0], ids[1], ids[2]);
    record("MENU_OPEN_CALL ", text);
    typedef void (*open_t)(void *, void *, void *, void *);
    open_t open_screen = (open_t)(appfw_base + 0x2063270UL);
    open_screen((void *)instance, &ids[0], &ids[1], &ids[2]);
    record("MENU_OPEN_RETURNED ", "rep_menu_controller::open_screen returned");
}
/* Natural construction path for the menu controller (grok/menu-trigger-grok): factory table entry 838
   (id 0x346) carries aux 0x1d159f0, which builds the controller for a screen id using the per-id
   workspace at 0x7603190 + id*0x5000. Building it ourselves avoids the framework-side dispatch that
   aborted. Fields are logged before any virtual call so a bad object is visible instead of fatal. */
/* The launcher redirects the application's stdout/stderr into /tmp/im.log, so assert() messages vanish
   when the guest aborts. With MENU_STDIO_KMSG=1 send both to /dev/kmsg instead: they then appear in the
   console capture, which is the only channel that survives an abort. */
static void redirect_stdio_to_kmsg(void) {
    int console = open("/dev/console", 1);
    if (console < 0) { record("STDIO_KMSG_FAILED ", "/dev/console not writable"); return; }
    dup2(console, 1);
    dup2(console, 2);
    record("STDIO_KMSG_ACTIVE ", "stdout/stderr now go to /dev/console");
}
/* Observation only: wrap slot 4 (init) of all five mode-controller vtables so we can see which modes the
   framework actually activates in QEMU. Forwarding is 1:1, so this changes no behaviour. */
static const unsigned long mode_vtables[5] = { 0x5b0c4f0UL, 0x5b0c558UL, 0x5b0c5c0UL, 0x5b0c628UL, 0x5b0c690UL };
static void *(*mode_slot4_original[5])(void *, void *);
static const char *mode_slot4_names[5] = { "boot", "menu", "playback", "shooting", "single_playback" };
static unsigned int mode_slot4_calls[5];
static void *observe_mode_slot4(unsigned int index, void *a0, void *a1) {
    ++mode_slot4_calls[index];
    char text[160];
    snprintf(text, sizeof text, "mode=%s call=%u this=%p id_ptr=%p id=%#x", mode_slot4_names[index],
             mode_slot4_calls[index], a0, a1, a1 ? *(const unsigned int *)a1 : 0);
    record("MODE_SLOT4 ", text);
    if (mode_slot4_original[index]) return mode_slot4_original[index](a0, a1);
    return 0;
}
#define MODE_TRAMPOLINE(N) \
    static void *observe_mode_slot4_##N(void *a0, void *a1) { return observe_mode_slot4(N, a0, a1); }
MODE_TRAMPOLINE(0) MODE_TRAMPOLINE(1) MODE_TRAMPOLINE(2) MODE_TRAMPOLINE(3) MODE_TRAMPOLINE(4)
static void *(*const mode_slot4_wrapper[5])(void *, void *) = {
    observe_mode_slot4_0, observe_mode_slot4_1, observe_mode_slot4_2, observe_mode_slot4_3, observe_mode_slot4_4,
};
static void install_mode_sentinels(unsigned long base) {
    unsigned int armed = 0;
    for (unsigned int i = 0; i < 5; ++i) {
        unsigned long *slot = (unsigned long *)(base + mode_vtables[i] + 4 * 8);
        unsigned long page = (unsigned long)slot & ~0xfffUL;
        if (mprotect((void *)page, 4096, 7) != 0) continue;
        if (!*slot) continue;
        mode_slot4_original[i] = (void *(*)(void *, void *))*slot;
        *slot = (unsigned long)mode_slot4_wrapper[i];
        ++armed;
    }
    char text[96];
    snprintf(text, sizeof text, "armed=%u of 5 mode-controller init slots", armed);
    record("MODE_SENTINELS ", text);
}
/* Retain explicit diagnostics for legacy switches whose missing arguments could corrupt live pools. */
static unsigned int controller2_attempts;
static void try_build_controller2(void) {
    if (!getenv("MENU_BUILD_CONTROLLER2") || controller2_attempts) return;
    controller2_attempts = 1;
    record("BUILD2_DISABLED ", "legacy ctor ABI and workspace index were wrong; use framework lifecycle");
}
static unsigned int controller_build_attempts;
static void try_build_controller(void) {
    if (!getenv("MENU_BUILD_CONTROLLER") || controller_build_attempts) return;
    controller_build_attempts = 1;
    record("MENU_BUILD_DISABLED ", "legacy aux ABI omitted required arguments; shared workspace is live");
}
/* Generic mode-controller activation. All five rep_* controllers share one vtable layout (stride 0x68,
   slot 4 = init): boot 0x5b0c4f0, menu 0x5b0c558, playback 0x5b0c5c0, shooting 0x5b0c628,
   single_playback 0x5b0c690 - so "the framework activates a mode" is exactly vtable[4](obj, &screen_id).
   MENU_ACTIVATE_MODE=<0..4|boot|menu|playback|shooting|single> drives the instance we find on the heap. */
static const char *mode_names[5] = { "boot", "menu", "playback", "shooting", "single_playback" };
static unsigned int mode_activate_attempts;
static void try_activate_mode(void) {
    if (!appfw_base || mode_activate_attempts) return;
    const char *spec = getenv("MENU_ACTIVATE_MODE");
    if (!spec || !*spec) return;
    mode_activate_attempts = 1;
    int index = -1;
    if (spec[0] >= '0' && spec[0] <= '9') index = spec[0] - '0';
    else for (int i = 0; i < 5; ++i) {
        const char *n = mode_names[i];
        int k = 0;
        while (n[k] && spec[k] == n[k]) ++k;
        if (!n[k]) { index = i; break; }
    }
    if (index < 0 || index > 4) { record("MODE_ACTIVATE ", "bad MENU_ACTIVATE_MODE value"); return; }
    char text[200];
    snprintf(text, sizeof text, "mode=%s vtable=appFw+%#lx scanning heap...", mode_names[index], mode_vtables[index]);
    record("MODE_ACTIVATE_START ", text);
    unsigned long instance = find_pointer_in_memory(appfw_base + mode_vtables[index]);
    if (!instance) { record("MODE_ACTIVATE_NO_INSTANCE ", "no instance of that controller on the heap"); return; }
    typedef void (*init_t)(void *, void *);
    init_t init = (init_t)(*(unsigned long *)(*(unsigned long *)instance + 4 * 8));
    unsigned int screen_id = 0x4b7;
    snprintf(text, sizeof text, "instance=%#lx slot4=%#lx calling init(&id=%#x)",
             instance, (unsigned long)init, screen_id);
    record("MODE_ACTIVATE_CALL ", text);
    init((void *)instance, &screen_id);
    record("MODE_ACTIVATE_RETURNED ", "controller init returned");
}
static unsigned int menu_init_attempts;
static void try_menu_init(void) {
    if (!appfw_base || menu_init_attempts) return;
    if (!getenv("MENU_MENU_INIT") && !getenv("MENU_OPEN_SCREEN")) return;
    if (getenv("MENU_BUILD_CONTROLLER2")) { record("MENU_INIT_SKIPPED ", "using the locally built controller instead"); return; }
    unsigned long vtable = appfw_base + 0x5b0c558UL;
    unsigned int *selector = (unsigned int *)(appfw_base + 0x7ed79a8UL);
    char text[200];
    snprintf(text, sizeof text, "selector_before=%u vtable=appFw+0x5b0c558 scanning...", *selector);
    record("MENU_INIT_START ", text);
    unsigned long instance = captured_menu_controller;
    if (!instance) {
        /* Only fall back to the (slow) scan when we were not able to grab the constructor's object -
           inside the init window the scan is too slow and destabilises the guest. */
        if (getenv("MENU_FORCE_IN_FACTORY")) {
            record("MENU_INIT_NO_CAPTURE ", "ctor probe has not seen the controller and scanning is unsafe here");
            return;
        }
        instance = find_pointer_in_memory(vtable);
    }
    if (!instance) { record("MENU_INIT_NO_INSTANCE ", "no writable pointer to the rep_menu_controller vtable"); return; }
    /* Only now is this attempt spent: a hook point that fired before the framework constructed the
       controller must leave the next hook point free to try again. */
    menu_init_attempts = 1;
    void *instance_manager = *(void **)((char *)instance + 0x180);
    snprintf(text, sizeof text, "instance=%#lx selector=%u vtable=%p manager_180=%p field_178=%#lx",
             instance, *selector, *(void **)instance, instance_manager,
             *(unsigned long *)((char *)instance + 0x178));
    record("MENU_INIT_INSTANCE ", text);
    if (!instance_manager) {
        /* grok: init() dereferences [this+0x180]; an instance without a manager cannot be driven. */
        record("MENU_INIT_UNUSABLE ", "instance+0x180 (manager) is null; skipping init");
        return;
    }
    if (getenv("MENU_OPEN_SCREEN")) {
        /* The caller asked for the narrower path; keep the selector untouched. */
        try_menu_open_screen(instance);
        return;
    }
    if (getenv("MENU_INIT_LOG_ONLY")) {
        record("MENU_INIT_LOG_ONLY ", "scan only; no virtual call");
        return;
    }
    if (getenv("MENU_INIT_SELECTOR")) {
        unsigned int value = (unsigned int)(getenv("MENU_INIT_SELECTOR")[0] - '0');
        unsigned int *mirror = (unsigned int *)(appfw_base + 0x83d9d00UL);   /* publishing function copies this back */
        *selector = value;
        *mirror = value;                                                      /* keep them consistent */
        snprintf(text, sizeof text, "selector and mirror set to %u", value);
        record("MENU_INIT_SELECTOR_SET ", text);
    }
    unsigned int screen_id = 0x4b7;                  /* any id outside the 0x2c8..0x2ca / 0x346 set */
    typedef void (*init_t)(void *, void *);
    init_t init = (init_t)(appfw_base + 0x20633c8UL);
    snprintf(text, sizeof text, "calling init(this=%#lx, id=%#x)", instance, screen_id);
    record("MENU_INIT_CALL ", text);
    init((void *)instance, &screen_id);
    record("MENU_INIT_RETURNED ", "rep_menu_controller::init returned");
}
/* The framework constructs the menu controller itself (an instance with vtable 0x5b0c558 exists on the
   heap), but scanning for it inside the init window is far too slow. Capture it at the constructor
   entry instead - the ctor is menu-specific (it hardcodes w1=0x346 at 0x1d1586c) and x0 is the object
   under construction, so a 16-byte entry stub gives us the pointer in microseconds. */
void capture_menu_controller(unsigned long candidate) {
    if (!captured_menu_controller) {
        captured_menu_controller = candidate;
        char text[144];
        snprintf(text, sizeof text, "object=%#lx (from the rep_menu_controller ctor at 0x1d15858)", candidate);
        record("MENU_CONTROLLER_SEEN ", text);
    }
}
__asm__(
".text\n"
".globl menu_ctor_trampoline\n"
".type menu_ctor_trampoline, %function\n"
"menu_ctor_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_menu_controller\n"
PROBE_RESTORE_ARGS
"    sub sp, sp, #0x1c0\n"              /* 原函数前 4 条 */
"    stp x29, x30, [sp, #0x140]\n"
"    add x29, sp, #0x140\n"
"    stp x23, x24, [sp, #0x170]\n"
"    adrp x16, menu_ctor_continue\n"
"    ldr x16, [x16, #:lo12:menu_ctor_continue]\n"
"    br x16\n"
);
extern void menu_ctor_trampoline(void);
static void *menu_ctor_continue __attribute__((used));
static void install_menu_ctor_probe(unsigned long base) {
    unsigned long target = base + 0x1d15858UL;
    menu_ctor_continue = (void *)(target + 16);
    unsigned long page = target & ~0xfffUL;
    if (mprotect((void *)page, 4096, 7) != 0) { record("MENU_CTOR_PROBE_FAILED ", "code page not writable"); return; }
    unsigned int *code = (unsigned int *)target;
    code[0] = 0x58000050;                       /* ldr x16, [pc, #8] */
    code[1] = 0xd61f0200;                       /* br  x16 */
    *(unsigned long *)(target + 8) = (unsigned long)menu_ctor_trampoline;
    clear_cache_range((void *)target, 16);
    record("MENU_CTOR_PROBE_ARMED ", "0x1d15858 patched");
}
/* Manager slot3 enqueues (owner, screen, previous, true, false); it does not render synchronously.
   MENU_OPEN_SET=owner,screen[,previous] defaults previous to owner. Mutation requires EXECUTE. */
static int parse_open_set(const char *spec, unsigned int ids[3]) {
    for (unsigned int slot = 0; slot < 3; ++slot) {
        unsigned int value = 0, digits = 0, radix = 10;
        if (spec[0] == '0' && (spec[1] == 'x' || spec[1] == 'X')) { radix = 16; spec += 2; }
        for (;;) {
            unsigned int digit;
            if (*spec >= '0' && *spec <= '9') digit = (unsigned int)(*spec - '0');
            else if (*spec >= 'a' && *spec <= 'f') digit = (unsigned int)(*spec - 'a' + 10);
            else if (*spec >= 'A' && *spec <= 'F') digit = (unsigned int)(*spec - 'A' + 10);
            else break;
            if (digit >= radix) return 0;
            value = value * radix + digit;
            if (value >= 0x4b7) return 0;
            ++spec; ++digits;
        }
        if (!digits) return 0;
        ids[slot] = value;
        if (!*spec) {
            if (slot == 0) return 0;
            if (slot == 1) ids[2] = ids[0];
            return 1;
        }
        if (*spec++ != ',') return 0;
    }
    return 0;
}
static unsigned int open_set_attempts;
static void try_open_set(void) {
    if (!appfw_base || open_set_attempts) return;
    if (!__atomic_load_n(&create_screen_returned, __ATOMIC_ACQUIRE) ||
        __atomic_load_n(&create_screen_active, __ATOMIC_ACQUIRE) ||
        (unsigned int)syscall(178) != ui_thread_id) return;
    if (!captured_manager) {
        if (getenv("MENU_OPEN_SET_LOG_ONLY")) { record("MENU_OPEN_SET_WAIT ", "manager not captured yet"); open_set_attempts = 0; }
        return;
    }
    const char *spec = getenv("MENU_OPEN_SET");
    if (!spec || !*spec) return;
    open_set_attempts = 1;
    void **vtable = *(void ***)captured_manager;
    char text[224];
    if ((unsigned long)vtable != appfw_base + 0x5b0c480UL ||
        (unsigned long)vtable[3] != appfw_base + 0x1e77dd8UL) {
        record("OPEN_SET_NO_VTABLE ", "manager vtable does not match verified ABI");
        return;
    }
    if (!getenv("MENU_OPEN_SET_EXECUTE") || getenv("MENU_OPEN_SET_LOG_ONLY")) {
        snprintf(text, sizeof text,
                 "manager=%#lx vtable=%p slots=%p %p %p %p (log only; no call)",
                 captured_manager, (void *)vtable, vtable[0], vtable[1], vtable[2], vtable[3]);
        record("MENU_OPEN_SET_LOG_ONLY ", text);
        open_set_attempts = 1;
        return;
    }
    unsigned int ids[3];
    if (!parse_open_set(spec, ids)) {
        record("OPEN_SET_BAD_IDS ", "expected owner,screen[,previous], all below 0x4b7");
        return;
    }
    snprintf(text, sizeof text, "manager=%#lx slot3=%p owner=%#x screen=%#x previous=%#x",
             captured_manager, vtable[3], ids[0], ids[1], ids[2]);
    record("OPEN_SET_CALL ", text);
    typedef void (*open_t)(void *, void *, void *, void *, int, int);
    open_t open_screen = (open_t)vtable[3];
    open_screen((void *)captured_manager, &ids[0], &ids[1], &ids[2], 1, 0);
    record("OPEN_SET_RETURNED ", "manager enqueue returned; no claim of display completion");
}
static int ctor_census_attempts_used_class;
/* Bounded sample of objects passing through the shared base ctor; overflow is explicitly logged.
   Classification is deferred until create_screen has returned on the original UI thread. */
static unsigned long captured_objects[16];
static unsigned int captured_object_count;
void capture_controller_object(unsigned long pointer) {
    if (pointer) {
        unsigned int index = __atomic_fetch_add(&captured_object_count, 1, __ATOMIC_RELAXED);
        if (index >= 16) {
            if (index == 16) record("CTOR_CAPTURE_LIMIT ", "first 16 objects only; later constructors still run");
            return;
        }
        __atomic_store_n(&captured_objects[index], pointer, __ATOMIC_RELEASE);
        char text[96];
        snprintf(text, sizeof text, "obj[%u]=%#lx", index, pointer);
        record("CTOR_OBJECT ", text);
    }
}
__asm__(
".text\n"
".globl base_ctor_trampoline\n"
".type base_ctor_trampoline, %function\n"
"base_ctor_trampoline:\n"
PROBE_SAVE_ARGS
"    bl capture_controller_object\n"
PROBE_RESTORE_ARGS
"    stp x29, x30, [sp, #-0x50]!\n"
"    mov x29, sp\n"
"    stp x19, x20, [sp, #0x10]\n"
"    mov x19, x0\n"
"    adrp x16, base_ctor_continue\n"
"    ldr x16, [x16, #:lo12:base_ctor_continue]\n"
"    br x16\n"
);
extern void base_ctor_trampoline(void);
static void *base_ctor_continue __attribute__((used));
static void install_base_ctor_probe(unsigned long base) {
    unsigned long target = base + 0x1ac61f8UL;
    base_ctor_continue = (void *)(target + 16);
    unsigned long page = target & ~0xfffUL;
    if (mprotect((void *)page, 4096, 7) != 0) { record("CTOR_PROBE_FAILED ", "page not writable"); return; }
    unsigned int *code = (unsigned int *)target;
    code[0] = 0x58000050;
    code[1] = 0xd61f0200;
    *(unsigned long *)(target + 8) = (unsigned long)base_ctor_trampoline;
    clear_cache_range((void *)target, 16);
    record("CTOR_PROBE_ARMED ", "0x1ac61f8 patched");
}
static unsigned int ctor_census_processed;
static void ctor_census_and_activate(void) {
    if (!appfw_base || !__atomic_load_n(&create_screen_returned, __ATOMIC_ACQUIRE) ||
        __atomic_load_n(&create_screen_active, __ATOMIC_ACQUIRE) ||
        (unsigned int)syscall(178) != ui_thread_id) return;
    unsigned int count = __atomic_load_n(&captured_object_count, __ATOMIC_ACQUIRE);
    if (count > 16) count = 16;
    const char *want = getenv("MENU_ACTIVATE_CAPTURED");
    for (unsigned int i = ctor_census_processed; i < count; ++i) {
        unsigned long object = __atomic_load_n(&captured_objects[i], __ATOMIC_ACQUIRE);
        if (!object) break;
        ctor_census_processed = i + 1;
        unsigned long vptr = *(unsigned long *)object;
        const char *klass = vptr == appfw_base + 0x5b0e298UL ? "scr0039_boot" : "unknown";
        for (unsigned int k = 0; k < 5; ++k)
            if (vptr == appfw_base + mode_vtables[k]) klass = mode_names[k];
        char text[176];
        snprintf(text, sizeof text, "obj=%#lx vptr=appFw+%#lx class=%s manager_180=%p",
                 object, vptr ? vptr - appfw_base : 0, klass, *(void **)((char *)object + 0x180));
        record("CTOR_CENSUS ", text);
        if (want && klass[0] != 'u' && vptr != appfw_base + 0x5b0e298UL && !ctor_census_attempts_used_class) {
            int match = 1;
            for (int k = 0; want[k] || klass[k]; ++k)
                if (want[k] != klass[k]) { match = 0; break; }
            if (match) {
                void *manager = *(void **)((char *)object + 0x180);
                if (!manager) { record("CTOR_ACTIVATE_SKIPPED ", "manager field is null"); continue; }
                ctor_census_attempts_used_class = 1;
                unsigned long init = *(unsigned long *)(vptr + 4 * 8);
                unsigned int screen_id = 0x4b7;
                snprintf(text, sizeof text, "activating class=%s obj=%#lx init=%#lx", klass, object, init);
                record("CTOR_ACTIVATE_CALL ", text);
                typedef void (*init_t)(void *, void *);
                ((init_t)init)((void *)object, &screen_id);
                record("CTOR_ACTIVATE_RETURNED ", "controller init returned");
            }
        }
    }
}
static int ux_render_attempts;
static void ux_render_poke(const char *why) {
    if (!real_dlsym) return;
    static void *(*get_wgtsys)(void);
    static int (*notify_draw)(void *);
    if (!get_wgtsys) get_wgtsys = real_dlsym((void *)-1, "_ZN2ux6wgtsys12WidgetSystem15sys_getInstanceEv");
    if (!notify_draw) notify_draw = real_dlsym((void *)-1, "_ZN2ux6wgtsys12WidgetSystem10notifyDrawEv");
    if (!get_wgtsys || !notify_draw) {
        record("UX_RENDER_POKE ", "WidgetSystem entry points not found");
        return;
    }
    void *widget_system = get_wgtsys();
    if (!widget_system) { record("UX_RENDER_POKE ", "WidgetSystem instance is NULL"); return; }
    unsigned int attempt = ++ux_render_attempts;
    int draw_result = notify_draw(widget_system);
    char text[192];
    snprintf(text, sizeof text, "attempt=%u why=%s wgtsys=%p notifyDraw=%d", attempt, why, widget_system, draw_result);
    record("UX_RENDER_POKE ", text);
}
/* Screen factory capture. The dispatcher 0x1e4bacc calls factory(id[w0], ctx[x1], mgr+0x40|[mgr+0x38][x2],
   id[w3], idx[w4], param[w5]) - so w4 tells one shared wrapper which table entry it stands for, and the
   originals can be re-read from the saved copy. Writing the table (VA 0x51f7810, .data.rel.ro) only fills
   in the mgr/param context the application itself uses, which is exactly what a forced call would need. */
#define FACTORY_TABLE_ENTRIES 864
static unsigned long *factory_table_address;
static void *(*factory_original[FACTORY_TABLE_ENTRIES])(void *, void *, void *, void *, void *, void *);
static unsigned int factory_capture_count;
static void *captured_mgr_arg;
static unsigned int forced_dispatch_done;

/* Force the application to build another screen set. mgr = the x2 the application itself passed minus
   0x40 (dispatch() derives x2 from mgr), so once we have seen one factory call we hold every input the
   dispatcher needs. Indices come from MENU_FORCE_SET as a comma-separated list. */
static void force_screen_set(const char *why) {
    const char *spec = getenv("MENU_FORCE_SET");
    if (!spec || !*spec) return;
    {
        char diag[176];
        snprintf(diag, sizeof diag, "why=%s done=%u mgr=%#lx base=%#lx spec=%s",
                 why, forced_dispatch_done, captured_manager, appfw_base, spec);
        record("FORCE_SET_ENTER ", diag);
    }
    if (forced_dispatch_done || !captured_manager || !appfw_base) return;
    forced_dispatch_done = 1;
    typedef void *(*dispatch_t)(void *, int, int);
    dispatch_t dispatch = (dispatch_t)(appfw_base + 0x1e4baccUL);
    unsigned int current = 0;
    const char *cursor = spec;
    for (;;) {
        if (*cursor >= '0' && *cursor <= '9') {
            current = current * 10 + (unsigned int)(*cursor - '0');
        } else {
            if (current) {
                /* Log before the call so a crash inside the dispatcher still leaves a trace in /dev/kmsg. */
                char begin[160];
                snprintf(begin, sizeof begin, "begin why=%s idx=%u mgr=%p (mgr_arg=%p)",
                         why, current, (void *)captured_manager, (void *)captured_mgr_arg);
                record("FORCE_SET_BEGIN ", begin);
                void *set = dispatch((void *)captured_manager, (int)current, 0);
                char text[160];
                snprintf(text, sizeof text, "why=%s idx=%u returned=%p", why, current, set);
                record("FORCE_SET ", text);
                if (set && getenv("MENU_FORCE_OPEN_AFTER")) {
                    /* Second half of the same in-init window: hand the freshly built controller to
                       open_screen so it actually pushes its screen, exactly as init's tail does. */
                    unsigned int selector = *(volatile unsigned int *)(appfw_base + 0x7ed79a8UL);
                    unsigned int ids[3];
                    ids[0] = selector <= 2 ? 0x2c8u + selector : 0x4b7u;
                    ids[1] = 0x4b7u;
                    ids[2] = 0x4b7u;
                    void *manager_field = *(void **)((char *)set + 0x180);
                    unsigned long field_178 = *(unsigned long *)((char *)set + 0x178);
                    char open_text[240];
                    snprintf(open_text, sizeof open_text,
                             "controller=%p vtable=%p manager_180=%p field_178=%#lx selector=%u id1=%#x",
                             set, *(void **)set, manager_field, field_178, selector, ids[0]);
                    record("FORCE_OPEN_FIELDS ", open_text);
                    if (!manager_field) {
                        record("FORCE_OPEN_SKIPPED ", "object+0x180 (manager) is null; open_screen would dereference it");
                        return;
                    }
                    record("FORCE_OPEN_BEGIN ", "manager field is non-null; calling open_screen");
                    typedef void (*open_t)(void *, void *, void *, void *);
                    open_t open_screen = (open_t)(appfw_base + 0x2063270UL);
                    open_screen(set, &ids[0], &ids[1], &ids[2]);
                    record("FORCE_OPEN_RETURNED ", "open_screen returned inside init");
                }
            } else {
                record("FORCE_SET ", "ignored an empty index in MENU_FORCE_SET");
            }
            current = 0;
            if (*cursor == 0) break;
        }
        ++cursor;
    }
}
static void *observe_factory_entry(void *a0, void *a1, void *a2, void *a3, void *a4, void *a5) {
    unsigned long index = (unsigned long)a4;
    if (!captured_mgr_arg) captured_mgr_arg = a2;
    if (factory_capture_count < 60 && index < FACTORY_TABLE_ENTRIES) {
        ++factory_capture_count;
        char text[224];
        snprintf(text, sizeof text,
                 "idx=%lu id=%#lx (w0=%#lx w3=%#lx) ctx=%p mgr_arg=%p param=%#lx vtable_hint=0x1e4bacc",
                 index, (unsigned long)a3, (unsigned long)a0, (unsigned long)a3, a1, a2, (unsigned long)a5);
        record("FACTORY_CALL ", text);
    }
    void *result = 0;
    if (index < FACTORY_TABLE_ENTRIES && factory_original[index])
        result = factory_original[index](a0, a1, a2, a3, a4, a5);
    /* Optional in-init trigger: the manager is only usable while Application_System_Init runs, so with
       MENU_FORCE_IN_FACTORY=1 fire here (the manager is mid-use but valid) instead of in the message loop. */
    if (getenv("MENU_FORCE_IN_FACTORY")) force_screen_set("in_factory_during_init");
    /* Same in-init window: init() wraps its body in transactions, so driving it from the message loop
       aborted; calling it while Application_System_Init runs is the supported context. */
    if (getenv("MENU_FORCE_IN_FACTORY") && getenv("MENU_MENU_INIT")) try_menu_init();
    /* (open-set is driven from the init window only: the manager is invalid afterwards) */
    if (getenv("MENU_OPEN_SET")) try_open_set();
    if (getenv("MENU_FORCE_IN_FACTORY") && getenv("MENU_ACTIVATE_MODE")) try_activate_mode();
    if (getenv("MENU_FORCE_IN_FACTORY")) try_build_controller2();
    if (getenv("MENU_FORCE_IN_FACTORY") && getenv("MENU_MENU_INIT")) try_menu_init();
    return result;
}
static void install_factory_capture(unsigned long base) {
    factory_table_address = (unsigned long *)(base + 0x51f7810UL);
    unsigned long page = (unsigned long)factory_table_address & ~0xfffUL;
    if (mprotect((void *)page, 0x200000, 7) != 0) {
        record("FACTORY_HOOK_FAILED ", "factory table page is not writable");
        return;
    }
    unsigned int patched = 0;
    for (unsigned int i = 0; i < FACTORY_TABLE_ENTRIES; ++i) {
        unsigned long *slot = factory_table_address + (unsigned long)i * 12;   /* 96 bytes = 12 words */
        if (!*slot) continue;
        factory_original[i] = (void *(*)(void *, void *, void *, void *, void *, void *))*slot;
        *slot = (unsigned long)observe_factory_entry;
        ++patched;
    }
    char text[128];
    snprintf(text, sizeof text, "patched=%u table=appFw+%#lx", patched, 0x51f7810UL);
    record("FACTORY_HOOK_ARMED ", text);
}
/* Read-only: the factory looks its builder up in a .bss registry at VA 0x7603168 keyed by screen id
   (adrp x6,#0x7603000; add x6,x6,#0x168; ldr x19,[x6,w0,sxtw#3]). Enumerating the non-null entries
   tells us exactly which screen sets the application has registered - a much shorter candidate list for
   the menu than the 864-entry factory table. */
static void dump_screen_registry(void) {
    if (!appfw_base) return;
    const unsigned long *registry = (const unsigned long *)(appfw_base + 0x7603168UL);
    char line[180];
    unsigned int written = 0, count = 0;
    line[0] = 0;
    for (unsigned int i = 0; i < 4096; ++i) {
        if (!registry[i]) continue;
        ++count;
        char piece[24];
        int n = snprintf(piece, sizeof piece, "%s%u:appFw+%#lx", written ? " " : "", i,
                         (unsigned long)registry[i] - appfw_base);
        if (n <= 0) break;
        for (int k = 0; piece[k] && written < sizeof line - 32; ++k) line[written++] = piece[k];
        if (written > sizeof line - 40) {
            line[written] = 0;
            record("SCREEN_REGISTRY ", line);
            written = 0; line[0] = 0;
        }
    }
    if (written) { line[written] = 0; record("SCREEN_REGISTRY ", line); }
    char text[96];
    snprintf(text, sizeof text, "non_null=%u of 4096", count);
    record("SCREEN_REGISTRY_TOTAL ", text);
}
static unsigned int create_screen_calls;
static void *observe_create_screen(void *a0, void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *a7) {
    __atomic_add_fetch(&create_screen_active, 1, __ATOMIC_RELEASE);
    unsigned int id = (unsigned int)(unsigned long)a1;
    unsigned long count = (unsigned long)a3;
    unsigned int orientation = (unsigned int)(unsigned long)a4;
    /* ds_create_screen_param is 52 (0x34) bytes per entry; +0 is the screen kind, which is also the
       index into the ctor tables at VA 0x51b82a0 / 0x51b8790. Log the first kinds so we can tell the
       menu screen apart from whatever this boot actually creates. */
    char kinds[200];
    unsigned int written = 0;
    kinds[0] = 0;
    if (a2 && count && count <= 64) {
        const unsigned char *params = a2;
        for (unsigned long i = 0; i < count && i < 20 && written < sizeof kinds - 12; ++i) {
            unsigned int kind = *(const unsigned int *)(params + i * 52);
            char piece[16];
            int n = snprintf(piece, sizeof piece, "%s%u", i ? "," : "", kind);
            if (n <= 0) break;
            for (int k = 0; piece[k] && written < sizeof kinds - 1; ++k) kinds[written++] = piece[k];
            kinds[written] = 0;
        }
    }
    char text[320];
    snprintf(text, sizeof text, "call=%u id=%#x count=%lu orientation=%u this=%p kinds=[%s]",
             ++create_screen_calls, id, count, orientation, a0, kinds);
    record("CREATE_SCREEN_ARGS ", text);
    if (create_screen_calls == 1) {
        dump_factory_table();
        /* The view owns an arena base/capacity/used tuple here, not display handles. */
        const unsigned char *self = a0;
        char info[200];
        unsigned long arena = self ? *(const unsigned long *)(self + 0x3e98) : 0;
        unsigned int capacity = self ? *(const unsigned int *)(self + 0x3ea0) : 0;
        unsigned int used = self ? *(const unsigned int *)(self + 0x3ea4) : 0;
        unsigned long screens = self ? *(const unsigned long *)(self + 0x3e90) : 0;
        unsigned long first = self ? *(const unsigned long *)(self + 0x3ec8) : 0;
        unsigned long vtable = self ? *(const unsigned long *)self : 0;
        snprintf(info, sizeof info,
                 "this=%p vtable=appFw+%#lx count_slot=%lu arena=%#lx capacity=%u used=%u screen0=%#lx",
                 a0, vtable ? vtable - appfw_base : 0, screens, arena, capacity, used, first);
        record("CREATE_SCREEN_STATE ", info);
    }
    record("CREATE_SCREEN_CALLED ", "view::create_screen entered (vtable sentinel at VA 0x58dbf38)");
    if (!real_create_screen) {
        __atomic_sub_fetch(&create_screen_active, 1, __ATOMIC_RELEASE);
        return 0;
    }
    if (!ui_thread_id) ui_thread_id = (unsigned int)syscall(178);   /* remember the UI thread */
    void *result = real_create_screen(a0, a1, a2, a3, a4, a5, a6, a7);
    if (getenv("MENU_FORCE_IN_FACTORY") && getenv("MENU_MENU_INIT")) try_menu_init();
    snprintf(text, sizeof text, "call=%u returned=%p", create_screen_calls, result);
    record("CREATE_SCREEN_RETURN ", text);
    /* The model is alive here: 28 screens just got created. Read the real display state and,
       when asked, push the task_main event sequence that bb-events decoded. */
    if (a0) {
        char state[224];
        snprintf(state, sizeof state, "count_slot=%lu screen0=%#lx screen1=%#lx arena=%#lx",
                 *(const unsigned long *)((const unsigned char *)a0 + 0x3e90),
                 *(const unsigned long *)((const unsigned char *)a0 + 0x3ec8),
                 *(const unsigned long *)((const unsigned char *)a0 + 0x3ed0),
                 *(const unsigned long *)((const unsigned char *)a0 + 0x3e98));
        record("CREATE_SCREEN_POST ", state);
    }
    if (create_screen_calls == 1 && getenv("MENU_SCREEN_REGISTRY")) dump_screen_registry();
    if (getenv("MENU_TASK_MAIN_EVENTS") && create_screen_calls == 1) task_main_probe();
    if (getenv("MENU_UX_NOTIFY_DRAW")) {
        ux_render_poke("after_create_screen");
        ux_render_poke("after_create_screen_repeat");
    }
    __atomic_add_fetch(&create_screen_returned, 1, __ATOMIC_RELEASE);
    __atomic_sub_fetch(&create_screen_active, 1, __ATOMIC_RELEASE);
    return result;
}
/* The view vtable (runtime VA base+0x58dbf38) has create_screen in slot 0 and nine more methods in
   slots 1..10 (0x17b37ac, 0x17ce838, 0x17b3810, 0x17b388c, 0x17b3894, 0x17ceb44, 0x17cf43c,
   0x17cef74, 0x17b3920, 0x17b38c8 per force-screen/REPORT.md section 1). Creation and display are
   separate operations, so watch every slot to find which one submits a screen to the display. */
static void *(*real_view_slot[11])(void *, void *, void *, void *, void *, void *, void *, void *);
static unsigned int view_slot_calls[11];
static void record_view_content(void *object) {
    const unsigned char *view = object;
    if (!view) return;
    unsigned long count = *(const unsigned long *)(view + 0x3e90);
    unsigned long arena = *(const unsigned long *)(view + 0x3e98);
    unsigned int capacity = *(const unsigned int *)(view + 0x3ea0);
    unsigned int used = *(const unsigned int *)(view + 0x3ea4);
    char text[224];
    snprintf(text, sizeof text, "count=%lu arena=%#lx capacity=%u used=%u update_state=%u draw_state=%u",
             count, arena, capacity, used, *(unsigned int *)(appfw_base + 0x5c1efe4),
             *(unsigned int *)(appfw_base + 0x5c1efe0));
    record("VIEW_CONTENT_STATE ", text);
    if (count > 1000 || !arena || capacity > 0x2000000 || used > capacity || arena + used < arena) return;
    unsigned long end = arena + used;
    unsigned int widgets = 0;
    for (unsigned long i = 0; i < count; ++i) {
        unsigned int kind = *(const unsigned int *)(view + 0x10 + 16 * i);
        unsigned long param = *(const unsigned long *)(view + 0x18 + 16 * i);
        unsigned long widget = *(const unsigned long *)(view + 0x3ec8 + 8 * i);
        if (widget) ++widgets;
        if (i >= 32) continue;
        int valid = param >= arena && param <= end && end - param >= 0x44;
        int show = -1, content = -1;
        if (valid && (kind == 0 || kind == 38 || kind == 101)) {
            show = *(const unsigned char *)(param + 0x2c);
            if (kind == 0) content = *(const int *)(param + 0x3c);
            if (kind == 38) content = *(const int *)(param + 0x30);
            if (kind == 101) content = *(const unsigned char *)(param + 0x40);
        }
        snprintf(text, sizeof text, "item=%lu kind=%u widget=%#lx param=%#lx param_in_arena=%d show=%d content=%d",
                 i, kind, widget, param, valid, show, content);
        record("VIEW_CONTENT_ITEM ", text);
    }
    snprintf(text, sizeof text, "widgets=%u count=%lu sampled=%lu", widgets, count, count < 32 ? count : 32);
    record("VIEW_CONTENT_TOTAL ", text);
}
static void *observe_view_slot_entry(unsigned int slot, void *a0, void *a1, void *a2, void *a3,
                                     void *a4, void *a5, void *a6, void *a7) {
    unsigned int call = ++view_slot_calls[slot];
    if (getenv("MENU_FORCE_IN_FACTORY") && getenv("MENU_MENU_INIT")) try_menu_init();
    if (call <= 3) {
        char text[160];
        snprintf(text, sizeof text, "slot=%u call=%u this=%p a1=%#lx a2=%p a3=%#lx",
                 slot, call, a0, (unsigned long)a1, a2, (unsigned long)a3);
        record("VIEW_SLOT_CALLED ", text);
    }
    if (!real_view_slot[slot]) return 0;
    void *result = real_view_slot[slot](a0, a1, a2, a3, a4, a5, a6, a7);
    if (slot == 2 && call <= 2 && getenv("MENU_FRAME_OBSERVE")) record_view_content(a0);
    return result;
}
#define VIEW_SLOT_TRAMPOLINE(N) \
    static void *observe_view_slot_##N(void *a0, void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *a7) { \
        return observe_view_slot_entry(N, a0, a1, a2, a3, a4, a5, a6, a7); \
    }
VIEW_SLOT_TRAMPOLINE(1) VIEW_SLOT_TRAMPOLINE(2) VIEW_SLOT_TRAMPOLINE(3) VIEW_SLOT_TRAMPOLINE(4)
VIEW_SLOT_TRAMPOLINE(5) VIEW_SLOT_TRAMPOLINE(6) VIEW_SLOT_TRAMPOLINE(7) VIEW_SLOT_TRAMPOLINE(8)
VIEW_SLOT_TRAMPOLINE(9) VIEW_SLOT_TRAMPOLINE(10)
static void *(*const view_slot_wrapper[11])(void *, void *, void *, void *, void *, void *, void *, void *) = {
    0,
    observe_view_slot_1, observe_view_slot_2, observe_view_slot_3, observe_view_slot_4,
    observe_view_slot_5, observe_view_slot_6, observe_view_slot_7, observe_view_slot_8,
    observe_view_slot_9, observe_view_slot_10,
};
static void install_create_screen_sentinel(unsigned long base) {
    unsigned long slot_address = base + 0x58dbf38UL;   /* runtime VA, not the file offset */
    unsigned long page = slot_address & ~0xfffUL;
    if (mprotect((void *)page, 4096, 3) != 0) {
        record("CREATE_SCREEN_SENTINEL_FAILED ", "vtable page is not writable");
        return;
    }
    real_create_screen = (void *(*)(void *, void *, void *, void *, void *, void *, void *, void *))
        *(unsigned long *)slot_address;
    *(unsigned long *)slot_address = (unsigned long)observe_create_screen;
    /* Sanity check: the original slot must point inside appFw's own image (create_screen = base+0x17cdb00). */
    char text[200];
    unsigned long delta = (unsigned long)real_create_screen - base;
    snprintf(text, sizeof text, "slot=%#lx original=%#lx (appFw+%#lx; expect 0x17cdb00) wrapper=%#lx",
             slot_address, (unsigned long)real_create_screen, delta, (unsigned long)observe_create_screen);
    record("CREATE_SCREEN_SENTINEL ", text);
    /* Arm slots 1..10 with forwarding wrappers so we can see which of the other view methods
       (activate / enter display layer / open) the application actually reaches. */
    for (unsigned int slot = 1; slot <= 10; ++slot) {
        unsigned long *slot_pointer = (unsigned long *)(base + 0x58dbf38UL + slot * 8UL);
        if (!*slot_pointer) continue;
        real_view_slot[slot] = (void *(*)(void *, void *, void *, void *, void *, void *, void *, void *))*slot_pointer;
        *slot_pointer = (unsigned long)view_slot_wrapper[slot];
    }
    char slots[160];
    snprintf(slots, sizeof slots, "armed slots 1..10: originals appFw+%#lx,%#lx,%#lx,%#lx,%#lx",
             (unsigned long)real_view_slot[1] - base, (unsigned long)real_view_slot[2] - base,
             (unsigned long)real_view_slot[3] - base, (unsigned long)real_view_slot[4] - base,
             (unsigned long)real_view_slot[5] - base);
    record("VIEW_SLOTS_ARMED ", slots);
    {
        /* Which process loaded us, and which of our switches this process can actually see? */
        extern int getpid(void);
        int pid = getpid();
        char env_text[384];
        snprintf(env_text, sizeof env_text, "pid=%d base=%#lx MENU_FORCE_SET=%s MENU_FORCE_IN_FACTORY=%s FACTORY_HOOK=%s CTOR_CENSUS=%s OPEN_SET=%s OPEN_SET_LOG_ONLY=%s",
                 pid, appfw_base,
                 getenv("MENU_FORCE_SET") ? getenv("MENU_FORCE_SET") : "(unset)",
                 getenv("MENU_FORCE_IN_FACTORY") ? "1" : "(unset)",
                 getenv("MENU_FACTORY_HOOK") ? "1" : "(unset)",
                 getenv("MENU_CTOR_CENSUS") ? "1" : "(unset)",
                 getenv("MENU_OPEN_SET") ? getenv("MENU_OPEN_SET") : "(unset)",
                 getenv("MENU_OPEN_SET_LOG_ONLY") ? "1" : "(unset)");
        record("OBSERVER_READY ", env_text);
    }
    if (getenv("MENU_MODE_SENTINELS")) install_mode_sentinels(appfw_base);
    if (getenv("MENU_STDIO_KMSG")) redirect_stdio_to_kmsg();
    if (getenv("MENU_FACTORY_HOOK")) install_factory_capture(base);
    if (getenv("MENU_FORCE_SET") || getenv("MENU_BUILD_CONTROLLER2") || getenv("MENU_OPEN_SET") || getenv("MENU_APPLY_MENU")) install_manager_probe(base);
    if (getenv("MENU_MENU_INIT") || getenv("MENU_BUILD2_THEN_INIT") || getenv("MENU_APPLY_MENU")) install_menu_ctor_probe(base);
    if (getenv("MENU_CTOR_CENSUS") || getenv("MENU_ACTIVATE_CAPTURED")) install_base_ctor_probe(base);
}
static void *observe_application_init(void *argument) {
    record("ENTER ", "Application_System_Init");
    void *result = real_application_init(argument);
    record(result ? "RETURN_NONZERO " : "RETURN_ZERO ", "Application_System_Init");
    /* Post-init view-object walk: Application global [appfw+0x5f645e8] -> object;
       find the qword in object[0..0x2000) whose pointee starts with the view
       vtable (appfw+0x58cbf38, slot0=create_screen). In-process reads, no OOM.
       Temporarily disabled: binary-size shift correlates with a deterministic
       init-time UIPC ioctl abort (libc+0xc1cbc) under icount. */
#if 0
    if (result && appfw_base && !getenv("MENU_OBSERVE_SELFTEST")) {
        unsigned long *root = (unsigned long *)(appfw_base + 0x5f645e8);
        unsigned long object = *root;
        char text[140];
        snprintf(text, sizeof text, "object=%#lx", object);
        record("VTWALK_ROOT ", text);
        if (object > 0x7f00000000UL && object < 0x800000000000UL) {
            unsigned long vtable = appfw_base + 0x58cbf38;
            int hits = 0;
            for (unsigned long off = 0; off < 0x2000 && hits < 12; off += 8) {
                unsigned long candidate = *(unsigned long *)(object + off);
                if (candidate < 0x7f00000000UL || candidate > 0x800000000000UL) continue;
                unsigned long first = *(unsigned long *)candidate;
                if (first == vtable) {
                    snprintf(text, sizeof text, "obj_off=%#lx ptr=%#lx", off, candidate);
                    record("VTWALK_VIEW ", text);
                    ++hits;
                }
            }
            snprintf(text, sizeof text, "vtable=%#lx hits=%d", vtable, hits);
            record("VTWALK_DONE ", text);
        }
    }
#endif
    /* Resident-page heap scan for the view object: read /proc/self/maps, scan
       only RESIDENT pages (mincore) of small anonymous rw- mappings for qwords
       equal to the view vtable (appfw+0x58dbf38/0x58cbf38). No page-in, no OOM. */
    if (result && appfw_base && !getenv("MENU_OBSERVE_SELFTEST")) {
        static const char maps_path[] = "/proc/self/maps";
        int mfd = open(maps_path, 0);
        if (mfd >= 0) {
            char all[32768];
            long cap = 0, got;
            while (cap < (long)sizeof all - 1 && (got = read(mfd, all + cap, sizeof all - 1 - cap)) > 0) cap += got;
            all[cap < 0 ? 0 : cap] = 0;
            close(mfd);
            unsigned long vt1 = appfw_base + 0x58dbf38, vt2 = appfw_base + 0x58cbf38;
            char line[320];
            const char *p = all;
            int regions = 0;
            unsigned long hits[16];
            int nhit = 0;
            while (*p && nhit < 16) {
                const char *e = p;
                while (*e && *e != '\n') ++e;
                int len = e - p;
                if (len > 0 && len < 300) {
                    const char *q = p;
                    unsigned long lo = 0, hi = 0;
                    while (*q >= '0' && *q <= '9' || (*q >= 'a' && *q <= 'f')) { lo = lo * 16 + (*q >= 'a' ? *q - 'a' + 10 : *q - '0'); ++q; }
                    if (*q == '-') ++q;
                    while (*q >= '0' && *q <= '9' || (*q >= 'a' && *q <= 'f')) { hi = hi * 16 + (*q >= 'a' ? *q - 'a' + 10 : *q - '0'); ++q; }
                    while (*q == ' ') ++q;
                    if (*q == 'r' && q[1] == 'w' && lo >= 0x7f00000000UL && hi - lo <= 0x1000000UL) {
                        ++regions;
                        for (unsigned long page = lo; page + 4096 <= hi && nhit < 16; page += 4096) {
                            unsigned char vec = 0;
                            if (syscall(232, page, 4096, &vec) != 0) continue;  /* mincore */
                            if (!(vec & 1)) continue;
                            for (unsigned long off = 0; off < 4096 && nhit < 16; off += 8) {
                                unsigned long v = *(unsigned long *)(page + off);
                                if (v == vt1 || v == vt2) hits[nhit++] = page + off;
                            }
                        }
                    }
                }
                p = *e ? e + 1 : e;
            }
            char text[160];
            snprintf(text, sizeof text, "regions=%d hits=%d", regions, nhit);
            record("HEAPSCAN_DONE ", text);
            for (int i = 0; i < nhit && i < 8; ++i) {
                snprintf(text, sizeof text, "addr=%#lx", hits[i]);
                record("HEAPSCAN_VIEW ", text);
            }
        }
    }
    return result;
}
static int observe_updater_init(void) {
    record("ENTER ", "udtr_ufp_init");
    int result = real_updater_init();
    char text[64];
    snprintf(text, sizeof text, "udtr_ufp_init=%d", result);
    record("RETURN ", text);
    return result;
}
static int observe_updater_exit(void) {
    record("ENTER ", "udtr_ufp_exit");
    int result = real_updater_exit();
    char text[64];
    snprintf(text, sizeof text, "udtr_ufp_exit=%d", result);
    record("RETURN ", text);
    return result;
}
static int same_name(const char *name, const char *expected) {
    size_t i = 0;
    while (name && name[i] && name[i] == expected[i]) ++i;
    return name && !name[i] && !expected[i];
}
static int capid_send(unsigned int destination, void *request) {
    if (!capid.table || !real_allocate_msg || !real_free_msg || !real_get_source || !real_set_source || !real_msg_size)
        return -1021;
    if (!request) return -1024;
    unsigned int input_size = real_msg_size(request);
    if (input_size < (destination == 0x9004015e ? 24U : 16U)) return -1024;
    unsigned int *words = request;
    unsigned int operation = destination == 0x9004015e ? words[1] : words[2];
    unsigned int source = real_get_source(request);
    unsigned int size = destination == 0x9004015e ? (operation == 0x1000 ? 16 : operation == 0x1003 ? 0 : 8) : 24;
    if (destination == 0x9004015e && (words[0] || words[2] || words[3] || words[4] || words[5])) return -1024;
    void *reply = 0;
    int result = size ? real_allocate_msg(source, &reply, size, 1) : 0;
    if (result) return result;
    pthread_mutex_lock(cap_lock);
    long owner = syscall(178);
    struct cap_service previous = capid;
    struct cap_table previous_table = *capid.table;
    if (destination == 0x9004015e) {
        unsigned char unused[16];
        result = cap_control(&capid, operation, owner, reply ? reply : unused, &size);
    } else {
        result = cap_sync(&capid, request, input_size, reply);
    }
    if (!result && size) {
        real_set_source(reply, destination);
        result = real_send_msg(source, reply);
    }
    if (result) {
        *capid.table = previous_table;
        capid = previous; /* failed delivery leaves the request and service state unchanged */
    }
    char text[160];
    snprintf(text, sizeof text, "tid=%ld dest=%#x op=%#x source=%#x result=%d header=%u,%u,%u,%u,%u initialized=%d",
             owner, destination, operation, source, result, capid.table->header[0], capid.table->header[1],
             capid.table->header[2], capid.table->header[3], capid.table->header[4], capid.initialized);
    record("CAPID_SERVICE ", text);
    pthread_mutex_unlock(cap_lock);
    if (result) {
        if (reply) real_free_msg(source, reply);
        return result;
    }
    real_free_msg(destination, request); /* a successful virtual send consumes the request */
    return 0;
}
static int sa_address_send(void *request) {
    if (!real_allocate_msg || !real_free_msg || !real_set_source || !real_msg_size) return -1021;
    if (!request || real_msg_size(request) < 80) return -1024;
    const unsigned int *words = request;
    if (words[3] || !words[2]) return -1024; /* reply qid is zero-extended u32 at +8 */
    unsigned int source = words[2];
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 80, 1);
    if (result) return result;
    result = sa_address_reply(request, reply);
    if (!result) {
        const unsigned char *bytes = reply;
        char text[160];
        snprintf(text, sizeof text, "source=%#x status=%u detail=%u first=%#llx",
                 source, bytes[6], bytes[7], ((const unsigned long long *)reply)[2]);
        record("SA_ADDRESS_REPLY ", text);
        real_set_source(reply, 0x00930101);
        result = real_send_msg(source, reply);
    }
    if (result) { real_free_msg(source, reply); return result; }
    real_free_msg(0x00930101, request);
    return 0;
}
static int display_info_send(void *request) {
    if (!real_allocate_msg || !real_msg_size || !real_get_source || !real_set_source || !real_free_msg) return -1021;
    unsigned int source = real_get_source(request);
    if (!source) return -1024;
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 18, 1);
    if (result) return result;
    result = display_info_reply(&virtual_display, request, real_msg_size(request), reply);
    if (!result) { real_set_source(reply, 0x92840747); result = real_send_msg(source, reply); }
    if (result) { real_free_msg(source, reply); return result; }
    char geometry[140];
    snprintf(geometry, sizeof geometry, "virtual panel=%ux%u aspect=%u evf=%ux%u aspect=%u",
             virtual_display.panel_width, virtual_display.panel_height, virtual_display.panel_aspect,
             virtual_display.evf_width, virtual_display.evf_height, virtual_display.evf_aspect);
    record("DISPLAY_INFO_SERVICE ", geometry);
    real_free_msg(0x92840747, request);
    return 0;
}
static int yuv_layout_send(void *request) {
    if (!real_allocate_msg || !real_msg_size || !real_get_source || !real_set_source || !real_free_msg) return -1021;
    unsigned int source = real_get_source(request);
    if (!source) return -1024;
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 12, 1);
    if (result) return result;
    result = yuv_layout_reply(request, real_msg_size(request), reply);
    if (!result) { real_set_source(reply, 0x92840747); result = real_send_msg(source, reply); }
    if (result) { real_free_msg(source, reply); return result; }
    record("YUV_LAYOUT_SERVICE ", "observed 640x480 layout accepted; original 0x114c status 0");
    real_free_msg(0x92840747, request);
    return 0;
}
/* Reactive CP stand-in: whenever the application blocks on one of the sequence queues it
   allocated for boot sequence 42 (the 0x81cf61xx family, excluding the BB dispatcher queue
   itself), deliver the one event shape the dispatcher is known to accept, exactly once per
   queue. Those queues receive nothing at all in QEMU, which is where the model stalls. */
static void sequence_event_deliver(unsigned int queue, unsigned int ordinal) {
    if (!real_allocate_msg || !real_send_msg || !real_set_source || !real_free_msg) return;
    void *msg = 0;
    if (real_allocate_msg(queue, &msg, 48, 1)) { record("SEQ_EVENT ", "alloc failed"); return; }
    unsigned char *b = msg;
    for (int i = 0; i < 48; ++i) b[i] = 0;
    b[0] = 0x03; b[1] = 0x20;   /* frame 0x2003 */
    b[2] = 0x01; b[3] = 0x82;   /* code 0x8201 */
    b[4] = 48;
    const char *sel = getenv("MENU_SEQ_EVENT_SEL");
    b[10] = (sel && sel[0] >= '0' && sel[0] <= '9') ? (unsigned char)(sel[0] - '0') : 3;
    real_set_source(msg, 0x92840747);
    int result = real_send_msg(queue, msg);
    char text[144];
    if (result) {
        real_free_msg(queue, msg);
        snprintf(text, sizeof text, "send failed queue=%#x result=%d ordinal=%u", queue, result, ordinal);
        record("SEQ_EVENT_FAILED ", text);
        return;
    }
    snprintf(text, sizeof text, "delivered 0x2003/0x8201 to sequence queue %#x (ordinal %u)", queue, ordinal);
    record("SEQ_EVENT_DELIVERED ", text);
}
static void bb_output_ready_event(void) {
    /* Also directly trigger a UX render pass: WidgetSystem::notifyDraw() on the
       singleton. This bypasses the model key processing that never fires in
       QEMU (no CP events), but exercises the real UX→GPE render path. */
    if (real_dlsym) {
        static void *(*get_wgtsys)(void);
        static int (*notify_draw)(void *);
        if (!get_wgtsys) get_wgtsys = real_dlsym((void *)-1, "_ZN2ux6wgtsys12WidgetSystem15sys_getInstanceEv");
        if (!notify_draw) notify_draw = real_dlsym((void *)-1, "_ZN2ux6wgtsys12WidgetSystem10notifyDrawEv");
        if (get_wgtsys && notify_draw) {
            void *wgtsys = get_wgtsys();
            if (wgtsys) {
                int draw_result = notify_draw(wgtsys);
                char text[120];
                snprintf(text, sizeof text, "wgtsys=%p notifyDraw=%d (direct UX render trigger)", wgtsys, draw_result);
                record("UX_RENDER_TRIGGER ", text);
            } else {
                record("UX_RENDER_TRIGGER ", "WidgetSystem::sys_getInstance returned NULL");
            }
        } else {
            record("UX_RENDER_TRIGGER ", "sys_getInstance or notifyDraw not found");
        }
    }

    /* The CP event dispatcher (appFw 0x34e65f8) reads its queue from [appFw+0x910fa1c]
       via helper 0x3510fa4 and accepts exactly: frame u16 0x2003 @+0, code u16 0x8201 @+2,
       u16 3 @+0xa; it then stores u32 @+0x1c into global 0x910f9fc and fulfils a std::promise
       (0x34e6508) that a waiting AppFw sequence holds. On real hardware CP sends this after
       the output pipeline starts. Delivered once, in that accepted format; the stored value
       0 is the neutral/success reading. */
    if (!appfw_base || !real_allocate_msg || !real_send_msg || !real_set_source || !real_free_msg) return;
    unsigned int queue = *(volatile unsigned int *)(appfw_base + 0x910fa1c);
    if (!queue) { record("BB_OUTPUT_READY ", "dispatcher queue id is zero; skipped"); return; }
    void *msg = 0;
    if (real_allocate_msg(queue, &msg, 48, 1)) { record("BB_OUTPUT_READY ", "alloc failed"); return; }
    unsigned char *b = msg;
    for (int i = 0; i < 48; ++i) b[i] = 0;
    b[0] = 0x03; b[1] = 0x20;  /* frame 0x2003 */
    b[2] = 0x01; b[3] = 0x82;  /* code 0x8201 */
    b[4] = 48;                 /* size u16 */
    b[10] = 3;                 /* [+0xa] == 3 selector */
    real_set_source(msg, 0x92840747);
    int result = real_send_msg(queue, msg);
    if (result) { real_free_msg(queue, msg); record("BB_OUTPUT_READY ", "send failed"); return; }
    char text[120];
    snprintf(text, sizeof text, "delivered 0x2003/0x8201 [+a]=3 value=0 to dispatcher queue %#x", queue);
    record("BB_OUTPUT_READY ", text);
}
static int plane_config_send(void *request) {
    if (!real_allocate_msg || !real_msg_size || !real_get_source || !real_set_source || !real_free_msg) return -1021;
    unsigned int source = real_get_source(request);
    if (!source) return -1024;
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 12, 1);
    if (result) return result;
    result = a7r5_plane_reply(request, real_msg_size(request), reply);
    if (!result) { real_set_source(reply, 0x92840747); result = real_send_msg(source, reply); }
    if (result) { real_free_msg(source, reply); return result; }
    record("PLANE_CONFIG_SERVICE ", "A7R5 584-byte 0x147 plane table accepted; original 0x1147 status 0");
    /* CP sends a second, asynchronous SetOutputComp after the output pipeline settles
       ("[ADF][OUT] SetOutputComp:BootExit err %x replyId %x", cpapp-b string file+0x6f1ec).
       AppFw's async waiter (0x34e6afc region) receives ANY message on the reply queue,
       frees it unread (0x34e6b14), releases the dynamic id (0x359a218 = osal_dynamic_id
       release, type bit 0x40) and tears the queue down; content is not consulted.
       Deliver the same original 12-byte completion format as that async notification. */
    void *async_reply = 0;
    int async_result = real_allocate_msg(source, &async_reply, 12, 1);
    if (!async_result) {
        async_result = a7r5_plane_reply(request, real_msg_size(request), async_reply);
        if (!async_result) { real_set_source(async_reply, 0x92840747); async_result = real_send_msg(source, async_reply); }
    }
    if (!async_result) record("PLANE_CONFIG_ASYNC_COMP ", "original-format async SetOutputComp delivered to reply queue (waiter is content-agnostic)");
    else { if (async_reply) real_free_msg(source, async_reply); record("PLANE_CONFIG_ASYNC_COMP ", "async SetOutputComp delivery failed"); }
    if (!async_result) {
        if (getenv("MENU_BB_READY_LATE")) {
            bb_ready_pending = 1;
            record("BB_OUTPUT_READY ", "deferred: MENU_BB_READY_LATE=1 holds the 0x2003/0x8201 fulfilment until after the cold-boot chain and an injected key");
        } else {
            if (bb_ready_inject_enabled) bb_output_ready_event();
        }
        /* A7R5 按键状态门槛待独立核对。 */
    }
    real_free_msg(0x92840747, request);
    return 0;
}
static int pin_disconnect_send(void *request) {
    if (!real_allocate_msg || !real_msg_size || !real_get_source || !real_set_source || !real_free_msg) return -1021;
    unsigned int source = real_get_source(request);
    if (!source) return -1024;
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 16, 1);
    if (result) return result;
    result = pin_disconnect_reply(request, real_msg_size(request), reply);
    if (!result) { real_set_source(reply, 0x909c015b); result = real_send_msg(source, reply); }
    if (result) { real_free_msg(source, reply); return result; }
    char text[100];
    snprintf(text, sizeof text, "mode=%u; original 0x8101 completion status 0", ((const unsigned char *)request)[8]);
    record("PIN_DISCONNECT_SERVICE ", text);
    real_free_msg(0x909c015b, request);
    return 0;
}
/* Experimental registry service for the boot-sequence subscriptions.
   The model sends 13 subscriptions (0xf02..0xf0e, group 0x2a) to 0x811006e9 through appFw+0x36e8118's
   constructor and then waits. Nothing on this side ever answers them, so this optional service echoes a
   completion back to the sender's queue. Disabled unless QEMU_SUBSCRIPTION_SERVICE=1. */
static int subscription_service(unsigned int destination, void *request) {
    if (!request || !real_allocate_msg || !real_get_source || !real_set_source || !real_send_msg || !real_msg_size)
        return -1021;
    unsigned int source = real_get_source(request);
    unsigned int size = real_msg_size(request);
    if (!size || size > 64) size = 20;
    {
        char seen[96];
        snprintf(seen, sizeof seen, "code=%#x bytes=%u source=%#x",
                 size >= 4 ? (((const unsigned char *)request)[2] | (((const unsigned char *)request)[3] << 8)) : 0,
                 size, source);
        record("SUBSCRIPTION_SEEN ", seen);
    }
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, size, 1);
    if (result) {
        /* The subscription messages carry a poison source (0xa5a5a5a5), so a reply cannot go back
           to the sender. The real registry lives on the CP/BB side; the WBI snapshot pairs
           0x811006e9 with 0x81106114, so that is the candidate event queue. */
        if (getenv("QEMU_SUBSCRIPTION_EVENT")) {
            void *event_message = 0;
            int allocated = real_allocate_msg(0x81106114, &event_message, size, 1);
            if (!allocated) {
                const unsigned char *in_bytes = request;
                unsigned char *out_bytes = event_message;
                for (unsigned int i = 0; i < size; ++i) out_bytes[i] = in_bytes[i];
                real_set_source(event_message, 0x811006e9);
                int sent = real_send_msg(0x81106114, event_message);
                char event_text[128];
                snprintf(event_text, sizeof event_text, "event to 0x81106114 code=%#x result=%d",
                         size >= 4 ? (in_bytes[2] | (in_bytes[3] << 8)) : 0, sent);
                record(sent ? "SUBSCRIPTION_EVENT_FAILED " : "SUBSCRIPTION_EVENT ", event_text);
                if (sent) real_free_msg(0x81106114, event_message);
            } else {
                char event_text[96];
                snprintf(event_text, sizeof event_text, "event alloc failed=%d for 0x81106114", allocated);
                record("SUBSCRIPTION_EVENT_FAILED ", event_text);
            }
        }
        char text[96];
        snprintf(text, sizeof text, "alloc_failed=%d source=%#x; message left for the original path", result, source);
        record("SUBSCRIPTION_UNHANDLED ", text);
        return -1;   /* the hook falls through to real_send_msg */
    }
    const unsigned char *in = request;
    unsigned char *out = reply;
    for (unsigned int i = 0; i < size; ++i) out[i] = in[i];
    real_set_source(reply, destination);
    result = real_send_msg(source, reply);
    char text[128];
    snprintf(text, sizeof text, "code=%#x bytes=%u source=%#x reply_result=%d",
             size >= 4 ? (in[2] | (in[3] << 8)) : 0, size, source, result);
    record(result ? "SUBSCRIPTION_REPLY_FAILED " : "SUBSCRIPTION_REPLY ", text);
    if (result) real_free_msg(source, reply);
    real_free_msg(destination, request);
    return result;
}
static int hdmi_parameter_send(unsigned int destination, void *request) {
    if (!request || !real_allocate_msg || !real_get_source || !real_set_source || !real_free_msg || !real_msg_size)
        return -1021;
    unsigned int source = real_get_source(request);
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 12, 1);
    if (result) return result;
    pthread_mutex_lock(cap_lock);
    struct hdmi_format_state previous = hdmi_format;
    struct hdmi_photo_state previous_photo = hdmi_photo;
    int photo = destination == 0x909a015a;
    result = photo ? hdmi_photo_reply(&hdmi_photo, request, real_msg_size(request), reply) :
                     hdmi_format_reply(&hdmi_format, request, real_msg_size(request), reply);
    if (!result) {
        real_set_source(reply, destination);
        result = real_send_msg(source, reply);
    }
    if (result) { hdmi_format = previous; hdmi_photo = previous_photo; }
    char text[128];
    if (photo)
        snprintf(text, sizeof text, "source=%#x premium=%u preset6=%u applied=%u result=%d completion=0x8102",
                 source, hdmi_photo.premium, hdmi_photo.desired_preset6, hdmi_photo.applied, result);
    else
        snprintf(text, sizeof text, "source=%#x format=%u applied=%u result=%d completion=0x132f",
                 source, hdmi_format.format, hdmi_format.applied, result);
    record(photo ? "HDMI_PHOTO_SERVICE " : "HDMI_FORMAT_SERVICE ", text);
    pthread_mutex_unlock(cap_lock);
    if (result) { real_free_msg(source, reply); return result; }
#ifndef MENU_OBSERVE_TRANSPORT_SELFTEST
    int fd = open(photo ? "/tmp/hdmi-photo-state.bin" : "/tmp/hdmi-format-state.bin", 0x241, 0644);
    if (fd >= 0) {
        write(fd, photo ? (void *)&hdmi_photo : (void *)&hdmi_format,
              photo ? sizeof hdmi_photo : sizeof hdmi_format);
        close(fd);
    }
#endif
    real_free_msg(destination, request);
    return 0;
}
int osal_dynamic_id(unsigned int type, unsigned int owner, unsigned long value) {
    if (!real_dynamic_id) __builtin_trap();
    int result = real_dynamic_id(type, owner, value);
    unsigned int id = (unsigned int)value;
    if (!(type & 0x40)) id = result == 0 && value ? *(unsigned int *)value : 0;
    char text[128];
    snprintf(text, sizeof text, "type=%#x owner=%#x result=%d id=%#x caller=%p",
             type, owner, result, id,
             __builtin_return_address(0));
    if (result != 0 || owner == 0x1cf) record("DYNAMIC_ID ", text);
    return result;
}
/* Registration records are filtered to keep the log readable, but the filter used to
   drop the whole input queue family (0x7a804c / 0x7ae0xx / 0x807a0020). Those are the
   I-InputMain / I-InputEvent receive queues, so their registrations - and therefore the
   key-event handlers - were invisible in every earlier run. */
static int trace_registration(unsigned int id) {
    unsigned int family = (id >> 16) & 0xff;
    if (id == 0x5503e0 || family == 0x55 || family == 0x7a) return 1;
    return ((id >> 16) & 0xfff) == 0x1cf;
}
int osal_reg_sync_msg_queue_cb(unsigned int id, void **handle, void *callback, unsigned long argument) {
    if (!real_reg_sync) __builtin_trap();
    int result = real_reg_sync(id, handle, callback, argument);
    char text[160];
    snprintf(text, sizeof text, "id=%#x result=%d callback=%p arg=%#lx queue=%p caller=%p",
             id, result, callback, argument, handle ? *handle : 0, __builtin_return_address(0));
    if (result != 0 || trace_registration(id)) record("REG_SYNC ", text);
    if (getenv("MENU_OSD_OBSERVE") && (((id >> 16) & 0xfff) == 0x280 || ((id >> 16) & 0xfff) == 0x288))
        record("OSD_REGISTER_SYNC ", text);
    return result;
}
int osal_reg_msg_queue_cb(unsigned int id, void **handle, void *callback, unsigned long argument) {
    if (!real_reg_async) __builtin_trap();
    int result = real_reg_async(id, handle, callback, argument);
    Dl_info info;
    const char *module = "?";
    unsigned long offset = 0;
    void *caller = __builtin_return_address(0);
    if (real_dladdr && real_dladdr(caller, &info) && info.dli_fbase) {
        module = info.dli_fname ? info.dli_fname : "?";
        offset = (unsigned long)caller - (unsigned long)info.dli_fbase;
    }
    char text[240];
    snprintf(text, sizeof text, "id=%#x result=%d callback=%p arg=%#lx queue=%p caller=%s+%#lx",
             id, result, callback, argument, handle ? *handle : 0, module, offset);
    record("REG_ASYNC ", text);
    if (getenv("MENU_OSD_OBSERVE") && (((id >> 16) & 0xfff) == 0x280 || ((id >> 16) & 0xfff) == 0x288))
        record("OSD_REGISTER_ASYNC ", text);
    return result;
}
/* Inline success reply for the kernel-served version queue: get_lensversion
   (appFw+0x359ab08) sends {cmd=7} via infra_sync_call; upm.ko answers status=1
   (no lens power) which maps to model error 0x151. A successful sync send leaves
   the reply in the caller's message buffer, so writing it here and returning 0
   reproduces the original contract. Reply: halfword +4 status 0, halfwords +6/+8
   version, word +0x18 flag (all zero = generic lens, version 0). */
static int version_transport_reply(unsigned int id, void *message) {
    if (id != 0x004b024e || !message || !real_msg_size || real_msg_size(message) < 36 ||
        *(const unsigned int *)message != 7) return -1024;
    char text[128];
    snprintf(text, sizeof text, "tid=%ld bytes=%u source=%#x caller=%p",
             syscall(178), real_msg_size(message),
             real_get_source ? real_get_source(message) : 0, __builtin_return_address(0));
    record("LENS_VERSION_REQUEST ", text);
    for (unsigned int i = 4; i < 36; ++i) ((unsigned char *)message)[i] = 0;
    record("LENS_VERSION_SERVICE ", "inline sync reply: status 0, version 0, flag 0");
    return 0;
}
/* Bisect: the osal_snd_sync_direct interposition correlates with a NULL
   MonQueue::GetQueueRemain crash (libMWF+0x409d0) during late boot — both crashing
   builds exported it, the good build did not. Keep the function compiled but do
   not interpose (no dlsym redirect, no PLT export) until the mechanism is understood. */
#if 0
int osal_snd_sync_direct(unsigned int id, void *message) {
    if (!real_send_sync_direct) __builtin_trap();
    if (id == 0x004b024e) {
        char probe[128];
        unsigned int probe_size = real_msg_size && message ? real_msg_size(message) : 0;
        snprintf(probe, sizeof probe, "tid=%ld bytes=%u word0=%#x caller=%p",
                 syscall(178), probe_size, message ? *(const unsigned int *)message : 0,
                 __builtin_return_address(0));
        record("SYNC_DIRECT_HIT ", probe);
        int serviced = version_transport_reply(id, message);
        if (!serviced) return 0;
    }
    int result = real_send_sync_direct(id, message);
    char text[140];
    snprintf(text, sizeof text, "tid=%ld dest=%#x result=%d caller=%p",
             syscall(178), id, result, __builtin_return_address(0));
    record("SND_SYNC_DIRECT ", text);
    return result;
}
#endif
int osal_snd_sync_msg(unsigned int id, void *message) {
    if (!real_send_sync) __builtin_trap();
    if (id == 0x004b024e) {
        char probe[128];
        unsigned int probe_size = real_msg_size && message ? real_msg_size(message) : 0;
        snprintf(probe, sizeof probe, "tid=%ld bytes=%u word0=%#x source=%#x caller=%p",
                 syscall(178), probe_size, message ? *(const unsigned int *)message : 0,
                 (real_get_source && message) ? real_get_source(message) : 0,
                 __builtin_return_address(0));
        record("VERSION_TRANSPORT_HIT ", probe);
        int serviced = version_transport_reply(id, message);
        if (!serviced) return 0;
    }
    if (0 && id == 0x80924127 && message && real_msg_size && real_msg_size(message) >= 40) {
        /* Sensor GetInh/GetState sync query {0x92,0x111} (or sibling subcodes).
           Reply all-zero: status 0, no inhibit flags, no state — the same shape
           a real sensor returns when nothing inhibits the indicator. */
        unsigned int request = *(const unsigned int *)message;
        char text[140];
        snprintf(text, sizeof text, "tid=%ld request=%#x source=%#x caller=%p",
                 syscall(178), request,
                 real_get_source ? real_get_source(message) : 0, __builtin_return_address(0));
        record("SENSOR_GETINH_REQUEST ", text);
        for (unsigned int i = 4; i < 40; ++i) ((unsigned char *)message)[i] = 0;
        if (!__atomic_fetch_add(&sensor_service_count, 1, __ATOMIC_RELAXED))
            record("SENSOR_GETINH_SERVICE ", "first 0x80924127 reply: all-zero 40-byte sensor state");
        return 0;
    }
    if (0 && id == 0x003e014d && message && real_msg_size && real_msg_size(message) >= 8) {
        /* backup_sync_msg reads only the reply status word at +4 (libbackup+0x1ae8).
           Reply success so the after-UUD settings sync can complete instead of
           retrying forever against the absent CP backup queue. Sparse logging:
           the daemon issues tens of thousands of these per run. */
        unsigned int n = __atomic_fetch_add(&backup_service_count, 1, __ATOMIC_RELAXED);
        if (n < 5 || (n % 5000) == 0) {
            char text[140];
            snprintf(text, sizeof text, "tid=%ld n=%u bytes=%u cmd=%#x source=%#x caller=%p",
                     syscall(178), n + 1, real_msg_size(message), ((const unsigned int *)message)[2],
                     real_get_source ? real_get_source(message) : 0, __builtin_return_address(0));
            record("BACKUP_SYNC_REQUEST ", text);
        }
        ((unsigned int *)message)[1] = 0;  /* reply status at +4: success */
        if (!n) record("BACKUP_SYNC_SERVICE ", "first 0x3e014d reply: status 0 (writes acknowledged, no CP storage)");
        return 0;
    }
    int version = id == 0x004b024e && message && real_msg_size && real_msg_size(message) >= 10 && *(unsigned int *)message == 5;
    if (!version && message && real_msg_size) {
        unsigned int size = real_msg_size(message);
        unsigned int code = size >= 4 ? ((const unsigned short *)message)[1] : 0;
        char text[170];
        snprintf(text, sizeof text, "tid=%ld dest=%#x code=%#x bytes=%u source=%#x caller=%p",
                 syscall(178), id, code, size,
                 real_get_source ? real_get_source(message) : 0, __builtin_return_address(0));
        record("SND_SYNC_OTHER ", text);
    }
    int result = real_send_sync(id, message);
    if (version) {
        const unsigned short *p = message;
        char text[120];
        snprintf(text, sizeof text, "transport=%d status=%u major=%u minor=%u source=original provider/dat4", result, p[2], p[3], p[4]);
        record("CURRENT_VERSION_RESULT ", text);
    }
    return result;
}
static int dmm_send(void *request) {
    if (!real_allocate_msg || !real_free_msg || !real_get_source || !real_set_source || !real_msg_size || !real_send_msg)
        return -1021;
    unsigned int source = real_get_source(request);
    if (!source) return -1024;
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 40, 1);
    if (result) return result;
    pthread_mutex_lock(cap_lock);
    struct dmm_service previous = dmm;
    result = dmm_service_reply(&dmm, request, real_msg_size(request), reply);
    unsigned int handle = 0, size = 0;
    unsigned long long address = 0;
    int status = -1024;
    if (!result) {
        handle = ((unsigned int *)reply)[3]; size = ((unsigned int *)reply)[8];
        address = ((unsigned long long *)reply)[3]; status = ((short *)reply)[1];
    }
    if (!result) {
        real_set_source(reply, 0x9061003c);
        result = real_send_msg(source, reply);
    }
    if (result) dmm = previous;
    char text[220];
    snprintf(text, sizeof text, "source=%#x op=%#x transport=%d status=%d handle=%#x address=%#llx size=%#x slots=%d/%d opens=%u/%u",
             source, ((unsigned short *)request)[0], result,
             status, handle, address, size, dmm.slots[0].allocated, dmm.slots[1].allocated,
             dmm.slots[0].open_count, dmm.slots[1].open_count);
    record("DMM_SERVICE ", text);
    pthread_mutex_unlock(cap_lock);
    if (result) { real_free_msg(source, reply); return result; }
    real_free_msg(0x9061003c, request);
    return 0;
}
static unsigned int record_osd_transport(const char *prefix, unsigned int id, const void *message) {
    if (!getenv("MENU_OSD_OBSERVE")) return 0;
    unsigned int local = id & 0x7fffffffu;
    if (local != 0x0280074d && local != 0x0280084d && local != 0x0280084e &&
        local != 0x0288076c && local != 0x028808e1) return 0;
    static unsigned int total;
    unsigned int count = __atomic_add_fetch(&total, 1, __ATOMIC_RELAXED);
    if (count > 128) {
        if (count == 129) record("OSD_TRANSPORT_LIMIT ", "first 128 send/receive observations; later calls forwarded");
        return 0;
    }
    unsigned int size = message && real_msg_size ? real_msg_size((void *)message) : 0;
    unsigned int shown = size < 96 ? size : 96;
    const unsigned char *p = message;
    const char digits[] = "0123456789abcdef";
    char hex[193], text[448];
    for (unsigned int i = 0; i < shown; ++i) { hex[2*i] = digits[p[i] >> 4]; hex[2*i+1] = digits[p[i] & 15]; }
    hex[2*shown] = 0;
    snprintf(text, sizeof text, "call=%u tid=%ld endpoint=%#x source=%#x bytes=%u shown=%u payload=%s",
             count, syscall(178), id, message && real_get_source ? real_get_source((void *)message) : 0,
             size, shown, hex);
    record(prefix, text);
    return count;
}
int osal_rcv_msg_tmo(unsigned int id, void **message, long timeout) {
    if (!real_rcv_msg_tmo) __builtin_trap();
    if (sequence_event_enabled && appfw_base) {
        unsigned int dispatcher = *(volatile unsigned int *)(appfw_base + 0x910fa1c);
        if ((id >> 16) == 0x81cf && id != dispatcher) {
            static unsigned int delivered[16];
            static unsigned int delivered_count;
            int already = 0;
            for (unsigned int i = 0; i < delivered_count && i < 16; ++i)
                if (delivered[i] == id) { already = 1; break; }
            if (!already && delivered_count < 16) {
                delivered[delivered_count++] = id;
                sequence_event_deliver(id, delivered_count);
            }
        }
    }
    /* Record each (tid, queue, timeout) tuple once: full receive-map without flooding. */
    static struct { unsigned int tid, queue; long timeout; } seen[256];
    static unsigned int seen_count;
    unsigned int tid = (unsigned int)syscall(178);
    int trace = timeout < 0 || (id >> 16) == 0x81cf || id == 0x5503e0;
    int known = 0;
    for (unsigned int i = 0; i < seen_count && i < 256; ++i)
        if (seen[i].tid == tid && seen[i].queue == id && seen[i].timeout == timeout) { known = 1; break; }
    if (!known) {
        unsigned int slot = __atomic_fetch_add(&seen_count, 1, __ATOMIC_RELAXED);
        if (slot < 256) { seen[slot].tid = tid; seen[slot].queue = id; seen[slot].timeout = timeout; }
        Dl_info info;
        const char *module = "?";
        unsigned long offset = 0;
        void *caller = __builtin_return_address(0);
        if (real_dladdr && real_dladdr(caller, &info) && info.dli_fbase) {
            module = info.dli_fname ? info.dli_fname : "?";
            offset = (unsigned long)caller - (unsigned long)info.dli_fbase;
        }
        char text[240];
        snprintf(text, sizeof text, "tid=%u queue=%#x timeout=%ld caller=%s+%#lx", tid, id, timeout, module, offset);
        record("RCV_SITE ", text);
        if (getenv("MENU_OSD_OBSERVE") && (((id >> 16) & 0xfff) == 0x280 || ((id >> 16) & 0xfff) == 0x288))
            record("OSD_RECEIVER_SITE ", text);
    }
    char text[240];
    if (trace) {
        Dl_info info;
        const char *module = "?";
        unsigned long offset = 0;
        void *caller = __builtin_return_address(0);
        if (real_dladdr && real_dladdr(caller, &info) && info.dli_fbase) {
            module = info.dli_fname ? info.dli_fname : "?";
            offset = (unsigned long)caller - (unsigned long)info.dli_fbase;
        }
        snprintf(text, sizeof text, "tid=%ld queue=%#x timeout=%ld enter caller=%s+%#lx", syscall(178), id, timeout, module, offset);
        record("RCV_MSG_WAIT ", text);
    }
    int result = real_rcv_msg_tmo(id, message, timeout);
    /* 仅诊断批次记录消费端实际收到的五字段消息，不改变分发内容或返回值。 */
    if (!result && id == 0x807a0020 && message && *message && real_msg_size &&
        real_msg_size(*message) == 20 && getenv("A7R5_INPUT_RECEIPTS")) {
        const unsigned int *words = *message;
        snprintf(text, sizeof text,
                 "tid=%ld queue=%#x source=%#x key_code=%#x sub=%#x status=%#x ex=%#x from=%#x",
                 syscall(178), id, real_get_source ? real_get_source(*message) : 0,
                 words[0], words[1], words[2], words[3], words[4]);
        record("A7R5_INPUT_RECEIVED ", text);
    }
    if (!result && message && *message) record_osd_transport("OSD_TRANSPORT_RECEIVE ", id, *message);
    if (!result && id == 0x807a0020 && bb_ready_pending) bb_key_seen = 1;
    if (trace) {
        unsigned int code = 0, size = 0;
        if (!result && message && *message && real_msg_size) {
            size = real_msg_size(*message);
            if (size >= 4) code = ((const unsigned short *)*message)[1];
        }
        snprintf(text, sizeof text, "tid=%ld queue=%#x timeout=%ld result=%d reply_code=%#x bytes=%u",
                 syscall(178), id, timeout, result, code, size);
        record("RCV_MSG_TMO ", text);
    }
    return result;
}
static unsigned int lens_pool_lookup_flags(void *message, unsigned int *from) {
    pthread_mutex_lock(lens_pool_lock);
    unsigned int flags = 0;
    for (int i = 0; i < LENS_POOL_SLOTS; ++i)
        if (lens_pool[i].live && lens_pool[i].message == message) {
            flags = lens_pool[i].live;
            *from = lens_pool[i].borrowed_from;
            lens_pool[i].live = 0;
            break;
        }
    pthread_mutex_unlock(lens_pool_lock);
    return flags;
}
static unsigned int lens_pool_lookup(void *message) {
    unsigned int from = 0;
    lens_pool_lookup_flags(message, &from);
    return from;
}
int osal_valloc_msg_wait(unsigned int id, void **message, unsigned int size, unsigned int count) {
    if (!real_allocate_msg) __builtin_trap();
    if (id == 0x004b024e) {
        char probe[96];
        snprintf(probe, sizeof probe, "tid=%ld size=%u count=%u", syscall(178), size, count);
        record("VERSION_VALLOC_HIT ", probe);
    }
    if (0 && id == 0x80924127 && size == 40 && count == 1 && message) {
        /* libObj sensor GetInh/GetState family (clients at libObj+0xcc07c/+0xed6e0):
           valloc 40 bytes from the absent 0x8092-node sensor queue, sync query
           {0x92,0x111,...}. Without a reply the CInfraIndctr lazy-init at
           libObj+0xc7cfc leaves its [0x28] sub-object dangling and the next
           indicator log SEGVs (run-7fan0f7i/8bgy9uuw at libObj+0xc7ce4). */
        extern void *malloc(unsigned long);
        unsigned char *raw = malloc(16 + 40);
        if (!raw) return -1024;
        for (int i = 0; i < 56; ++i) raw[i] = 0;
        *(unsigned int *)(raw + 8) = 40;
        *message = raw + 16;
        pthread_mutex_lock(lens_pool_lock);
        int slot = -1;
        for (int i = 0; i < LENS_POOL_SLOTS; ++i)
            if (!lens_pool[i].live) { slot = i; break; }
        if (slot >= 0) {
            lens_pool[slot].live = 2;
            lens_pool[slot].message = *message;
            lens_pool[slot].borrowed_from = 0;
        }
        pthread_mutex_unlock(lens_pool_lock);
        record("SENSOR_POOL_ALLOC ", "malloc'd 40 bytes with osal header");
        return 0;
    }
    if (0 && id == 0x003e014d && size == 112 && count == 1 && message && !backup_service_enabled) {
        /* Diagnostic-only path: with the reply service disabled the valloc keeps
           failing exactly as before (silent return 0 + infinite retry), but the
           first commands are logged so the reply policy can be made selective. */
        return real_allocate_msg(id, message, size, count);
    }
    if (0 && id == 0x003e014d && size == 112 && count == 1 && message) {
        /* libbackup backup_sync_msg (libbackup+0x1a10) vallocs 112 bytes from the
           CP-side backup queue; without it every call fails silently (returns 0 with
           the result word untouched) and the daemon retries forever (39k+ per run).
           The message never enters a kernel queue (the sync send is serviced inline),
           so a malloc'd buffer with the 16-byte osal header (size at -8, src at -0xc)
           satisfies osal_msg_size/get_msg_src exactly. */
        extern void *malloc(unsigned long);
        unsigned char *raw = malloc(16 + 112);
        if (!raw) return -1024;
        for (int i = 0; i < 128; ++i) raw[i] = 0;
        *(unsigned int *)(raw + 8) = 112;
        *message = raw + 16;
        pthread_mutex_lock(lens_pool_lock);
        int slot = -1;
        for (int i = 0; i < LENS_POOL_SLOTS; ++i)
            if (!lens_pool[i].live) { slot = i; break; }
        if (slot >= 0) {
            lens_pool[slot].live = 2;  /* 2 = malloc'd, free with free(raw) */
            lens_pool[slot].message = *message;
            lens_pool[slot].borrowed_from = 0;
        }
        pthread_mutex_unlock(lens_pool_lock);
        record("BACKUP_POOL_ALLOC ", slot >= 0 ? "malloc'd 112 bytes with osal header" : "map full; leak instead of wrong free");
        return 0;
    }
    if (id == 0x912503d0 && size == 20 && count == 1 && message) {
        /* Borrow the ulog queue pool: the CP updater queue does not exist in QEMU. */
        int result = real_allocate_msg(0x8f013a, message, 20, 1);
        if (!result) {
            pthread_mutex_lock(lens_pool_lock);
            int slot = -1;
            for (int i = 0; i < LENS_POOL_SLOTS; ++i)
                if (!lens_pool[i].live) { slot = i; break; }
            if (slot >= 0) {
                lens_pool[slot].live = 1;
                lens_pool[slot].message = *message;
                lens_pool[slot].borrowed_from = 0x8f013a;
            }
            pthread_mutex_unlock(lens_pool_lock);
            record("LENS_POOL_ALLOC ", slot >= 0 ? "borrowed 20 bytes from 0x8f013a" : "map full; free will passthrough");
        }
        return result;
    }
    return real_allocate_msg(id, message, size, count);
}
int osal_free_msg(unsigned int id, void *message) {
    if (!real_free_msg) __builtin_trap();
    if (id == 0x912503d0 && message) {
        unsigned int from = 0;
        unsigned int flags = lens_pool_lookup_flags(message, &from);
        if (flags == 2) { extern void free(void *); free((char *)message - 16); return 0; }
        if (from) return real_free_msg(from, message);
    }
    return real_free_msg(id, message);
}

static struct a7r5_hdmi_state a7r5_hdmi;
static int a7r5_hdmi_send(void *message) {
    if (!real_msg_size || !real_get_source || !real_allocate_msg || !real_set_source || !real_send_msg || !real_free_msg)
        return -1021;
    unsigned int source = real_get_source(message);
    if (!source) return -1024;
    void *reply = 0;
    int result = real_allocate_msg(source, &reply, 12, 1);
    if (result) return result;
    struct a7r5_hdmi_state before = a7r5_hdmi;
    result = a7r5_hdmi_reply(&a7r5_hdmi, message, real_msg_size(message), reply);
    if (!result) { real_set_source(reply, 0x92840747); result = real_send_msg(source, reply); }
    if (result) { a7r5_hdmi = before; real_free_msg(source, reply); return result; }
    real_free_msg(0x92840747, message);
    record("A7R5_HDMI_032D ", "accepted exact 10-byte request; virtual setting only");
    return 0;
}

int osal_snd_msg(unsigned int id, void *message) {
    if (!real_send_msg) __builtin_trap();
    /* Force-dispatch from the application's own message loop, i.e. after its UI construction stack has
       unwound: calling the dispatcher from inside create_screen re-entered the manager and aborted. */
    if (create_screen_calls >= 1 && !getenv("MENU_FORCE_IN_FACTORY")) force_screen_set("in_message_loop");
    if (create_screen_calls >= 1 && !getenv("MENU_FORCE_IN_FACTORY")) {
        int right_thread = 1;
        if (getenv("MENU_UI_THREAD_ONLY") && ui_thread_id && (unsigned int)syscall(178) != ui_thread_id)
            right_thread = 0;
        if (right_thread) {
            try_menu_init();
            /* Mode activation from the application's own loop, on its UI thread: scanning here is safe
               (see PHASE-STATUS section 19) and this targets the instance the framework itself built. */
            if (getenv("MENU_ACTIVATE_MODE")) try_activate_mode();
            if ((getenv("MENU_CTOR_CENSUS") || getenv("MENU_ACTIVATE_CAPTURED")) && create_screen_calls >= 1)
                ctor_census_and_activate();
            /* The factory window fires before the manager is captured, so the same submission is also
               attempted from the UI thread once the framework really exists. */
            if (getenv("MENU_OPEN_SET") && captured_manager && create_screen_calls >= 1) try_open_set();
        }
    }
    if (create_screen_calls >= 1) try_build_controller();
    /* Top-level dispatch: the subscription registry is a different destination from the
       BB config queue, so this must sit outside the 0x92840747 branch. */
    if (subscription_enabled && id == 0x811006e9 && message) {
        int handled = subscription_service(id, message);
        if (handled >= 0) return handled;
    }
    if (id == 0x9061003c && message && real_msg_size && real_msg_size(message) >= 40) {
        const unsigned int *words = message;
        char text[180];
        snprintf(text, sizeof text, "tid=%ld op=%#x unit=%#x handle=%#x option=%#x source=%#x",
                 syscall(178), words[0] & 65535, words[1], words[2],
                 ((const unsigned short *)message)[11], real_get_source ? real_get_source(message) : 0);
        record("DMM_REQUEST ", text);
        if (dmm_enabled && (words[0] & 65535) >= 0x20 && (words[0] & 65535) <= 0x23) return dmm_send(message);
    }
    if (capid_enabled && (id == 0x9004015e || id == 0x92850750)) return capid_send(id, message);
    if (id == 0x92840747 && message && real_msg_size && real_msg_size(message) >= 8) {
        const unsigned short *head = message;
        char text[160];
        snprintf(text, sizeof text, "tid=%ld frame=%#x property=%#x bytes=%u flags=%#x source=%#x",
                 syscall(178), head[0], head[1], real_msg_size(message), head[3],
                 real_get_source ? real_get_source(message) : 0);
        record("BB_CONFIG_REQUEST ", text);
        if (display_info_enabled && head[0] == 0x200d && head[1] == 0x16a) return display_info_send(message);
        if (display_info_enabled && head[0] == 0x200d && head[1] == 0x14c) return yuv_layout_send(message);
        if (display_info_enabled && head[0] == 0x200d && head[1] == 0x147) return plane_config_send(message);
        if (display_info_enabled && head[0] == 0x200d && (head[1] == 0x161 || head[1] == 0x13d || head[1] == 0x11a)) {
            unsigned int source = real_get_source ? real_get_source(message) : 0;
            if (!source || !real_allocate_msg || !real_set_source || !real_free_msg) return -1021;
            void *reply = 0;
            int result = real_allocate_msg(source, &reply, 12, 1);
            if (result) return result;
            result = head[1] == 0x161 ? prop_161_reply(message, real_msg_size(message), reply)
                     : head[1] == 0x13d ? prop_13d_reply(message, real_msg_size(message), reply)
                                        : prop_11a_reply(message, real_msg_size(message), reply);
            if (!result) { real_set_source(reply, 0x92840747); result = real_send_msg(source, reply); }
            if (result) { real_free_msg(source, reply); return result; }
            record(head[1] == 0x161 ? "PROP_161_SERVICE " : head[1] == 0x13d ? "PROP_13D_SERVICE " : "PROP_11A_SERVICE ",
                   head[1] == 0x161 ? "observed 10-byte 0x161 request accepted; original 0x1161 completion status 0"
                   : head[1] == 0x13d ? "observed 10-byte 0x13d request accepted; original 0x113d completion status 0"
                                      : "observed 14-byte 0x11a request accepted; original 0x111a completion status 0");
            real_free_msg(0x92840747, message);
            return 0;
        }
        if (hdmi_format_enabled && head[0] == 0x200d && head[1] == 0x32d) return a7r5_hdmi_send(message);
        if (hdmi_format_enabled && head[0] == 0x200d && head[1] == 0x32f) return hdmi_parameter_send(id, message);
    }
    if (id == 0x909c015b && message && real_msg_size && real_msg_size(message) >= 12) {
        const unsigned short *head = message;
        char text[160];
        snprintf(text, sizeof text, "tid=%ld frame=%#x code=%#x bytes=%u flags=%#x mode=%u source=%#x",
                 syscall(178), head[0], head[1], real_msg_size(message), head[3],
                 ((const unsigned char *)message)[8], real_get_source ? real_get_source(message) : 0);
        record("PIN_REQUEST ", text);
        if (display_info_enabled && head[0] == 0 && head[1] == 0x101) return pin_disconnect_send(message);
    }
    if (id == 0x909a015a && message && real_msg_size && real_msg_size(message) >= 12) {
        const unsigned short *head = message;
        char text[160];
        snprintf(text, sizeof text, "tid=%ld frame=%#x command=%#x bytes=%u flags=%#x value=%#x source=%#x",
                 syscall(178), head[0], head[1], real_msg_size(message), head[3],
                 ((const unsigned int *)message)[2], real_get_source ? real_get_source(message) : 0);
        record("HDMI_PHOTO_REQUEST ", text);
        if (hdmi_photo_enabled && head[0] == 0x2500 && head[1] == 0x102) return hdmi_parameter_send(id, message);
        if (display_info_enabled && head[0] == 0x2500 && head[1] == 0x109) {
            unsigned int source = real_get_source ? real_get_source(message) : 0;
            if (!source || !real_allocate_msg || !real_set_source || !real_free_msg) return -1021;
            void *reply = 0;
            int result = real_allocate_msg(source, &reply, 12, 1);
            if (result) return result;
            result = pin_hdmi_reply(message, real_msg_size(message), reply);
            if (!result) { real_set_source(reply, id); result = real_send_msg(source, reply); }
            if (result) { real_free_msg(source, reply); return result; }
            record("PIN_HDMI_SERVICE ", "observed 0x2500/0x109 request accepted; original 0x8109 completion status 0");
            real_free_msg(id, message);
            return 0;
        }
    }
    if (id == 0x00930101 && message && real_msg_size && real_msg_size(message) >= 16) {
        const unsigned short *head = message;
        const unsigned long long *addresses = message;
        char text[192];
        snprintf(text, sizeof text, "tid=%ld cmd=%#x count=%u reply=%#llx caller=%p",
                 syscall(178), head[0], head[2], addresses[1], __builtin_return_address(0));
        record("SA_ADDRESS_REQUEST ", text);
        if (head[0] == 0xb850 && head[2] <= 8 && real_msg_size(message) >= 16U + 8U * head[2])
            for (unsigned int i = 0; i < head[2]; ++i) {
                snprintf(text, sizeof text, "index=%u address=%#llx", i, addresses[2 + i]);
                record("SA_ADDRESS_INPUT ", text);
            }
        int result = sa_address_enabled && head[0] == 0xb850 ? sa_address_send(message) : real_send_msg(id, message);
        snprintf(text, sizeof text, "tid=%ld result=%d", syscall(178), result);
        record("SA_ADDRESS_SEND_RETURN ", text);
        return result;
    }
    if (id == 0x912503d0 && message && real_msg_size && real_msg_size(message) == 20 &&
        *(const unsigned int *)message == 0) {
        /* libInfraGetVersion.so+0xe08 lens getter: 20-byte {0} request, dynamic-id reply
           queue in msg source, 1s wait. Reply validated at +0xeec: [+0]==0 status,
           [+4] type<=4 with (1<<type)&0x1d, version at +8/+0xa/+0xe. Type 0 = generic. */
        unsigned int source = real_get_source ? real_get_source(message) : 0;
        char text[160];
        snprintf(text, sizeof text, "tid=%ld source=%#x caller=%p",
                 syscall(178), source, __builtin_return_address(0));
        record("LENS_VERSION_REQUEST ", text);
        if (source && real_allocate_msg && real_set_source && real_free_msg && real_send_msg) {
            void *reply = 0;
            int result = real_allocate_msg(source, &reply, 20, 1);
            if (!result) {
                for (int i = 0; i < 20; ++i) ((unsigned char *)reply)[i] = 0;
                /* status 0 (success), lens type 0 (generic, in 0x1d mask), version 0 */
                real_set_source(reply, 0x912503d0);
                result = real_send_msg(source, reply);
                if (result) real_free_msg(source, reply);
            }
            snprintf(text, sizeof text, "tid=%ld reply=%d", syscall(178), result);
            record("LENS_VERSION_SERVICE ", result ? "reply delivery failed" :
                    "20-byte lens reply delivered: status 0, type 0, version 0");
            unsigned int from = lens_pool_lookup(message);
            real_free_msg(from ? from : 0x912503d0, message);
            return result;
        }
    }
    if (id == 0x912503d0 && getenv("QEMU_NO_CP_UPDATER")) {
        record("TRANSPORT_UNAVAILABLE ", "CP updater 0x912503d0; request not consumed");
        return -1021;
    }
    if (id == 0x9004015e && message) {
        const unsigned int *words = message; /* capidtbl requests are 24 bytes */
        char text[192];
        snprintf(text, sizeof text, "tid=%ld dest=%#x words=%#x,%#x,%#x,%#x,%#x,%#x caller=%p",
                 syscall(178), id, words[0], words[1], words[2], words[3], words[4], words[5],
                 __builtin_return_address(0));
        record("CAPID_SEND ", text);
        int result = real_send_msg(id, message);
        snprintf(text, sizeof text, "tid=%ld dest=%#x result=%d", syscall(178), id, result);
        record("CAPID_SEND_RETURN ", text);
        return result;
    }
    if (bb_ready_inject_enabled && bb_ready_pending && bb_key_seen && id != 0x811006e9) {
        bb_ready_pending = 0;
        record("BB_OUTPUT_READY ", "deferred fulfilment released after the key injection");
        bb_output_ready_event();
    }
    if (message && real_msg_size) {
        unsigned int size = real_msg_size(message);
        unsigned int code = size >= 4 ? ((const unsigned short *)message)[1] : 0;
        /* Known periodic noise: heartbeat/log-drain channels, plus the 0x20f keepalive on
           the model event queue (real key events on 0x5503e0 use code 0x1400 and stay visible). */
        if (id == 0x8f013a || id == 0x8f0139 || id == 0x92b4086f || (id == 0x5503e0 && code == 0x20f))
            return real_send_msg(id, message);
        char text[180];
        snprintf(text, sizeof text, "tid=%ld dest=%#x code=%#x bytes=%u source=%#x caller=%p",
                 syscall(178), id, code, size,
                 real_get_source ? real_get_source(message) : 0, __builtin_return_address(0));
        record("SND_MSG_OTHER ", text);
        /* Payload capture for unmapped CP-facing destinations (event registration probes). */
        if (id == 0x811006e9 || id == 0x80920871 || id == 0x80920572 || id == 0x807a0020 ||
            id == 0x7a804c || id == 0x7ae098 || id == 0x7ae118 || id == 0x5503e0) {
            const unsigned char *bytes = message;
            unsigned int shown = size < 24 ? size : 24;
            char hex[180];
            int at = 0;
            for (unsigned int i = 0; i < shown && at < 150; ++i) at += snprintf(hex + at, sizeof hex - at, "%02x", bytes[i]);
            snprintf(text, sizeof text, "tid=%ld dest=%#x code=%#x payload=%s", syscall(178), id, code, hex);
            record("SND_MSG_PAYLOAD ", text);
        }
    }
    unsigned int observed = record_osd_transport("OSD_TRANSPORT_SEND ", id, message);
    int result = real_send_msg(id, message);
    if (observed) {
        char text[96];
        snprintf(text, sizeof text, "call=%u endpoint=%#x result=%d", observed, id, result);
        record("OSD_TRANSPORT_SEND_RETURN ", text);
    }
    return result;
}
int kikilog_set_notify_cb(unsigned int id) {
    if (!real_kikilog_notify) __builtin_trap();
    int result = real_kikilog_notify(id);
    char text[64];
    snprintf(text, sizeof text, "id=%#x result=%d", id, result);
    record("KIKILOG_NOTIFY ", text);
    return result;
}
static void capture_gpe(unsigned int operation, int gpe, int core, const void *parameters, unsigned int bytes) {
    if (!parameters) return;
    unsigned int index = __atomic_fetch_add(&gpe_capture_count, 1, __ATOMIC_RELAXED);
    if (index >= 256) {
        if (index == 256) record("GPE_CAPTURE_LIMIT ", "first 256 requests; later requests still executed");
        return;
    }
    unsigned int buffer[40] = {operation, (unsigned int)gpe, (unsigned int)core, bytes};
    unsigned char *target = (unsigned char *)(buffer + 4);
    const unsigned char *source = parameters;
    for (unsigned int i = 0; i < bytes; ++i) target[i] = source[i];
    int fd = open("/tmp/gpe-requests.bin", 0x441, 0644);
    if (fd >= 0) { write(fd, buffer, bytes + 16); close(fd); }
    char text[64];
    snprintf(text, sizeof text, "op=%u gpe=%d core=%d bytes=%u", operation, gpe, core, bytes);
    record("GPE_REQUEST ", text);
    if (index < 256) {
        char hex[289];
        const char digits[] = "0123456789abcdef";
        for (unsigned int i = 0; i < bytes; ++i) { hex[i * 2] = digits[source[i] >> 4]; hex[i * 2 + 1] = digits[source[i] & 15]; }
        hex[bytes * 2] = 0;
        record("GPE_PARAMETERS ", hex);
    }
}
static int (*real_osd_set_entry)(void *, const void *);
static unsigned long headless_libobj;
static struct hosd_native headless_native;
static unsigned int headless_stop, headless_started, headless_thread_live;
static pthread_t headless_thread;
static int (*headless_join)(pthread_t, void **);
static int headless_try_raster(void) { return pthread_mutex_trylock(headless_raster_mutex); }
static int headless_unlock_raster(void) { return pthread_mutex_unlock(headless_raster_mutex); }
static int headless_frame(struct hosd_frame *frame, unsigned char *pixels) {
    return hosd_capture_frame(headless_libobj, &headless_native, frame, pixels);
}
/* The entry's first four verified instructions are PC-independent. */
static void *headless_fin_continue __attribute__((used));
__asm__(
".text\n"
".align 2\n"
".globl headless_fin_original\n"
".type headless_fin_original, %function\n"
"headless_fin_original:\n"
"stp x29,x30,[sp,#-48]!\n"
"mov w0,#0x4000\n"
"mov x29,sp\n"
"stp x19,x20,[sp,#16]\n"
"adrp x16,headless_fin_continue\n"
"ldr x16,[x16,#:lo12:headless_fin_continue]\n"
"br x16\n");
extern unsigned long headless_fin_original(void);
static unsigned long (*headless_finish)(void) = headless_fin_original;
static unsigned long observe_grm_fin(void) {
    /* Serialize both startup and actual teardown; no FB access can outlive join. */
    if (pthread_mutex_lock(headless_lifecycle_mutex)) return (unsigned long)-1;
    __atomic_store_n(&headless_stop, 1, __ATOMIC_RELEASE);
    if (headless_thread_live) {
        if (!headless_join || headless_join(headless_thread, 0)) {
            record("OSD_HEADLESS_FAILED ", "join failed; native grm_fin refused");
            pthread_mutex_unlock(headless_lifecycle_mutex);
            return (unsigned long)-1;
        }
        headless_thread_live = 0;
    }
    record("OSD_HEADLESS_JOINED ", "receiver exited before native grm_fin");
    unsigned long result = headless_finish();
    pthread_mutex_unlock(headless_lifecycle_mutex);
    return result;
}
static int install_headless_fin(unsigned long base) {
    unsigned int *entry = (unsigned int *)(base + 0xffd24);
    if (entry[0] != 0xa9bd7bfd || entry[1] != 0x52880000 || entry[2] != 0x910003fd || entry[3] != 0xa90153f3)
        return -1;
    void *page = (void *)((unsigned long)entry & ~4095UL);
    if (mprotect(page, 4096, 7)) return -1;
    headless_fin_continue = (void *)(base + 0xffd34);
    entry[0] = 0x58000050; entry[1] = 0xd61f0200;
    *(unsigned long *)(entry + 2) = (unsigned long)observe_grm_fin;
    clear_cache_range(entry, 16);
    return mprotect(page, 4096, 5);
}
static void start_headless_osd(void) {
    static struct hosd_ops ops;
    if (!headless_osd_enabled || !real_draw_framebuffer || !real_rcv_msg_tmo ||
        !real_msg_size || !real_get_source || !real_free_msg || !real_allocate_msg ||
        !real_set_source || !real_send_msg) return;
    if (pthread_mutex_lock(headless_lifecycle_mutex)) return;
    if (headless_started || headless_stop) { pthread_mutex_unlock(headless_lifecycle_mutex); return; }
    headless_started = 1;
    if (!software_rgba4444) { record("OSD_HEADLESS_FAILED ", "requires explicit software GPE RGBA4444 mode"); goto done; }
    int (*stat_queue)(unsigned int, unsigned int *) = real_dlsym((void *)-1, "osal_stat_msgq");
    if (hosd_claim("/tmp/headless-osd.claim", "/proc/modules", stat_queue, record)) {
        record("OSD_HEADLESS_FAILED ", "exclusive startup checks failed; receiver not started");
        goto done;
    }
    headless_libobj = (unsigned long)real_draw_framebuffer - 0x170910UL;
    ops = (struct hosd_ops){real_rcv_msg_tmo, real_msg_size, real_get_source, real_free_msg,
                           real_allocate_msg, real_set_source, real_send_msg, headless_frame, record, &headless_stop};
    unsigned long b = headless_libobj;
    headless_native = (struct hosd_native){
        real_dlsym((void *)-1, "osal_wai_sem_tmo"), real_dlsym((void *)-1, "osal_sig_sem"),
        (void *)(b + 0xefa78), (void *)(b + 0xef980), (void *)(b + 0xef9b8), (void *)(b + 0xefabc),
        (void *)(b + 0xef8f8), (void *)(b + 0xeff6c), (void *)(b + 0xef814), headless_try_raster, headless_unlock_raster, record};
    /* Resolve before creating the worker: it must never enter the loader lock. */
    int (*create)(pthread_t *, const void *, void *(*)(void *), void *) = real_dlsym((void *)-1, "pthread_create");
    headless_join = real_dlsym((void *)-1, "pthread_join");
    if (!headless_native.wait_sem || !headless_native.signal_sem || !create || !headless_join || install_headless_fin(b)) {
        record("OSD_HEADLESS_FAILED ", "native lease symbols/actual grm_fin entry hook unavailable"); goto done;
    }
    if (create(&headless_thread, 0, hosd_worker, &ops))
        record("OSD_HEADLESS_FAILED ", "pthread creation unavailable");
    else headless_thread_live = 1;
done:
    pthread_mutex_unlock(headless_lifecycle_mutex);
}
static unsigned int notify_draw_count, draw_framebuffer_count;
static void record_frame_call(const char *prefix, unsigned int count, void *object, unsigned long result) {
    if (count > 8) return;
    char text[192];
    snprintf(text, sizeof text, "call=%u tid=%ld this=%p result=%#lx update_state=%u draw_state=%u",
             count, syscall(178), object, result, *(unsigned int *)(appfw_base + 0x5c1efe4),
             *(unsigned int *)(appfw_base + 0x5c1efe0));
    record(prefix, text);
}
static unsigned long observe_notify_draw(void *object) {
    unsigned int count = __atomic_add_fetch(&notify_draw_count, 1, __ATOMIC_RELAXED);
    record_frame_call("FRAME_NOTIFY_ENTER ", count, object, 0);
    unsigned long result = real_notify_draw(object);
    record_frame_call("FRAME_NOTIFY_RETURN ", count, object, result);
    return result;
}
static void record_frame_buffers(unsigned int count) {
    if (count > 8) return;
    unsigned long base = (unsigned long)real_draw_framebuffer - 0x170910UL;
    unsigned long manager = *(unsigned long *)(base + 0x2ebde0UL);
    if (!manager) return;
    unsigned long fb = *(unsigned long *)(manager + 8);
    if (!fb) return;
    unsigned long on = *(unsigned long *)(fb + 0x68), off = *(unsigned long *)(fb + 0x70);
    if (!((on == fb + 0x20 && off == fb + 0x40) || (on == fb + 0x40 && off == fb + 0x20))) return;
    /* FrameBuffer::update copies desired width/height/format (+0x14) to current fields (+8). */
    char text[224];
    snprintf(text, sizeof text, "call=%u width=%u height=%u bmp_format=%u on=%#lx off=%#lx on_bitmap=%#lx off_bitmap=%#lx",
             count, *(unsigned short *)(fb + 8), *(unsigned short *)(fb + 10),
             *(unsigned int *)(fb + 12), *(unsigned long *)(on + 0x18),
             *(unsigned long *)(off + 0x18), *(unsigned long *)on, *(unsigned long *)off);
    record("FRAME_BUFFERS ", text);
}
static void record_frame_sync(unsigned int count) {
    if (count > 8) return;
    unsigned long base = (unsigned long)real_draw_framebuffer - 0x170910UL;
    unsigned long manager = *(unsigned long *)(base + 0x2ebde0UL);
    if (!manager) return;
    unsigned long fb = *(unsigned long *)(manager + 8);
    unsigned long ready = *(unsigned long *)(manager + 0x10), cb = *(unsigned long *)(manager + 0x48);
    unsigned long external = *(unsigned long *)(manager + 0x20);
    unsigned long gate = external ? *(unsigned long *)(external + 0x48) : 0;
    char text[320];
    snprintf(text, sizeof text, "call=%u manager=%#lx ready_obj=%#lx ready_id=%#x callback_obj=%#lx callback_id=%#x external=%#lx external_gate=%#lx external_id=%#x",
             count, manager, ready, ready ? *(unsigned int *)(ready + 8) : 0,
             cb, cb ? *(unsigned int *)(cb + 8) : 0, external, gate, gate ? *(unsigned int *)(gate + 8) : 0);
    record("FRAME_SYNC_OBJECTS ", text);
    if (fb) {
        snprintf(text, sizeof text, "call=%u framebuffer=%#lx fb80_id=%#x fb90_id=%#x mgr60=%u fb78=%u",
                 count, fb, *(unsigned int *)(fb + 0x88), *(unsigned int *)(fb + 0x98),
                 *(unsigned char *)(manager + 0x60), *(unsigned char *)(fb + 0x78));
        record("FRAME_SYNC_FLAGS ", text);
    }
    unsigned long native = *(unsigned long *)(base + 0x2ec900UL);
    if (native) {
        snprintf(text, sizeof text, "call=%u libobj=%#lx table=%#lx native18=%#lx native78=%#lx nativec8=%#lx",
                 count, base, native, *(unsigned long *)(native + 0x18),
                 *(unsigned long *)(native + 0x78), *(unsigned long *)(native + 0xc8));
        record("FRAME_NATIVE_TABLE ", text);
    }
}
static void try_apply_menu_after_frame(void) {
    static unsigned int attempted;
    if (!getenv("MENU_APPLY_MENU") || attempted || !captured_manager || !create_screen_returned || create_screen_active) return;
    if ((unsigned int)syscall(178) != ui_thread_id) return;
    attempted = 1;
    unsigned long manager = captured_manager;
    unsigned long controller = *(unsigned long *)(manager + 0x330);
    unsigned int current = *(unsigned int *)(manager + 0x348);
    unsigned int selector = *(unsigned int *)(appfw_base + 0x7ed79a8);
    unsigned int mirror = *(unsigned int *)(appfw_base + 0x83d9d00);
    unsigned long p30 = *(unsigned long *)(manager + 0x30), p10 = *(unsigned long *)(manager + 0x10);
    char text[224];
    if (*(unsigned long *)manager != appfw_base + 0x5b0c480UL || current != 0x308 ||
        controller != appfw_base + 0x7603190UL ||
        *(unsigned long *)controller != appfw_base + 0x5b0e298UL ||
        !p30 || !p10 ||
        selector > 2) {
        snprintf(text, sizeof text, "current=%#x controller=%#lx p30=%#lx p10=%#lx selector=%u mirror=%u",
                 current, controller, p30, p10, selector, mirror);
        record("MENU_APPLY_SKIPPED ", text);
        return;
    }
    snprintf(text, sizeof text, "tid=%u manager=%#lx current=%#x selector=%u mirror=%u boot_controller=%#lx",
             ui_thread_id, manager, current, selector, mirror, controller);
    record("MENU_APPLY_ENTER ", text);
    unsigned int from = 0x4b7, to = 0x346, restore = 0x4b7;
    /* Same nine-argument apply ABI as firmware boot; the final zero is a stack argument. */
    typedef void (*apply_t)(void *, const unsigned int *, const unsigned int *, const unsigned int *,
                            unsigned int, unsigned int, unsigned int, unsigned int, unsigned int);
    ((apply_t)(appfw_base + 0x1e78870))((void *)manager, &from, &to, &restore, 0, 1, 0, 0, 0);
    snprintf(text, sizeof text, "current=%#x controller=%#lx", *(unsigned int *)(manager + 0x348),
             *(unsigned long *)(manager + 0x330));
    record("MENU_APPLY_RETURN ", text);
}
static unsigned long observe_draw_framebuffer(void *object) {
    unsigned int count = __atomic_add_fetch(&draw_framebuffer_count, 1, __ATOMIC_RELAXED);
    record_frame_call("FRAME_DRAW_ENTER ", count, object, 0);
    record_frame_sync(count);
    unsigned long result = real_draw_framebuffer(object);
    record_frame_call("FRAME_DRAW_RETURN ", count, object, result);
    record_frame_buffers(count);
    try_apply_menu_after_frame();
    if (count == 9) record("FRAME_LOG_LIMIT ", "first 8 frame calls logged; all later calls forwarded");
    return result;
}
static void install_frame_observers(unsigned long base) {
    if (!getenv("MENU_FRAME_OBSERVE")) return;
    if (!real_notify_draw || !real_draw_framebuffer) {
        record("FRAME_PROBES_FAILED ", "libObj exports not captured before appFw init");
        return;
    }
    if (mprotect((void *)(base + 0x5bc2000), 4096, 3) != 0) {
        record("FRAME_PROBES_FAILED ", "appFw GOT page not writable");
        return;
    }
    *(unsigned long *)(base + 0x5bc2098) = (unsigned long)observe_notify_draw;
    *(unsigned long *)(base + 0x5bc2370) = (unsigned long)observe_draw_framebuffer;
    record("FRAME_PROBES_ARMED ", "verified appFw notifyDraw/drawFramebuffer import slots");
}
static int (*real_osd_pin_send)(void *, unsigned int, unsigned int, unsigned int);
static unsigned long (*real_lz_decode)(void *);
static unsigned int lz_decode_count;
static unsigned long osd_libobj_base;
static int (*real_resource_open)(const char *, int, ...);
static void *(*real_resource_fopen)(const char *, const char *);
extern int *__errno_location(void);
static unsigned int resource_open_count;
static void record_resource_open(const char *path, long result, int error) {
    if (!path || !(strstr(path, "image_") || strstr(path, "global.xdb") || strstr(path, ".ltt") ||
                  strstr(path, "fontlist") || strstr(path, "TEXTRM_FONT_LIST") || same_name(path, "/dev/ldec"))) return;
    unsigned int count = __atomic_add_fetch(&resource_open_count, 1, __ATOMIC_RELAXED);
    if (count <= 128) {
        char text[384];
        snprintf(text, sizeof text, "call=%u result=%ld errno=%d path=%.260s", count, result, error, path);
        record("RESOURCE_OPEN ", text);
    } else if (count == 129) record("RESOURCE_LOG_LIMIT ", "first 128 matching resource opens recorded");
}
static int observe_resource_open(const char *path, int flags, ...) {
    int result;
    if ((flags & 0x40) || (flags & 0x410000) == 0x410000) {
        __builtin_va_list args;
        __builtin_va_start(args, flags);
        unsigned int mode = __builtin_va_arg(args, unsigned int);
        __builtin_va_end(args);
        result = real_resource_open(path, flags, mode);
    } else result = real_resource_open(path, flags);
    int error = *__errno_location();
    record_resource_open(path, result, result < 0 ? error : 0);
    *__errno_location() = error;
    return result;
}
static void *observe_resource_fopen(const char *path, const char *mode) {
    void *result = real_resource_fopen(path, mode);
    int error = *__errno_location();
    record_resource_open(path, result ? 1 : -1, result ? 0 : error);
    *__errno_location() = error;
    return result;
}
static unsigned long software_lz_decode(void *object) {
    const unsigned char *p = object;
    if (!p || !osd_libobj_base) return 0;
    void *stream = *(void *const *)(p + 8), *image = *(void *const *)(p + 0x10);
    unsigned int format = *(const unsigned int *)(p + 0x18);
    unsigned int width = *(const unsigned short *)(p + 0x1c), height = *(const unsigned short *)(p + 0x1e);
    unsigned int input_size = *(const unsigned int *)(p + 0x20);
    unsigned int bpp = format == 1 ? 4 : format == 7 ? 2 : format == 8 ? 1 : 0;
    if (!stream || !image || !bpp || !width || !height || width > 8192 || height > 8192 ||
        !input_size || input_size > 0x1000000) {
        record("RESOURCE_LZ_CPU_FAIL ", "unsupported descriptor"); return 0;
    }
    unsigned long row_bytes = ((width + 15UL) & ~15UL) * bpp;
    unsigned long size = row_bytes * height;
    if (size > 0x1000000) { record("RESOURCE_LZ_CPU_FAIL ", "output exceeds bound"); return 0; }
    unsigned long table = *(unsigned long *)stream;
    if (!table || *(unsigned long *)(table + 0x58) != osd_libobj_base + 0x12f790UL) {
        record("RESOURCE_LZ_CPU_FAIL ", "input stream getter does not match verified pure getter"); return 0;
    }
    const unsigned char *input = *(const unsigned char *const *)((const unsigned char *)stream + 0x10);
    if (sony_lz77_decode(input, input_size, 0, size)) {
        record("RESOURCE_LZ_CPU_FAIL ", "compressed stream failed bounded validation"); return 0;
    }
    unsigned long image_table = *(unsigned long *)image;
    if (!image_table || !*(unsigned long *)(image_table + 0x58)) return 0;
    unsigned int stride = 0;
    typedef void *(*lock_t)(void *, unsigned int *);
    typedef void (*unlock_t)(void *);
    typedef void (*size_t_fn)(void *, unsigned short *, unsigned short *);
    void *output = ((lock_t)(osd_libobj_base + 0x12c8b0))(image, &stride);
    if (!output) { record("RESOURCE_LZ_CPU_FAIL ", "output bitmap not writable"); return 0; }
    unsigned short output_width = 0, output_height = 0;
    ((size_t_fn)*(unsigned long *)(image_table + 0x58))(image, &output_width, &output_height);
    int result = 5;
    if (stride == row_bytes && output_width >= width && output_height >= height)
        result = sony_lz77_decode(input, input_size, output, size);
    unsigned long nonzero = 0;
    if (!result) for (unsigned long i = 0; i < size; ++i) nonzero += ((const unsigned char *)output)[i] != 0;
    ((unlock_t)(osd_libobj_base + 0x12c8c8))(image);
    char text[224];
    snprintf(text, sizeof text, "format=%u width=%u height=%u input=%u output=%lu stride=%u bitmap=%ux%u nonzero=%lu result=%d",
             format, width, height, input_size, size, stride, output_width, output_height, nonzero, result);
    record(result ? "RESOURCE_LZ_CPU_FAIL " : "RESOURCE_LZ_CPU_OK ", text);
    return result == 0;
}
static unsigned long observe_lz_decode(void *object) {
    unsigned int count = __atomic_add_fetch(&lz_decode_count, 1, __ATOMIC_RELAXED);
    char text[256];
    if (count <= 64 && object) {
        const unsigned char *p = object;
        unsigned long stream = *(const unsigned long *)(p + 8);
        unsigned long table = stream ? *(const unsigned long *)stream : 0;
        unsigned long getter = table ? *(const unsigned long *)(table + 0x58) : 0;
        snprintf(text, sizeof text, "call=%u object=%p format=%u width=%u height=%u input_bytes=%u stream=%#lx getter=%#lx output=%p",
                 count, object, *(const unsigned int *)(p + 0x18), *(const unsigned short *)(p + 0x1c),
                 *(const unsigned short *)(p + 0x1e), *(const unsigned int *)(p + 0x20), stream, getter,
                 *(void *const *)(p + 0x10));
        record("RESOURCE_LZ_ENTER ", text);
    }
    unsigned long result = getenv("QEMU_SOFTWARE_LZ77") ? software_lz_decode(object) : real_lz_decode(object);
    int error = *__errno_location();
    if (count <= 64) {
        snprintf(text, sizeof text, "call=%u result=%#lx errno=%d", count, result, error);
        record("RESOURCE_LZ_RETURN ", text);
    } else if (count == 65) record("RESOURCE_LZ_LIMIT ", "first 64 decoder calls logged");
    *__errno_location() = error;
    return result;
}
static int (*real_osd_wait_sem)(unsigned int, unsigned int);
static int (*real_osd_signal_sem)(unsigned int);
static unsigned int osd_prepare_count, osd_send_count;
static unsigned int osd_wait_count, osd_signal_count;
static unsigned int frame_wait_count;
static int observe_osd_wait_sem(unsigned int id, unsigned int timeout) {
    unsigned long caller = (unsigned long)__builtin_return_address(0);
    int target = caller == osd_libobj_base + 0x100224;
    int frame_target = !target && __atomic_load_n(&draw_framebuffer_count, __ATOMIC_RELAXED) >= 2 &&
        timeout == 0xffffffffu && (unsigned int)syscall(178) == ui_thread_id;
    unsigned int count = target ? __atomic_add_fetch(&osd_wait_count, 1, __ATOMIC_RELAXED)
        : frame_target ? ++frame_wait_count : 0;
    int logged = (target && count <= 16) || (frame_target && count <= 128);
    char text[192];
    if (logged) {
        unsigned long parent = 0;
        if (caller == osd_libobj_base + 0x1027ac) {
            /* Verified Semaphore::lock saves x29/x30 in a 16-byte frame before this call. */
            unsigned long frame = (unsigned long)__builtin_frame_address(0);
            unsigned long upper = *(unsigned long *)frame;
            if (!(upper & 15) && upper > frame && upper - frame < 4096)
                parent = *(unsigned long *)(upper + 8);
        }
        snprintf(text, sizeof text, "call=%u tid=%ld sem=%#x timeout=%#x caller=libObj+%#lx parent=%#lx",
                 count, syscall(178), id, timeout, caller-osd_libobj_base, parent);
        record(target ? "OSD_WAIT_ENTER " : "FRAME_SEM_WAIT_ENTER ", text);
        if (frame_target && count <= 2) {
            typedef int (*stat_t)(unsigned int, unsigned int *);
            stat_t stat_msgq = (stat_t)real_dlsym((void *)-1, "osal_stat_msgq");
            /* Query only queues already used by the completed first-frame path. */
            const unsigned int queues[] = {0x8280074d, 0x8280084d, 0x8288076c};
            if (stat_msgq) for (unsigned int i = 0; i < 3; ++i) {
                unsigned int state[4] = {0, 0, 0, 0};
                int status = stat_msgq(queues[i], state);
                snprintf(text, sizeof text, "wait_call=%u endpoint=%#x result=%d state=%u,%u,%u,%u",
                         count, queues[i], status, state[0], state[1], state[2], state[3]);
                record("OSD_KERNEL_QUEUE ", text);
            }
        }
    }
    int result = real_osd_wait_sem(id, timeout);
    if (logged) {
        snprintf(text, sizeof text, "call=%u sem=%#x result=%d", count, id, result);
        record(target ? "OSD_WAIT_RETURN " : "FRAME_SEM_WAIT_RETURN ", text);
    }
    if (frame_target && count == 129) record("FRAME_SEM_LOG_LIMIT ", "first 128 UI-thread waits logged");
    return result;
}
static int observe_osd_signal_sem(unsigned int id) {
    int result = real_osd_signal_sem(id);
    if (osd_libobj_base && id == *(unsigned int *)(osd_libobj_base + 0x2ebe68)) {
        unsigned int count = __atomic_add_fetch(&osd_signal_count, 1, __ATOMIC_RELAXED);
        if (count <= 16) {
            char text[128];
            snprintf(text, sizeof text, "call=%u tid=%ld sem=%#x result=%d", count, syscall(178), id, result);
            record("OSD_WAIT_SIGNAL ", text);
        }
    }
    return result;
}
static int observe_osd_set_entry(void *stream, const void *entry) {
    unsigned int count = __atomic_add_fetch(&osd_prepare_count, 1, __ATOMIC_RELAXED);
    if (count <= 64 && entry) {
        const unsigned char *p = entry;
        char text[224];
        snprintf(text, sizeof text, "call=%u target=%u width=%u height=%u rt=%#lx be=%#lx",
                 count, *(const unsigned short *)(p + 0x20),
                 *(const unsigned short *)(p + 0x24), *(const unsigned short *)(p + 0x26),
                 *(const unsigned long *)(p + 0x48), *(const unsigned long *)(p + 0x58));
        record("OSD_PREPARE ", text);
    }
    int result = real_osd_set_entry(stream, entry);
    if (count <= 64) {
        char text[80];
        snprintf(text, sizeof text, "call=%u result=%d", count, result);
        record("OSD_PREPARE_RETURN ", text);
    }
    return result;
}
static int observe_osd_pin_send(void *pin, unsigned int a1, unsigned int a2, unsigned int a3) {
    unsigned int count = __atomic_add_fetch(&osd_send_count, 1, __ATOMIC_RELAXED);
    if (count <= 64 && pin) {
        const unsigned int *p = pin;
        char text[160];
        snprintf(text, sizeof text, "call=%u dest=%#x source=%#x state=%u args=%#x,%#x,%#x",
                 count, p[7], p[11], p[12], a1, a2, a3);
        record("OSD_SEND ", text);
    }
    int result = real_osd_pin_send(pin, a1, a2, a3);
    if (count <= 64) {
        char text[80];
        snprintf(text, sizeof text, "call=%u result=%d", count, result);
        record("OSD_SEND_RETURN ", text);
    }
    if (count == 65) record("OSD_LOG_LIMIT ", "first 64 sends logged; later calls still forwarded");
    return result;
}
static void install_osd_observers(void *handle) {
    if (osd_libobj_base) return;
    void *anchor = real_dlsym(handle, "GRM_screenGetOnBitmap");
    real_osd_set_entry = real_dlsym(handle, "_ZN27C_DataflowInfra_StdData_OSD25SetEntry_OsdImageSizeInfoEP34C_DataflowInfra_Entry_OsdImageSize");
    real_osd_pin_send = real_dlsym(handle, "_ZN16DataflowInfraPin4SendEjjj");
    if (!anchor || !real_osd_set_entry || !real_osd_pin_send) {
        record("OSD_PROBES_FAILED ", "required exports unresolved");
        return;
    }
    unsigned long base = (unsigned long)anchor - 0xf4674UL;
    /* JUMP_SLOT offsets verified with readelf on the original c0897d72 libObj.so. */
    if (mprotect((void *)(base + 0x266000), 8192, 3) != 0) {
        record("OSD_PROBES_FAILED ", "GOT pages not writable");
        return;
    }
    *(unsigned long *)(base + 0x266c70) = (unsigned long)observe_osd_set_entry;
    *(unsigned long *)(base + 0x267480) = (unsigned long)observe_osd_pin_send;
    osd_libobj_base = base;
    real_osd_wait_sem = real_dlsym(handle, "osal_wai_sem_tmo");
    real_osd_signal_sem = real_dlsym(handle, "osal_sig_sem");
    if (real_osd_wait_sem && real_osd_signal_sem) {
        *(unsigned long *)(base + 0x2661a0) = (unsigned long)observe_osd_wait_sem;
        *(unsigned long *)(base + 0x267498) = (unsigned long)observe_osd_signal_sem;
        record("OSD_WAIT_PROBES_ARMED ", "VDT submit wait at libObj+0x100220 and matching semaphore signals");
    } else record("OSD_WAIT_PROBES_FAILED ", "OSAL semaphore exports unresolved");
    real_resource_open = real_dlsym(handle, "open");
    real_resource_fopen = real_dlsym(handle, "fopen");
    if (real_resource_open && real_resource_fopen) {
        *(unsigned long *)(base + 0x266488) = (unsigned long)observe_resource_open;
        *(unsigned long *)(base + 0x266fe0) = (unsigned long)observe_resource_fopen;
        record("RESOURCE_PROBES_ARMED ", "libObj image bank/database/font opens; errno and return values preserved");
    }
    unsigned long *decode_slot = (unsigned long *)(base + 0x25fc90);
    if (*decode_slot == base + 0x156380 && mprotect((void *)(base + 0x25f000), 4096, 3) == 0) {
        real_lz_decode = (unsigned long (*)(void *))*decode_slot;
        *decode_slot = (unsigned long)observe_lz_decode;
        record("RESOURCE_LZ_PROBE_ARMED ", "verified Lz77Decoder::decodeImpl vtable slot");
    } else record("RESOURCE_LZ_PROBE_FAILED ", "decoder slot did not match original implementation");
    char text[144];
    snprintf(text, sizeof text, "libObj=%#lx set_entry=+0x266c70 pin_send=+0x267480", base);
    record("OSD_PROBES_ARMED ", text);
}
int software_draw_initialize(int gpe) {
    if (!software_gpe) return real_draw_initialize ? real_draw_initialize(gpe) : 5;
    if (gpe != 0) return 5;
    if (raster_fd < 0) raster_fd = open("/dev/mem", 2);
    if (software_rgba4444) record("GPE_RGBA_MODEL ", "opt-in straight RGBA4444/source-over/nearest model; hardware pixel equivalence unverified");
    record("GPE_SOFTWARE_INIT ", raster_fd >= 0 ? "physical bitmap access ready; hardware FIFO unused" : "bitmap access unavailable");
    return raster_fd >= 0 ? 0 : 5;
}
int software_gperm_initialize(const void *object) {
    if (!software_gpe) return real_gperm_initialize ? real_gperm_initialize(object) : 5;
    return object ? software_draw_initialize(((const int *)object)[2]) : 5;
}
static int raster_completion(unsigned int sequence, unsigned int source, const unsigned char *callback_info) {
    void (*callback)(const void *) = *(void (**)(const void *))callback_info;
    struct { unsigned int sequence, reserved; unsigned long argument; } info =
        {sequence, 0, *(const unsigned long *)(callback_info + 8)};
    if (callback) callback(&info);
    if (source) { int status = 0; if (!real_draw_complete || !real_draw_complete(source, &status, sizeof status)) return 5; }
    return 0;
}
int software_fill_worker(int gpe, int core, unsigned int sequence, unsigned int source, const void *parameters) {
    if (!software_gpe) return real_worker_fill ? real_worker_fill(gpe, core, sequence, source, parameters) : 5;
    int previous_failure = raster_failed;
    raster_failed = 1;
    if (!parameters || gpe != 0 || core != 0 || raster_fd < 0) return 5;
    const unsigned int *p = parameters;
    unsigned long long address = *(const unsigned long long *)parameters;
    size_t bytes = ((size_t)p[3] + p[5]) * p[6] * (p[7] ? 4 : 2);
    if (address < 0x410000000ULL || address >= 0x500000000ULL || !bytes || bytes > 0x4000000 ||
        bytes > 0x500000000ULL - address) return 5;
    unsigned long base = address & ~4095ULL;
    size_t offset = address - base, length = (offset + bytes + 4095) & ~4095UL;
    if (pthread_mutex_lock(headless_raster_mutex)) return 5;
    void *mapped = mmap(0, length, 3, 1, raster_fd, base);
    if (mapped == (void *)-1) { pthread_mutex_unlock(headless_raster_mutex); return 5; }
    int result = gpe_uniform_fill((unsigned char *)mapped + offset, bytes, p);
    if (result && software_rgba4444) result = gpe_fill_rgba4444((unsigned char *)mapped + offset, bytes, p);
    if (munmap(mapped, length)) result = 5;
    if (pthread_mutex_unlock(headless_raster_mutex)) result = 5;
    char text[180];
    snprintf(text, sizeof text, "sequence=%u address=%#llx bytes=%lu width=%u height=%u format=%u result=%d",
             sequence, address, bytes, p[4], p[5], p[7], result);
    record("GPE_SOFTWARE_FILL ", text);
    if (result) { raster_failed = 1; return result; }
    const unsigned char *raw = parameters;
    result = raster_completion(sequence, source, raw + 0x28);
    raster_failed = result ? 1 : previous_failure;
    return result;
}
int software_blit_worker(int gpe, int core, unsigned int sequence, unsigned int source, const void *parameters) {
    if (!software_gpe) return real_worker_blit ? real_worker_blit(gpe, core, sequence, source, parameters) : 5;
    capture_gpe(1, gpe, core, parameters, 0x90);
    int previous_failure = raster_failed;
    raster_failed = 1;
    if (!parameters || gpe != 0 || core != 0 || raster_fd < 0) return 5;
    const unsigned char *raw = parameters;
    struct gpe_copy_plan plan;
    struct gpe_sprite_plan sprite;
    int use_sprite = 0;
    /* Non-null callbacks need the deferred command-5 FIFO; libObj's verified path uses NULL. */
    if (*(const unsigned long *)(raw + 0x80)) {
        record("GPE_SOFTWARE_UNSUPPORTED ", "deferred non-null callback is not implemented");
        return 5;
    }
    if (gpe_plan_copy(parameters, &plan)) {
        if (!software_rgba4444 || gpe_plan_sprite(parameters, &sprite)) {
            record("GPE_SOFTWARE_UNSUPPORTED ", "BitBlit outside supported copy or opt-in sprite subset");
            return 5;
        }
        plan = sprite.memory;
        use_sprite = 1;
    }
    if (!raw[0x7a] && !source) return 5;
    if (!plan.rows) {
        int result = raster_completion(sequence, source, raw + 0x80);
        raster_failed = result ? 1 : previous_failure;
        return result;
    }
    unsigned long dst_base = plan.destination & ~4095ULL, src_base = plan.source & ~4095ULL;
    unsigned long dst_offset = plan.destination - dst_base, src_offset = plan.source - src_base;
    unsigned long dst_length = (dst_offset + plan.destination_span + 4095) & ~4095UL;
    unsigned long src_length = (src_offset + plan.source_span + 4095) & ~4095UL;
    if (pthread_mutex_lock(headless_raster_mutex)) return 5;
    void *dst = mmap(0, dst_length, 3, 1, raster_fd, dst_base);
    if (dst == (void *)-1) { pthread_mutex_unlock(headless_raster_mutex); return 5; }
    void *src = mmap(0, src_length, 1, 1, raster_fd, src_base);
    if (src == (void *)-1) { munmap(dst, dst_length); pthread_mutex_unlock(headless_raster_mutex); return 5; }
    int result = use_sprite
        ? gpe_draw_sprite((unsigned char *)dst + dst_offset, plan.destination_span,
                          (const unsigned char *)src + src_offset, plan.source_span, &sprite)
        : gpe_copy_rows((unsigned char *)dst + dst_offset, plan.destination_span,
                        (const unsigned char *)src + src_offset, plan.source_span, &plan);
    if (munmap(src, src_length)) result = 5;
    if (munmap(dst, dst_length)) result = 5;
    if (pthread_mutex_unlock(headless_raster_mutex)) result = 5;
    char text[192];
    snprintf(text, sizeof text, "sequence=%u src=%#llx dst=%#llx rows=%u line=%lu result=%d",
             sequence, plan.source, plan.destination, plan.rows, plan.line, result);
    record(use_sprite ? "GPE_SOFTWARE_SPRITE_APPROX " : "GPE_SOFTWARE_COPY ", text);
    if (result) return result;
    result = raster_completion(sequence, source, raw + 0x80);
    raster_failed = result ? 1 : previous_failure;
    return result;
}
int software_flush_worker(int gpe, int core, unsigned int sequence, unsigned int source, const void *parameters) {
    if (!software_gpe) return real_worker_flush ? real_worker_flush(gpe, core, sequence, source, parameters) : 5;
    if (!parameters || gpe != 0 || core != 0 || raster_fd < 0 || raster_failed) return 5;
    /* The original worker FIFO has already executed all prior CPU operations. */
    record("GPE_SOFTWARE_FLUSH ", "prior raster writes finished; using original callback/SID completion format");
    return raster_completion(sequence, source, (const unsigned char *)parameters + 8);
}
int observe_gpe_fill(int gpe, int core, unsigned int *sequence, const void *parameters) {
    if (!real_gpe_fill) __builtin_trap();
    capture_gpe(0, gpe, core, parameters, 0x38);
    return real_gpe_fill(gpe, core, sequence, parameters);
}
int observe_gpe_blit(int gpe, int core, unsigned int *sequence, const void *parameters) {
    if (!real_gpe_blit) __builtin_trap();
    capture_gpe(1, gpe, core, parameters, 0x90);
    return real_gpe_blit(gpe, core, sequence, parameters);
}
#include "a7r5-model-trace.inc"
#include "a7r5-input-trace.inc"
#include "a7r5-gui.inc"

/* 仅用于无蓝牙虚拟后端的实验；原厂 ELF 文件保持不变。 */
static void patch_a7r5_bluetooth(void *symbol) {
    Dl_info info;
    if (!real_dladdr || !real_dladdr(symbol, &info) ||
        (unsigned long)symbol - (unsigned long)info.dli_fbase != 0x17feac0UL) {
        record("A7R5_PATCH_FAILED ", "Application_System_Init anchor mismatch");
        __builtin_trap();
    }
    unsigned int *entry = (unsigned int *)((unsigned long)info.dli_fbase + 0x35051bcUL);
    if (*entry != 0xa9bf7bfdU || mprotect((void *)((unsigned long)entry & ~4095UL), 4096, 7)) {
        record("A7R5_PATCH_FAILED ", "Bluetooth initializer fingerprint/mprotect mismatch");
        __builtin_trap();
    }
    *entry = 0xd65f03c0U;
    clear_cache_range(entry, 4);
    if (mprotect((void *)((unsigned long)entry & ~4095UL), 4096, 5)) __builtin_trap();
    record("A7R5_BT_WRAPPER_SKIPPED ", "only Bluetooth unit 0x35051bc; shared init 0x351e58c retained");
}

void *dlsym(void *handle, const char *name) {
    if (!real_dlsym) initialize();
    void *symbol = real_dlsym(handle, name);
    record(symbol ? "RESOLVED " : "NO_SYMBOL ", name);
    if (symbol && same_name(name, "Application_System_Init")) {
        if (getenv("A7R5_SKIP_BT_WRAPPER")) patch_a7r5_bluetooth(symbol);
        if (getenv("A7R5_MODEL_TRACE")) { Dl_info i; if (!real_dladdr(symbol, &i)) __builtin_trap(); a7r5_trace_install((unsigned long)i.dli_fbase); }
        if (getenv("A7R5_GUI_TRACE")) { Dl_info i; if (!real_dladdr(symbol, &i)) __builtin_trap(); appfw_base=(unsigned long)i.dli_fbase; a7r5_gui_install(appfw_base); }
        record("A7R5_ORIGINAL_APP_INIT ", "passthrough; no A7C2 address hooks");
        return symbol;
    }
    if (symbol && same_name(name, "udtr_ufp_init")) {
        real_updater_init = symbol;
        return observe_updater_init;
    }
    if (symbol && same_name(name, "udtr_ufp_exit")) {
        real_updater_exit = symbol;
        return observe_updater_exit;
    }
    if (symbol && same_name(name, "osal_dynamic_id")) {
        real_dynamic_id = symbol;
        return osal_dynamic_id;
    }
    if (symbol && same_name(name, "osal_reg_sync_msg_queue_cb")) {
        real_reg_sync = symbol;
        return osal_reg_sync_msg_queue_cb;
    }
    if (symbol && same_name(name, "osal_snd_msg")) {
        real_send_msg = symbol;
        return osal_snd_msg;
    }
    if (symbol && same_name(name, "osal_valloc_msg_wait")) {
        real_allocate_msg = symbol;
        return osal_valloc_msg_wait;
    }
    if (symbol && same_name(name, "osal_free_msg")) {
        real_free_msg = symbol;
        return osal_free_msg;
    }
    if (symbol && same_name(name, "osal_snd_sync_msg")) {
        real_send_sync = symbol;
        return osal_snd_sync_msg;
    }
    if (symbol && same_name(name, "osal_snd_sync_direct") && 0) {
        real_send_sync_direct = symbol;
    }
    if (symbol && same_name(name, "kikilog_set_notify_cb")) {
        real_kikilog_notify = symbol;
        return kikilog_set_notify_cb;
    }
    if (symbol && same_name(name, "_ZN5mpgpe13GpermFillRectENS_3GpeENS_7IntCoreEPjRKNS_13FillRectParamE")) {
        real_gpe_fill = symbol;
        return observe_gpe_fill;
    }
    if (symbol && same_name(name, "_ZN5mpgpe12GpermBitBlitENS_3GpeENS_7IntCoreEPjRKNS_12BitBlitParamE")) {
        real_gpe_blit = symbol;
        return observe_gpe_blit;
    }
    return symbol;
}
int pthread_attr_setschedpolicy(void *attr, int policy) {
    if (!real_attr_policy) initialize();
    (void)policy;
    return real_attr_policy(attr, 0);
}
int pthread_attr_setschedparam(void *attr, const void *parameter) {
    if (!real_attr_param) initialize();
    int normal_priority = 0;
    (void)parameter;
    return real_attr_param(attr, &normal_priority);
}
int pthread_setschedparam(pthread_t thread, int policy, const void *parameter) {
    if (!real_thread_param) initialize();
    int normal_priority = 0;
    (void)policy; (void)parameter;
    return real_thread_param(thread, 0, &normal_priority);
}
int sched_setscheduler(int pid, int policy, const void *parameter) {
    if (!real_scheduler) initialize();
    int normal_priority = 0;
    (void)policy; (void)parameter;
    return real_scheduler(pid, 0, &normal_priority);
}
