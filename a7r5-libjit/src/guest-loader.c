/* 仅用于无网QEMU夹具：加载、立即关闭库句柄并收割子进程。 */
extern void *dlopen(const char *, int);
extern int dlclose(void *);
extern char *dlerror(void);
extern long write(int, const void *, unsigned long);
extern int waitpid(int, int *, int);

int main(int argc, char **argv) {
    if (argc != 2) return 40;
    void *handle = dlopen(argv[1], 1);
    if (!handle) {
        char *error = dlerror();
        unsigned long size = 0;
        while (error && error[size]) size++;
        write(1, error, size);
        return 41;
    }
    if (dlclose(handle)) return 42;
    write(1, "LOADER_RETURNED\n", 16);
    int status = 0;
    if (waitpid(-1, &status, 0) < 0) return 0;
    write(1, "WORKER_REAPED\n", 14);
    return (status & 127) ? 43 : 0;
}
