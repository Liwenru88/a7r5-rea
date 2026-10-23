/* Standalone original-Fsys test. This is not a camera capture/encoder implementation. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <sys/mman.h>
#include <dlfcn.h>

#define IMAGE_BYTES 0x400000U
#define EXPORT_PHYS UINT64_C(0x41e600000)
extern void mcmn_init(void);
extern uint32_t mcmn_param_getul(int32_t);
extern int32_t mcmn_param_getl(int32_t);
extern int32_t Fsys_Init(void);
extern int32_t Fsys_Mount(const char *, uint32_t, char *, const void *);
extern int32_t Fsys_Mkdir(const char *);
extern int32_t Fsys_Open(const char *, uint64_t *, uint32_t);
extern int32_t Fsys_Write(uint64_t, const void *, int32_t);
extern int32_t Fsys_Read(uint64_t, void *, int32_t);
extern int32_t Fsys_Flush(uint64_t);
extern int32_t Fsys_Close(uint64_t);
extern int32_t Fsys_Unmount(unsigned char, uint32_t);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");

static void require_zero(const char *operation, int32_t result) {
    printf("FSYS_CALL %s result=%#x\n", operation, (uint32_t)result); fflush(0);
    if (result) _exit(10);
}
static int export_image(void) {
    char cmdline[8192];
    int fd = open("/proc/cmdline", O_RDONLY);
    if (fd < 0) return 1;
    ssize_t n = read(fd, cmdline, sizeof cmdline - 1); close(fd);
    if (n <= 0) return 1;
    cmdline[n] = 0;
    if (!strstr(cmdline, " memrsv=0x00400000@0x41e600000:uc ")) return 1;
    fd = open("/image_mmca", O_RDONLY);
    if (fd < 0 || lseek(fd, 0, SEEK_END) != IMAGE_BYTES || lseek(fd, 0, SEEK_SET)) {
        if (fd >= 0) close(fd);
        return 1;
    }
    int memory = open("/dev/mem", O_RDWR);
    if (memory < 0) { close(fd); return 1; }
    unsigned char *mapped = mmap(0, IMAGE_BYTES, PROT_READ | PROT_WRITE, MAP_SHARED, memory, EXPORT_PHYS);
    close(memory);
    if (mapped == MAP_FAILED) { close(fd); return 1; }
    unsigned total = 0;
    while (total < IMAGE_BYTES) {
        n = read(fd, mapped + total, IMAGE_BYTES - total);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        total += n;
    }
    close(fd);
    uint64_t hash = UINT64_C(14695981039346656037);
    for (unsigned i = 0; i < total; i++) hash = (hash ^ mapped[i]) * UINT64_C(1099511628211);
    __sync_synchronize();
    munmap(mapped, IMAGE_BYTES);
    if (total != IMAGE_BYTES) return 1;
    printf("FSYS_IMAGE_EXPORTED physical=0x%llx bytes=%u fnv1a64=%016llx\n",
           (unsigned long long)EXPORT_PHYS, total, (unsigned long long)hash);
    fflush(0);
    return 0;
}
static int run(int argc, char **argv) {
    int verify_only = argc == 2 && !strcmp(argv[1], "verify");
    int photos = argc == 2 && !strcmp(argv[1], "photos");
    if (argc > 2 || (argc == 2 && !verify_only && !photos)) return 2;
    unsigned (*configured)(void) = dlsym(RTLD_DEFAULT, "file_media_configured");
    if (!configured) return 3;
    printf("FSYS_FILE_TEST_BEGIN verify_only=%d\n", verify_only); fflush(0);
    mcmn_init();
    if (configured() != 1 || mcmn_param_getul(0x69) || mcmn_param_getul(0xf9)) return 4;
    for (int id = 0xa5; id <= 0xad; id++) if (mcmn_param_getl(id)) return 5;
    for (int id = 0xba; id <= 0xc2; id++) if (mcmn_param_getul(id)) return 6;
    require_zero("Init", Fsys_Init());
    char drive = 0, directory[32], path[64];
    require_zero("Mount", Fsys_Mount("/dev/mmca", 0, &drive, 0));
    if (drive < 'A' || drive > 'Z') return 7;
    if (photos) {
        /* 只读固定生成的测试 JPEG；消费原厂 Fsys 字节，不宣称原厂图像解码。 */
        for (unsigned index=1;index<=2;index++) {
            snprintf(path,sizeof path,"%c:/DCIM/100MSDCF/DSC0000%u.JPG",drive,index);
            uint64_t handle=0,hash=UINT64_C(14695981039346656037);unsigned total=0;
            unsigned char data[4096];
            require_zero("PhotoOpen",Fsys_Open(path,&handle,1));
            for (;;) {
                int n=Fsys_Read(handle,data,sizeof data);
                if (n<0 || total+(unsigned)n>0x100000U) return 12;
                if (!n)break;
                for (int j=0;j<n;j++)hash=(hash^data[j])*UINT64_C(1099511628211);
                total+=(unsigned)n;
            }
            require_zero("PhotoClose",Fsys_Close(handle));
            printf("FSYS_PHOTO_READ index=%u bytes=%u fnv1a64=%016llx\n",index,total,(unsigned long long)hash);fflush(0);
        }
        require_zero("PhotoUnmount",Fsys_Unmount((unsigned char)drive,0));
        printf("FSYS_PHOTO_READ_DONE\n");fflush(0);return 0;
    }
    snprintf(directory, sizeof directory, "%c:/QTEST", drive);
    snprintf(path, sizeof path, "%c:/QTEST/PROBE.BIN", drive);
    unsigned char expected[4096], got[4096];
    for (unsigned i = 0; i < sizeof expected; i++) expected[i] = (i * 37U + 9U) & 255U;
    uint64_t handle = 0;
    if (!verify_only) {
        require_zero("Mkdir", Fsys_Mkdir(directory));
        require_zero("OpenWrite", Fsys_Open(path, &handle, 0xf));
        int32_t bytes = Fsys_Write(handle, expected, sizeof expected);
        printf("FSYS_WRITE actual=%d expected=%u\n", bytes, (unsigned)sizeof expected); fflush(0);
        if (bytes != sizeof expected) return 8;
        require_zero("Flush", Fsys_Flush(handle));
        require_zero("CloseWrite", Fsys_Close(handle));
    }
    require_zero("OpenRead", Fsys_Open(path, &handle, 1));
    int32_t bytes = Fsys_Read(handle, got, sizeof got);
    if (bytes != sizeof got || memcmp(expected, got, sizeof got)) return 9;
    require_zero("CloseRead", Fsys_Close(handle));
    require_zero("Unmount", Fsys_Unmount((unsigned char)drive, 0));
    printf("FSYS_FILE_CONTENT_PASS bytes=%u verify_only=%d\n", (unsigned)sizeof got, verify_only); fflush(0);
    if (verify_only && export_image()) return 11;
    printf("FSYS_FILE_TEST_DONE result=0 verify_only=%d\n", verify_only); fflush(0);
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
