/* AJR1到4.06原网格表的字节适配；不安装挂钩、不提供像素模型或机身许可。 */
#ifndef AF_GRID406_SOURCE_H
#define AF_GRID406_SOURCE_H
#include "af_joint_asset.h"
#define AF_GRID406_STATE_BYTES 0x18au
#define AF_GRID406_CONTEXT_BYTES 0x6b4u
#define AF_GRID406_C4_BYTES 0xc4u
#define AF_GRID406_OPERATION_BYTES 8u
typedef struct {
    AfJointAsset asset;
    uint8_t payload_sha256[32];
    uint32_t slot,level,grid_address;
} AfGrid406Table;
/* snapshot必须来自同一次锁内clone伴随发布的身份；不能由九字段相等推导。
 * root是原240d34的r1，c4是r3，source是该C4首指针。
 * 本接口只保存调用方已证明的关联，不生成身份、不借全局当前配方。 */
typedef struct {uint64_t snapshot;uint32_t root,c4,source;} AfGrid406Key;
typedef struct {
    AfGrid406Table table;
    AfGrid406Key key;
    uint32_t active;
} AfGrid406Token;
/* 固定本包AJR1完整解码、载荷/模型/基底校验；保留全部Gamma/矩阵/CC1。
 * grid_address为调用方驻留CP内存中1215源字节的真实地址；地址本身不授予访问许可。
 * prepare不向该地址写入，调用方须先原样复制asset.recipe.grid并保证驻留。
 * 仅新C07..C20，level1..8；不借用原六marker。失败不发布。 */
int af_grid406_prepare(const AfPreset *,const void *payload,size_t,
    const uint8_t model_sha256[32],uint32_t slot,uint32_t level,
    uint32_t grid_address,AfGrid406Table *);
/* capture重新编码核对实际完整recipe摘要并深拷贝，之后原table可另作下一操作。
 * token及原grid_address处1215源在使用期间由唯一拥有者保持不可变。 */
int af_grid406_capture(const AfGrid406Table *,const AfGrid406Key *,AfGrid406Token *);
/* 只接受本次显式key、原查询实际返回0..3及已证mode0/profile0；
 * 缺查询/其他模式返回SKIP，不借旧六槽bef620绕过硬件来源门槛。
 * operation/c4/grid_state/context及两个输出各有上述最小字节数且相互独立。
 * operation是*root，原240de2 STRD写入的operation+4必须仍指向key.c4，原C4首指针仍是key.source。
 * grid_state是*(pipe+8)，其+4为原source_class，不是C4指针，必须保持原字节。
 * raw_grid是调用方从grid_address实际持有映射取得的1215源，逐字节核对深拷贝。
 * query_class是原415160返回的硬件分类，不是银行index；mode0在原230ddc
 * 固定stage+0xb=0，故本接口仅失效context+54；mode1/2/3不在该接口范围。
 * 只改原grid_state+184/+188/+189与context+54缓存字节，其他字节保持。
 * 模拟的是原selector结果及缓存失效，成功不表示原packer已运行或ISP已应用。
 * 原230f0c私有分派仍须独立接到230f10；只调用此函数不足以使新槽生效。 */
int af_grid406_overlay(const AfGrid406Token *,const AfGrid406Key *,
    uint32_t mode,uint32_t profile,uint32_t level,uint32_t query_class,
    const void *raw_grid,const void *operation,const void *c4,
    const void *grid_state,const void *context,
    void *state_out,void *context_out);
/* 仅结束本次root授权。原state残留1215指针，绝不能据此释放table/原表内存。
 * 调用方须保持驻留，直到原选择器已替换引用且不会再次重包。packed银行仍原厂管理。 */
int af_grid406_finish(AfGrid406Token *,const AfGrid406Key *);
#endif
