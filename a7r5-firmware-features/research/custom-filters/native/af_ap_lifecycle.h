/* 原登记完成回执：单一启动拥有者、驻留状态，不发布界面或成像能力。 */
#ifndef AF_AP_LIFECYCLE_H
#define AF_AP_LIFECYCLE_H
#include "af_slots.h"
typedef void (*AfApRegisterFn)(void *,const void *,const void *);
enum {AF_AP_LIFE_ARMED=1,AF_AP_LIFE_RECORDED=2,AF_AP_LIFE_TAKEN=3,AF_AP_LIFE_FAILED=4};
typedef struct {
 uint32_t version,bytes;
 uintptr_t base,registry,begin,end;
 uint64_t rows,serial;
 uint32_t constructor_index,phase;
} AfApRegistration;
_Static_assert(sizeof(AfApRegistration)==64,"原登记回执固定64B");
typedef struct {
 AfApRegistration registration;
 uint32_t phase,depth,calls,reserved;
} AfApLifecycle;
int af_ap_lifecycle_arm(AfApLifecycle *,uintptr_t base,void *registry);
/* 原函数始终先委派恰好一次；不匹配/重复/重入只拒绝回执，不能吞掉原登记。 */
void af_ap_lifecycle_dispatch(AfApLifecycle *,AfApRegisterFn,void *,const void *,const void *);
/* 只在原AppInit入口、恢复自己登记BL后消费；不能重复消费或把旧计数当完成。 */
int af_ap_lifecycle_take(AfApLifecycle *,AfApRegistration *);
enum {AF_AP_LIFE_UNSAFE_PERMISSIONS=-55};
/* 外层已核对实际RX页。恢复RX失败时回滚本指令再恢复；仍失败则不得继续执行该页。 */
int af_ap_lifecycle_write(uint32_t *,uint32_t before,uint32_t after,
                         int (*protect_page)(void *,int),void (*flush)(void *,size_t));
#endif
