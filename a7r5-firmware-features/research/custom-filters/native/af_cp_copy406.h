/* 原E70 memcpy包装；只伴随输入版本，不制造图像或资源完成事件。 */
#ifndef AF_CP_COPY406_H
#define AF_CP_COPY406_H
#include "af_cp_input406.h"
typedef void (*AfCpCopy406Port)(void *,const void *,size_t);

/* 原固定目的的唯一写者调用。logical地址与宿主缓冲显式分开。
 * allow为0时先撤销该目的资格，仍原样复制一次；非零时核源epoch与真实VD。
 * copy必须为原memcpy ABI，input/source/destination须彼此独立。 */
int af_cp_copy406_observe(AfCpInput406 *,void *destination,uint32_t logical_destination,
    const void *source,uint32_t logical_source,size_t,uint32_t native_vd,unsigned allow,
    AfCpCopy406Port copy);
/* 四个已证原BL调用共用此入口，按真实LR和原调用帧路由。 */
void af_cp_copy406_gate(void);
void af_cp_override406_image_copy_target(void *,const void *,size_t,uint32_t);
void af_cp_override406_untracked_copy_target(void *,const void *,size_t);
#endif
