/* 完整研究配方的独立128字节协议；不分配Sony消息ID，不确认成像。 */
#ifndef AF_RECIPE_TRANSPORT_H
#define AF_RECIPE_TRANSPORT_H
#include "af_joint_asset.h"
#define AF_RECIPE_FRAME_BYTES 128u
#define AF_RECIPE_DATA_BYTES 76u
#define AF_RECIPE_DATA_FRAMES 26u
#define AF_RECIPE_TOTAL_FRAMES 28u
#define AF_RECIPE_MAX_DATA_FRAMES (AF_JOINT_SECTOR_SUPPORTED?33u:26u)
#define AF_RECIPE_MAX_TOTAL_FRAMES (AF_JOINT_SECTOR_SUPPORTED?35u:28u)
#define AF_RECIPE_CAP_FULL 1u
#define AF_RECIPE_CAP_SECTOR 2u
#define AF_RECIPE_NONE 2u
#define AF_RECIPE_LEASES 8u
/* 字节布局全为小端：magic[0:4]、schema[4]、operation[5]、header=48[6:8]、
 * total=1943[8:12]、slot[12:16]、session[16:24]、version[24:32]、
 * offset[32:36]、length[36:38]、有符号status[38:40]、capability[40:44]、
 * 保留零[44:48]、payload[48:124]、CRC32[124:128]。payload尾部必须为零。
 * BEGIN payload：base/kind/八值[0:10]、保留零[10:12]、完整AJR1 SHA[12:44]、
 * 原LUT SHA[44:76]；ACK payload仅32字节AJR1 SHA。CRC/SHA不是身份认证。
 * AF_RECIPE_CAP_FULL是本协议的独立能力命名空间，不是Sony消息ID或已协商的A7P1位。
 */
enum AfRecipeOperation {AF_RECIPE_BEGIN=1,AF_RECIPE_DATA=2,AF_RECIPE_END=3,AF_RECIPE_ACK=4};
enum AfRecipeState {AF_RECIPE_FREE=0,AF_RECIPE_RECEIVING=1,AF_RECIPE_COMPLETE=2,
    AF_RECIPE_READY=3,AF_RECIPE_TAKEN=4,AF_RECIPE_ACTIVE=5,AF_RECIPE_RETIRED=6};
typedef struct {
    uint64_t session,version;
    uint32_t slot;
    AfPreset preset;
    uint8_t image[AF_JOINT_ASSET_MAX_BYTES];
    uint32_t image_bytes;
} AfRecipeMessage;
typedef struct {uint32_t magic;AfRecipeMessage message;} AfRecipeTx;
/* 内部驻留C布局，非稳定序列化ABI；AP/CP须按同一当前头重编。
 * 热状态放前以避免完整asset扩大后跨4095字节寻址；线协议仍显式逐字节编码。 */
typedef struct {uint32_t state,references;AfRecipeMessage message;AfJointAsset asset;} AfRecipeOwned;
typedef struct {uint64_t session,version,lease;uint32_t bank;} AfRecipeLease;
typedef struct {uint64_t lease;uint32_t bank;} AfRecipeReference;
typedef struct {uint64_t session,version;uint32_t slot;int status;uint8_t payload_sha256[32];} AfRecipeAck;
typedef struct {
    uint32_t magic,capabilities,receiving,active,offset;
    uint64_t session,seen_version,committed_version,next_lease,owner;
    AfRecipeReference leases[AF_RECIPE_LEASES];
    AfRecipeAck rejected;
    uint32_t rejected_valid,rejected_bytes;
    AfRecipeOwned buffers[2];
} AfRecipeRx;

size_t af_recipe_tx_bytes(void);
size_t af_recipe_rx_bytes(void);
size_t af_recipe_decode_work_bytes(void);
/* init独立复制全部源字节与八项值；不借repository的复用缓冲。 */
int af_recipe_tx_init(AfRecipeTx *,uint64_t session,uint64_t version,uint32_t slot,
    const AfPreset *,const void *,size_t);
/* ordinal=0为BEGIN，1..26为DATA，27为END；仅生成，不发送、不重试。 */
int af_recipe_tx_frame(const AfRecipeTx *,uint32_t ordinal,void *,size_t);
uint32_t af_recipe_tx_frames(const AfRecipeTx *);
/* 只接受对应tx的session/version/slot/载荷摘要；不发送、不重发或推断图像生效。 */
int af_recipe_tx_ack(const AfRecipeTx *,const void *,size_t,AfRecipeAck *);
/* 首次对象清零，配置一次；能力须由真实外层协商明确提供，未知能力拒绝。
 * 字节核心支持C01..C20；实际入口对C01..C06另核USER20协商位。
 * 显式overlay不授权个人设置迁移，不写原厂六槽表。 */
int af_recipe_rx_init(AfRecipeRx *,uint64_t session,uint32_t capabilities);
/* 唯一通信拥有者串行调用；只收取独立副本。END不在消息栈解码。
 * 同事务严格顺序；错误包不改变已提交对象，版本在BEGIN成功时消耗。 */
int af_recipe_rx_frame(AfRecipeRx *,const void *,size_t);
/* 完整收取后由显式任务调用；work为独立驻留工作区，不使用大栈解码。
 * 成功仅表示AJR1及BEGIN元数据匹配，不授予当前CP模型/成像资格。 */
int af_recipe_rx_validate(AfRecipeRx *,AfJointAssetDecodeWork *);
/* 最近一次完整载荷验证失败的有版本拒绝ACK；下一次BEGIN成功后失效。
 * 仅读取，不发送或自动重试，不对未校验的乱序/损坏单帧作成功回应。 */
int af_recipe_rx_rejection(const AfRecipeRx *,void *ack,size_t);
/* take取得唯一发布拥有者租约，commit后仍持有该代，必须显式release。
 * 未处理take时不能取消；borrow指针仅在该租约存活期间有效。 */
int af_recipe_rx_take(AfRecipeRx *,AfRecipeLease *,const AfRecipeOwned **);
/* decision=AF_OK仅发布软件活动对象；失败decision为负，不替换旧活动代。
 * ACK只称软件提交决定，调用者仍需原CP原子应用/失败语义，不代表像素。
 * 成功提交后即使ACK实际发送失败也不能回滚或自动重发本事务。 */
int af_recipe_rx_finish(AfRecipeRx *,const AfRecipeLease *,int decision,void *ack,size_t);
int af_recipe_rx_acquire(AfRecipeRx *,AfRecipeLease *,const AfRecipeOwned **);
int af_recipe_rx_release(AfRecipeRx *,const AfRecipeLease *);
/* 只取消未take的incoming；不重置session/版本，不影响活动或退役租约。 */
int af_recipe_rx_cancel(AfRecipeRx *);
int af_recipe_ack_decode(const void *,size_t,AfRecipeAck *);
#endif
