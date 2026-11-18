/* 当前4.06原厂工作数组的只读整组快照；不代表图像生效。 */
#ifndef AF_FACTORY406_H
#define AF_FACTORY406_H
#include "af_slots.h"
#define AF_FACTORY406_ROWS 18u
/* 调用方持有原模型锁、保证全部数组在本次调用内稳定。
 * selector只允许0..9/17/18；数组基底采用原内部0..11编号。
 * 非法/陈旧来源或输出别名拒绝，不写源数组、不发布部分输出。 */
int af_factory406_snapshot(uint32_t selector,const uint32_t *bases,
                          const int32_t *const parameters[AF_PARAMETERS],AfPreset *output);
/* 原UI线程在原厂setter完整返回后调用；ap_base须来自已核对来源/映射的绑定。
 * 本函数核对原getter指令，沿原2e7d208/2e7cee4持有模型锁一次读取九字段。
 * 还核对当前原690身份；不能在原模型尚未初始化时调用。
 * 无文件/设备接口，不创建线程；只复用原模型锁，不更改原690或任何原槽。 */
int af_ap_factory406_snapshot(uintptr_t ap_base,uint32_t selector,AfPreset *output);
#endif
