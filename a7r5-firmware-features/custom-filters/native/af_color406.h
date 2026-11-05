/* 当前4.06完整构造器的半字参数运算；不是像素颜色模型。 */
#ifndef AF_COLOR406_H
#define AF_COLOR406_H
#include "af_slots.h"
/* raw按3端点×6项排列；每端点使用同一组独立校准对角值。
 * 精确保留原strh的低16位，不把越界截断解释为已批准的ISP系数范围。 */
int af_color406_matrix(const uint16_t raw[18],const uint16_t diagonal[3],int16_t output[27]);
/* raw第一端点为绝对项，后两端点为相对第一端点的差分；
 * adjust为原全局修正器输出的8项，先作用于第一端点再传播差分。 */
int af_color406_primary(const uint16_t raw[24],const int16_t adjust[8],int16_t output[24]);
/* 第二域只有第一端点加修正；后8项原样保留元数据，不叠加LUT增量。
 * 是否允许调用由原profile/模式决定；此函数不自动开放不支持的第二域。 */
int af_color406_secondary(const uint16_t raw[8],const int16_t adjust[8],const uint16_t metadata[8],int16_t output[16]);
/* 只支持原27/24/8项增量；必须在原构造/差分展开之后使用。
 * 所有对象须独立；无文件/分配/设备接口，非法输入不发布。 */
int af_color406_add(const int16_t *,const int16_t *,uint32_t count,int16_t *);
/* 原常规CC1消费的两级Q8插值；weights依次为主路径端点1权重、
 * 次路径端点1/2权重、两路径混合权重。范围0～256，次路径两权重和≤256。
 * 第一层按原低半字/向下截位，最终混合按半入且远离0舍入；
 * 权重须由已验证原上下文取得，不猜测它与色温/曝光/像素的关系。 */
int af_color406_blend(const int16_t endpoints[24],const uint16_t weights[4],int16_t output[8]);
/* 已按原门控选定的规范校准字节：前4项有符号，后4项无符号。
 * 调用者负责原全局/动态来源及禁用时不写的语义，不自动猜测校准来源。 */
int af_color406_adjust(const uint8_t raw[8],int16_t output[8]);
/* 原矩阵常规消费的三端点、两路径Q8混合；权重顺序与CC1接口相同。
 * 先对差分半入远离0，再加第一端点并饱和16位；最终混合再次舍入/饱和。
 * 不含时间平滑、特殊profile、附加矩阵/色域转换或硬件像素处理。 */
int af_color406_matrix_blend(const int16_t endpoints[27],const uint16_t weights[4],int16_t output[9]);
#endif
