/* 仅供独立 AArch64 测试；定义来自固件 glibc ABI，不引入 macOS 头文件。 */
typedef unsigned int uint32_t;
typedef int int32_t;
typedef unsigned long uint64_t;
typedef long ssize_t;
#define UINT64_C(x) x##UL
#define O_RDONLY 0
#define O_RDWR 2
#define SEEK_SET 0
#define SEEK_END 2
#define EINTR 4
#define PROT_READ 1
#define PROT_WRITE 2
#define MAP_SHARED 1
#define MAP_FAILED ((void *)-1)
#define RTLD_DEFAULT ((void *)0)
extern int printf(const char *, ...), fflush(void *), snprintf(char *, unsigned long, const char *, ...);
extern int strcmp(const char *, const char *), memcmp(const void *, const void *, unsigned long);
extern char *strstr(const char *, const char *);
extern int open(const char *, int, ...), close(int), munmap(void *, unsigned long);
extern long lseek(int, long, int);
extern ssize_t read(int, void *, unsigned long);
extern void *mmap(void *, unsigned long, int, int, int, long), *dlsym(void *, const char *);
extern void _exit(int);
extern int *__errno_location(void);
#define errno (*__errno_location())
