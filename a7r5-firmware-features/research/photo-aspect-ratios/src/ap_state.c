/* 菜单取消按原厂捕获/恢复配对，私有比例使用新代次重新发布。 */
#include "ap_state.h"
extern uintptr_t r5_aspect_capture_native(void);
extern uintptr_t r5_aspect_restore_native(void);
extern const volatile uint32_t stock_aspect_saved;
extern unsigned stock_restore_alias(void *, unsigned);
extern void stock_set(unsigned);
extern void stock_commit(unsigned);

static unsigned custom(unsigned id) { return id - 4u < R5_ASPECT_COUNT - 4u; }
static unsigned token(void) { return __atomic_load_n(&aspect_selection, __ATOMIC_ACQUIRE); }
static unsigned next(unsigned old, unsigned id) {
    return ((old & ~255u) + 256u) | (custom(id) ? id : 0u);
}
unsigned r5_aspect_publish(unsigned id)
{
    /* 显式操作阻止尚未完成的开机读盘覆盖当前选择。 */
    __atomic_store_n(&aspect_session.restore_claim, 1, __ATOMIC_RELEASE);
    unsigned old = token(), value;
    do { value = next(old, id); }
    while (!__atomic_compare_exchange_n(&aspect_selection, &old, value, 0,
                                       __ATOMIC_RELEASE, __ATOMIC_ACQUIRE));
    return value;
}
uintptr_t r5_aspect_capture_value(void)
{
    __atomic_store_n(&aspect_session.saved_choice, 0, __ATOMIC_RELEASE);
    r5_aspect_restore_once();
    unsigned epoch = token(), id = r5_aspect_get();
    uintptr_t result = r5_aspect_capture_native();
    if (epoch == token())
        __atomic_store_n(&aspect_session.saved_choice,
            0x100u | (stock_aspect_saved == 0 && custom(id) ? id : 0), __ATOMIC_RELEASE);
    return result;
}
uintptr_t r5_aspect_restore_value(void)
{
    unsigned expected = token();
    uintptr_t result = r5_aspect_restore_native();
    unsigned saved = __atomic_load_n(&aspect_session.saved_choice, __ATOMIC_ACQUIRE);
    if (saved & 0x100u) {
        unsigned value = next(expected, saved & 255u);
        __atomic_compare_exchange_n(&aspect_selection, &expected, value, 0,
                                   __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
    }
    return result;
}
uint64_t r5_aspect_restore_alias(void *self, unsigned menu)
{
    unsigned epoch = token();
    unsigned alias = stock_restore_alias(self, menu);
    return (menu == 33 ? (uint64_t)epoch << 32 : 0) | alias;
}
void r5_aspect_restore_commit(uint64_t packed, void (*callback)(unsigned))
{
    unsigned row = (unsigned)packed;
    if (callback != r5_aspect_commit) { callback(row); return; }
    unsigned id;
    if (row - 126u < 4u) id = row - 126u;
    else if (row - 0x1600u < R5_ASPECT_COUNT - 4u) id = row - 0x1600u + 4u;
    else return;
    unsigned expected = packed >> 32, value = next(expected, id);
    if (!__atomic_compare_exchange_n(&aspect_selection, &expected, value, 0,
                                    __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    stock_set(custom(id) ? 0 : id);
    stock_commit(custom(id) ? 126 : row);
    (void)r5_aspect_save(id);
}
