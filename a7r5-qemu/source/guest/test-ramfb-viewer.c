#define RAMFB_TEST
#include "ramfb-viewer.c"
#include <assert.h>
#include <stdlib.h>

static unsigned char frame[HOSD_BYTES], raw[HOSD_BYTES], output[XRGB_BYTES];
static void putle(unsigned char *p, uint64_t v, unsigned n) {
    for (unsigned i = 0; i < n; ++i) { p[i] = v; v >>= 8; }
}
static void checksum(void) { putle(frame + 40, fnv(frame, sizeof frame, 1), 8); }
static void fixture(unsigned seq, unsigned source, unsigned cmd) {
    memset(frame, 0, sizeof frame); memcpy(frame, "HOSDAP02", 8);
    putle(frame + 8, seq, 8); putle(frame + 16, 7, 4);
    putle(frame + 20, 640, 4); putle(frame + 24, 480, 4); putle(frame + 28, 1, 4);
    putle(frame + 32, UINT64_C(0x43a7b4100), 8);
    putle(frame + 48, HOSD_PIXELS, 4); putle(frame + 52, sizeof(struct hosd_metadata), 4);
    putle(frame + 56, cmd, 4); putle(frame + 64, 0x1003, 2); putle(frame + 72, 7, 4);
    putle(frame + 84, 640, 2); putle(frame + 86, 480, 2);
    putle(frame + 100, 0x1002, 2); putle(frame + 108, cmd, 4);
    if (cmd == 0x1005) putle(frame + 112, cmd, 2);
    putle(frame + 120, source, 8); checksum();
}
static void save(const char *path) {
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0600); assert(fd >= 0);
    assert(write(fd, frame, sizeof frame) == sizeof frame); assert(!close(fd));
}
struct mock {
    unsigned select, offset, count, kicks, sleeps, mode;
    unsigned char directory[68], id[4], sig[4];
    unsigned char *pool;
};
static void select_key(void *ctx, uint16_t sel) { struct mock *m=ctx; m->select=sel; m->offset=0; }
static unsigned char data_byte(void *ctx) {
    struct mock *m=ctx;
    unsigned i=m->offset++;
    if (m->select == 0) { assert(i < 4); return m->sig[i]; }
    if (m->select == 1) { assert(i < 4); return m->id[i]; }
    assert(m->select == 0x19 && i < sizeof m->directory); return m->directory[i];
}
static uint64_t signature(void *ctx) { (void)ctx; return UINT64_C(0x51454d5520434647); }
static void kick(void *ctx, uint64_t addr) {
    struct mock *m=ctx; ++m->kicks; assert(addr == RAMFB_BASE + RAMFB_DMA);
    if (m->mode != 2) putbe(m->pool + RAMFB_DMA, m->mode, 4);
}
static void pause_bus(void *ctx) { ++((struct mock *)ctx)->sleeps; }
int main(void) {
    assert(reserved("x=1 memrsv=0x00500000@0x41e100000:uc y=2"));
    assert(!reserved("xmemrsv=0x00500000@0x41e100000:uc"));
    assert(!reserved("memrsv=0x00500000@0x41e100000:ucbroken"));
    fixture(1, 1, 0x1003); assert(!validate(frame, sizeof frame));
    assert(validate(frame, sizeof frame - 1)); assert(validate(frame, sizeof frame + 1));
    const unsigned offsets[] = {0, 20, 24, 28, 48, 52, 64, 72, 80, 84, 86, 100, 108, 120};
    for (unsigned i=0; i<sizeof offsets/sizeof *offsets; ++i) {
        fixture(1,1,0x1003); frame[offsets[i]] ^= 0x80; checksum(); assert(validate(frame,sizeof frame));
    }
    fixture(1,1,0x1003); frame[sizeof frame - 1] ^= 1; assert(validate(frame,sizeof frame));
    fixture(1,1,0x1003); putle(frame+32, UINT64_C(0x410000000)-1,8); checksum(); assert(validate(frame,sizeof frame));
    putle(frame+32, UINT64_C(0x500000000)-HOSD_PIXELS+1,8); checksum(); assert(validate(frame,sizeof frame));
    putle(frame+32, UINT64_C(0x500000000)-HOSD_PIXELS,8); checksum(); assert(!validate(frame,sizeof frame));
    fixture(2,1,0x1005); frame[112]=0; checksum(); assert(validate(frame,sizeof frame));
    fixture(1,1,0x1003);
    unsigned char *pixels=frame+HOSD_HEADER+sizeof(struct hosd_metadata);
    const unsigned colors[]={0xf00f,0x0f0f,0x00ff,0xffff,0xfff0,0xf008,0x123f};
    const unsigned char expected[]={0,0,255,0, 0,255,0,0, 255,0,0,0, 255,255,255,0,
                                    0,0,0,0, 0,0,136,0, 51,34,17,0};
    for(unsigned i=0;i<7;++i) putle(pixels+2*i,colors[i],2);
    convert(pixels,output); assert(!memcmp(output,expected,sizeof expected));
    struct mock m={.id={3},.sig={'Q','E','M','U'}};
    m.pool=calloc(1,RAMFB_SIZE); assert(m.pool);
    putbe(m.directory,1,4); putbe(m.directory+4,28,4); putbe(m.directory+8,0x24,2);
    memcpy(m.directory+12,"etc/ramfb",10);
    struct bus b={&m,select_key,data_byte,signature,kick,pause_bus};
    assert(discover(&b)==0x24); m.sig[0]='X'; assert(discover(&b)<0); m.sig[0]='Q';
    m.id[0]=1; assert(discover(&b)<0); m.id[0]=3;
    putbe(m.directory,257,4); assert(discover(&b)<0); putbe(m.directory,1,4);
    putbe(m.directory+4,27,4); assert(discover(&b)<0); putbe(m.directory+4,28,4);
    assert(!config(m.pool+RAMFB_CFG,m.pool+RAMFB_DMA,1,0x24));
    const unsigned char cfg[]={0,0,0,4,0x1e,0x30,0,0, 0x34,0x32,0x52,0x58,
                              0,0,0,0, 0,0,2,0x80, 0,0,1,0xe0, 0,0,0xa,0};
    const unsigned char dma[]={0,0x24,0,0x18, 0,0,0,28, 0,0,0,4,0x1e,0x5f,0xf0,0x40};
    assert(!memcmp(m.pool+RAMFB_CFG,cfg,28)); assert(!memcmp(m.pool+RAMFB_DMA,dma,16));
    assert(config(m.pool,m.pool+64,2,0x24)); assert(config(m.pool,m.pool+64,0,0x4000));
    assert(!submit(&b,m.pool,0,0x24) && m.kicks==1 && !m.sleeps);
    m.mode=1; assert(submit(&b,m.pool,1,0x24)==-1);
    m.mode=2; assert(submit(&b,m.pool,1,0x24)==-2 && m.sleeps==100);
    free(m.pool);

    char directory[]="/tmp/ramfb-test-XXXXXX"; assert(mkdtemp(directory));
    char path[128], replacement[128];
    snprintf(path,sizeof path,"%s/frame",directory); snprintf(replacement,sizeof replacement,"%s/new",directory);
    fixture(1,1,0x1003); save(path);
    int fd=open(path,O_RDONLY); assert(fd>=0);
    /* Replace pathname between open and read: all bytes must remain old inode's. */
    frame[0]='X'; save(replacement); assert(!rename(replacement,path));
    struct consumer s={.fd=-1}; struct stat st; const char *err=NULL;
    assert(snapshot(&s,fd,raw,&st,&err)==2); commit(&s,fd,&st,raw);
    int other=open(path,O_RDONLY); assert(other>=0);
    assert(snapshot(&s,other,raw,&st,&err)<0); close(other);
    fixture(2,1,0x1005); save(replacement); assert(!rename(replacement,path));
    other=open(path,O_RDONLY); assert(other>=0);
    assert(snapshot(&s,other,raw,&st,&err)==1); commit(&s,other,&st,raw);
    other=open(path,O_RDONLY); assert(other>=0);
    assert(snapshot(&s,other,raw,&st,&err)==0);
    assert(lseek(other,0,SEEK_CUR)==HOSD_HEADER); close(other);
    fixture(3,1,0x1005); pixels[0]=1; checksum(); save(replacement); assert(!rename(replacement,path));
    other=open(path,O_RDONLY); assert(snapshot(&s,other,raw,&st,&err)<0); close(other);
    fixture(3,1,0x1005); frame[HOSD_HEADER]^=1; save(replacement); assert(!rename(replacement,path));
    other=open(path,O_RDONLY); assert(snapshot(&s,other,raw,&st,&err)<0); close(other);
    fixture(1,1,0x1003); save(replacement); assert(!rename(replacement,path));
    other=open(path,O_RDONLY); assert(snapshot(&s,other,raw,&st,&err)<0); close(other);
    fixture(3,3,0x1003); save(replacement); assert(!rename(replacement,path));
    other=open(path,O_RDONLY); assert(snapshot(&s,other,raw,&st,&err)==2); commit(&s,other,&st,raw);
    /* A valid all-black new source is still submitted. */
    convert(raw+HOSD_HEADER+sizeof(struct hosd_metadata),output);
    for(unsigned i=0;i<sizeof output;++i) assert(output[i]==0);
    close(s.fd); assert(!unlink(path)); assert(!rmdir(directory));
    static const char result[]="RAMFB_TEST_PASS: parser, alpha/colors, BE config/DMA, error/timeout, inode and retained-source policy (mock MMIO only)\n";
    assert(write(1,result,sizeof result-1)==sizeof result-1);
    return 0;
}
#ifdef RAMFB_FIRMWARE_TEST
void _start(void) { _exit(main()); }
#endif
