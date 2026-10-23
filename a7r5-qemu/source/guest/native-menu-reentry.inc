/* 只在已核对的原生重入切换中省略未建模 boot 硬件清理；其他调用透传。 */
static unsigned int a7r5_native_transition;
static void (*a7r5_native_original_boot_exit)(void *,const unsigned int *);
static void a7r5_native_boot_exit(void *o,const unsigned int *to) {
    unsigned long m=captured_manager;
    if (a7r5_native_transition && (unsigned int)syscall(178)==ui_thread_id &&
        m && o==*(void **)(m+0x398) && to && *to==0x354 &&
        *(unsigned long *)o==appfw_base+0x58d3028) {
        record("A7R5_NATIVE_BOOT_EXIT_OMITTED ","known MENU reentry only; unmodeled boot hardware teardown");
        return;
    }
    a7r5_native_original_boot_exit(o,to);
}
static void a7r5_native_install_boot_exit(unsigned long base) {
    unsigned long *slot=(unsigned long *)(base+0x58d3050);
    if (*slot!=base+0x20c7bac) __builtin_trap();
    if (mprotect((void *)((unsigned long)slot&~4095UL),4096,3)) __builtin_trap();
    a7r5_native_original_boot_exit=(void *)*slot;
    *slot=(unsigned long)a7r5_native_boot_exit;
    if (mprotect((void *)((unsigned long)slot&~4095UL),4096,1)) __builtin_trap();
}
/* 原生离线菜单补充入口：只消费已确认关闭态的 MENU 按下/释放。 */
static unsigned int a7r5_native_consume_release;
static unsigned int a7r5_native_enabled(void) { return getenv("A7R5_NATIVE_MENU_REENTRY")!=0; }
static int a7r5_native_key_received(unsigned int queue,void *message) {
    if (!a7r5_native_enabled() || queue!=0x807a0020 || !message || !real_msg_size || !real_free_msg ||
        real_msg_size(message)!=20 || !real_get_source || real_get_source(message)!=0x92840747) return 0;
    const unsigned int *words=message;
    if (words[0]!=0x1ab || words[1] || words[3] || words[4]!=1) return 0;
    if (!words[2]) {
        __atomic_store_n(&a7r5_native_key_down,0,__ATOMIC_RELEASE);
        return __atomic_exchange_n(&a7r5_native_consume_release,0,__ATOMIC_ACQ_REL)!=0;
    }
    if (words[2]!=1)return 0;
    if (__atomic_exchange_n(&a7r5_native_key_down,1,__ATOMIC_ACQ_REL))
        return __atomic_load_n(&a7r5_native_consume_release,__ATOMIC_ACQUIRE)!=0;
    unsigned long m=captured_manager;
    unsigned int current=m?*(unsigned int *)(m+0x3b8):0;
    char text[180];
    snprintf(text,sizeof text,"current=%#x tid=%ld seen=%u",current,syscall(178),a7r5_native_seen_menu);
    record("A7R5_NATIVE_MENU_PRESS ",text);
    if (a7r5_native_seen_menu && current==0x355) {
        __atomic_store_n(&a7r5_native_consume_release,1,__ATOMIC_RELEASE);
        __atomic_store_n(&a7r5_native_pending,1,__ATOMIC_RELEASE);
        return 1;
    }
    return 0;
}
static void a7r5_native_reentry_poll(void) {
    if (!a7r5_native_enabled() || !__atomic_load_n(&a7r5_native_pending,__ATOMIC_ACQUIRE) ||
        (unsigned int)syscall(178)!=ui_thread_id || create_screen_active ||
        __atomic_load_n(&a7r5_apply_depth,__ATOMIC_ACQUIRE)) return;
    unsigned long m=captured_manager;
    if (!m || *(unsigned long *)m!=appfw_base+0x58d2fb8 || !*(unsigned long *)(m+0x398))return;
    unsigned long controller=*(unsigned long *)(m+0x398);
    if (*(unsigned long *)controller!=appfw_base+0x58d3028) {
        __atomic_store_n(&a7r5_native_pending,0,__ATOMIC_RELEASE);
        record("A7R5_NATIVE_MENU_REFUSED ","boot owner vtable differs; no apply");return;
    }
    unsigned int current=*(unsigned int *)(m+0x3b8);
    if (!__atomic_exchange_n(&a7r5_native_pending,0,__ATOMIC_ACQ_REL))return;
    if (current!=0x355) {
        record("A7R5_NATIVE_MENU_REFUSED ","screen changed before draw completion; no apply");return;
    }
    char text[180];
    snprintf(text,sizeof text,"closed=%#x owner=rep_boot tid=%u boundary=draw-return",current,ui_thread_id);
    record("A7R5_NATIVE_MENU_REENTER ",text);
    unsigned int from=0x4cf,to=0x354,restore=0x4cf;
    __atomic_add_fetch(&a7r5_apply_depth,1,__ATOMIC_RELEASE);
    a7r5_native_transition=1;
    a7r5_original_apply((void *)m,&from,&to,&restore,0,1,0,0,0);
    a7r5_native_transition=0;
    __atomic_sub_fetch(&a7r5_apply_depth,1,__ATOMIC_RELEASE);
    snprintf(text,sizeof text,"current=%#x tid=%u",*(unsigned int *)(m+0x3b8),ui_thread_id);
    record("A7R5_NATIVE_MENU_REENTER_RETURN ",text);
}
