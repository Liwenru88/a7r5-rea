/* 同包4.06实际原生接线；布局和永久前像由同一次ELF构建生成。 */
#ifndef AF_CP_NATIVE406_H
#define AF_CP_NATIVE406_H
#include "af_cp_native_bank406.h"
#include "af_cp_recipe406.h"
#ifdef AF_CP_CAPTURE406
#define AF_CP_NATIVE406_HOOKS 51u
#define AF_CP_NATIVE_CAPTURE_BYTES 584u
extern const volatile uint8_t af_cp_native406_capture_expected[AF_CP_NATIVE_CAPTURE_BYTES];
#else
#define AF_CP_NATIVE406_HOOKS 18u
#endif
typedef struct {uint32_t address;uint8_t code[4];} AfCpNative406Hook;
extern const volatile uint8_t af_cp_native406_factor_expected[288];
extern const volatile AfCpNative406Hook af_cp_native406_hooks[AF_CP_NATIVE406_HOOKS];
int af_cp_native406_bind_once(void);
int af_cp_native406_ready(void);
void af_cp_native406_receive_finished(void);
AfCpNativeBanks406 *af_cp_native406_banks(void);
void af_cp_native406_c4_target(void *,const void *,size_t,uint32_t);
void af_cp_native406_queue_target(void *,const void *,size_t,uint32_t,const void *);
void af_cp_native406_shot_copy_target(void *,const void *,size_t,uint32_t);
/* 以下入口由原0x24锁包装，和九字段投影同锁提交。 */
int af_cp_override406_prepare_joint(uint64_t,uint32_t,const AfPreset *,const AfJointAsset *);
void af_cp_override406_close(void);
#endif
