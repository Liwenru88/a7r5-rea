/* Regression check: a dlopen constructor creates and joins a scheduling thread. */
typedef unsigned long pthread_t;
extern pthread_t pthread_self(void);
extern int pthread_setschedparam(pthread_t, int, const void *);
extern int pthread_create(pthread_t *, const void *, void *(*)(void *), void *);
extern int pthread_join(pthread_t, void **);
extern int printf(const char *, ...);
extern void *dlopen(const char *, int);
extern void *dlsym(void *, const char *);
extern int dlclose(void *);
extern char *getenv(const char *);

#ifdef TEST_LIBRARY
static int result;
static void *worker(void *unused) {
    (void)unused;
    int priority = 0;
    result = pthread_setschedparam(pthread_self(), 0, &priority) == 0 ? 1 : -1;
    return 0;
}
__attribute__((constructor)) static void constructor(void) {
    pthread_t thread;
    if (pthread_create(&thread, 0, worker, 0) != 0) { result = -2; return; }
    if (pthread_join(thread, 0) != 0) result = -3;
}
int observe_test_result(void) { return result; }
void *Application_System_Init(void *argument) { return argument; }
int udtr_ufp_init(void) { return -7; }
int udtr_ufp_exit(void) { return -8; }
int osal_dynamic_id(unsigned int type, unsigned int owner, unsigned long value) {
    if (type == 0x4a && owner == 463 && value == 0x12345678) return 0;
    unsigned int *id = (unsigned int *)value;
    if (type != 42 || owner != 463 || !id) return -10;
    *id = 0x12345678;
    return -9;
}
int osal_reg_sync_msg_queue_cb(unsigned int id, void **handle, void *callback, unsigned long argument) {
    if (id != 42 || !handle || callback != (void *)0x1234 || argument != 17) return -14;
    *handle = (void *)0x5678;
    return -13;
}
int osal_snd_msg(unsigned int id, void *message) { (void)id; (void)message; return -12; }
int kikilog_set_notify_cb(unsigned int id) { return id == 42 ? -15 : -16; }
int mock_fill(int, int, unsigned int *, const void *)
    __asm__("_ZN5mpgpe13GpermFillRectENS_3GpeENS_7IntCoreEPjRKNS_13FillRectParamE");
int mock_blit(int, int, unsigned int *, const void *)
    __asm__("_ZN5mpgpe12GpermBitBlitENS_3GpeENS_7IntCoreEPjRKNS_12BitBlitParamE");
int mock_fill(int gpe, int core, unsigned int *sequence, const void *parameters) {
    if (gpe != 1 || core != 0 || !sequence || !parameters) return -17;
    *sequence = 77;
    return -18;
}
int mock_blit(int gpe, int core, unsigned int *sequence, const void *parameters) {
    if (gpe != 1 || core != 0 || !sequence || !parameters) return -19;
    *sequence = 78;
    return -20;
}
#else
extern int __libc_start_main(int (*)(int, char **), int, char **,
                            void (*)(void), void (*)(void), void (*)(void), void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int main_probe(int argc, char **argv) {
    (void)argc; (void)argv;
    void *library = dlopen("/lib/observe-constructor.so", 2);
    if (!library) return 2;
    int (*get_result)(void) = dlsym(library, "observe_test_result");
    if (!get_result || get_result() != 1) return 3;
    void *(*application_init)(void *) = dlsym(library, "Application_System_Init");
    if (!application_init || application_init((void *)0x1234) != (void *)0x1234) return 4;
    int (*updater_init)(void) = dlsym(library, "udtr_ufp_init");
    int (*updater_exit)(void) = dlsym(library, "udtr_ufp_exit");
    if (!updater_init || !updater_exit || updater_init() != -7 || updater_exit() != -8) return 5;
    int (*dynamic_id)(unsigned int, unsigned int, unsigned long) = dlsym(library, "osal_dynamic_id");
    unsigned int id = 0;
    if (!dynamic_id || dynamic_id(42, 463, (unsigned long)&id) != -9 || id != 0x12345678) return 6;
    if (dynamic_id(0x4a, 463, 0x12345678) != 0) return 7;
    int (*reg_sync)(unsigned int, void **, void *, unsigned long) = dlsym(library, "osal_reg_sync_msg_queue_cb");
    void *handle = 0;
    if (!reg_sync || reg_sync(42, &handle, (void *)0x1234, 17) != -13 || handle != (void *)0x5678) return 8;
    int (*send_msg)(unsigned int, void *) = dlsym(library, "osal_snd_msg");
    if (!send_msg || send_msg(42, 0) != -12) return 9;
    int expected = getenv("QEMU_NO_CP_UPDATER") ? -1021 : -12;
    if (send_msg(0x912503d0, 0) != expected) return 10;
    unsigned int capid_request[6] = {0, 0x1000, 0, 0, 0, 0};
    if (send_msg(0x9004015e, capid_request) != -12 || capid_request[1] != 0x1000) return 14;
    int (*notify)(unsigned int) = dlsym(library, "kikilog_set_notify_cb");
    if (!notify || notify(42) != -15) return 11;
    int (*fill)(int, int, unsigned int *, const void *) = dlsym(library, "_ZN5mpgpe13GpermFillRectENS_3GpeENS_7IntCoreEPjRKNS_13FillRectParamE");
    int (*blit)(int, int, unsigned int *, const void *) = dlsym(library, "_ZN5mpgpe12GpermBitBlitENS_3GpeENS_7IntCoreEPjRKNS_12BitBlitParamE");
    unsigned int sequence = 0;
    unsigned char parameters[144] = {0};
    if (!fill || fill(1, 0, &sequence, parameters) != -18 || sequence != 77) return 12;
    if (!blit || blit(1, 0, &sequence, parameters) != -20 || sequence != 78) return 13;
    dlclose(library);
    printf("PASS: constructor thread and application-init wrapper preserved behavior\n");
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(main_probe, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
#endif
