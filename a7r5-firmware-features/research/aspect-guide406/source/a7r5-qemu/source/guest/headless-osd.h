#ifndef HEADLESS_OSD_H
#define HEADLESS_OSD_H
/* AP software consumer, experimental RGBA4444 only; no CP compositor or panel. */
#define HOSD_CONTROL 0x8280074dU
#define HOSD_UPDATE 0x8280084dU
#define HOSD_META_UPDATE 0x8280084eU
#define HOSD_AP 0x8288076cU
#define HOSD_GUI 0x9088076bU
#define HOSD_PIXELS (640U * 480U * 2U)
#define HOSD_HEADER 128U
#ifndef HOSD_PATH
#define HOSD_PATH "/tmp/headless-osd-frame.bin"
#endif
#define HOSD_TIMEOUT (-1022)
#define HOSD_IDLE_MS 1000L
#define HOSD_PAIR_MS 5000L
struct hosd_metadata {
    unsigned char gui[80], widgets[256][96], extra[16], present[258];
};
#define HOSD_BYTES (HOSD_HEADER + sizeof(struct hosd_metadata) + HOSD_PIXELS)
struct hosd_frame {
    unsigned int id, width, height, format;
    unsigned long physical;
};
struct hosd_state {
    struct hosd_metadata working, frozen;
    unsigned char fix[12], descriptor[36], update[8];
    unsigned int pending, have_descriptor, failed;
    unsigned long sequence, pixel_source_seq;
    const char *phase;
    struct hosd_frame retained_frame;
    unsigned char retained_descriptor[36], retained_pixels[HOSD_PIXELS];
};
struct hosd_ops {
    int (*receive)(unsigned int, void **, long);
    unsigned int (*size)(void *), (*source)(void *);
    int (*release)(unsigned int, void *);
    int (*allocate)(unsigned int, void **, unsigned int, unsigned int);
    void (*set_source)(void *, unsigned int);
    int (*send)(unsigned int, void *);
    int (*frame)(struct hosd_frame *, unsigned char *);
    void (*log)(const char *, const char *);
    const unsigned int *stop;
};
struct hosd_native {
    int (*wait_sem)(unsigned int, unsigned int), (*signal_sem)(unsigned int);
    int (*addref)(void *), (*read_lock)(void *, int, const void **);
    int (*read_unlock)(void *), (*release)(void *);
    int (*physical)(void *, unsigned long *), (*row_pixels)(void *, short *), (*size)(void *, unsigned long *);
    int (*try_raster)(void), (*unlock_raster)(void);
    void (*log)(const char *, const char *);
};
/* frame contains the request ID/geometry on entry, captured identity on success. */
int hosd_capture_frame(unsigned long, const struct hosd_native *, struct hosd_frame *, unsigned char *);
unsigned long hosd_hash(const unsigned char *, unsigned long);
/* A failed transaction poisons the consumer: never acknowledge later incomplete state. */
int hosd_step(struct hosd_state *, const struct hosd_ops *, const char *);
void *hosd_worker(void *);
/* Diagnostic reader only; identity checks do not replace a producer-obeyed read lease. */
int hosd_read_frame(unsigned long libobj_base, struct hosd_frame *, unsigned char *);
int hosd_persist(const char *, const unsigned char *, unsigned long);
/* A once-per-boot claim, deliberately not removed on failure/process exit. */
int hosd_claim(const char *path, const char *modules,
               int (*stat_queue)(unsigned int, unsigned int *), void (*log)(const char *, const char *));
#endif
