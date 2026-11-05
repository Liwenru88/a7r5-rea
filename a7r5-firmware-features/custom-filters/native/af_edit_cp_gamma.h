/* 固定ST/CP第6列的研究数值格式适配；不是像素输入域或机身应用许可。 */
#ifndef AF_EDIT_CP_GAMMA_H
#define AF_EDIT_CP_GAMMA_H
#include "af_gamma406.h"
#include "af_joint.h"

#define AF_EDIT_CP_GAMMA_PROGRESS_TOTAL 128u
#define AF_EDIT_CP_GAMMA_OUTPUT_BYTES 1024u
typedef struct {
    uint32_t axis[128], gamma_y[128];
} AfEditCpGamma;

/* 原始record必须恰为576B，SHA-256为
 * f4e9f31bce38b4c705721a501c7597705852e671bc39baf60b02dac8b88f95ac，
 * 即锁定4.06 CP的wire0/column6/0xdcca0c原记录；再核对非均匀129点轴。
 * curve是该轴上的完整129个CP整数候选：共同点Edit_x=32*CP_x，Edit_y=2*CP_y。
 * CP独有61440采用明确参数往返政策：先在Edit两端值间线性向下取整，
 * 再(Y+1)/2向上取半；只有该结果恰等于curve[127]才可表达，否则SKIP。
 * 此舍入是本接口的有损表示准入政策，不是CP硬件插值或ISP舍入证据。
 * CP合法但两倍值越出Edit18位也返回AF_JOINT_SKIP；坏源/形状/单调性返回INVALID。
 * output自含1024B，无外部工作区；输入与output必须独立，回调不得改写活动缓冲。
 * 回调0及128均可取消，失败/取消不改变output；单一拥有者调用，地址发布非跨线程原子。
 * 不改变af_edit_gamma_bridge的18位坐标语义，不标识EVF/JPG或支持其他基底。
 */
int af_edit_cp_gamma(const void *record, size_t record_bytes,
                      const uint32_t *curve, size_t points, AfEditCpGamma *output,
                      AfGridProgress progress, void *context);
#endif
