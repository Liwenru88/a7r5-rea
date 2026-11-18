/* 原Capture生命期的按值伴随；不拥有原图像或完整配方。 */
#ifndef AF_CP_CAPTURE406_H
#define AF_CP_CAPTURE406_H
#include "af_cp_components406.h"
#include "af_cp_capture_color406.h"
#define AF_CP_CAPTURE406_COUNT 490u
#define AF_CP_CAPTURE406_B 0xbd0u
#define AF_CP_CAPTURE406_G 0xda8u
#define AF_CP_CAPTURE406_D 0xe20u
#define AF_CP_CAPTURE406_FIELDS 47u
#define AF_CP_CAPTURE406_FORMATTER_BYTES 0x4eu
typedef struct {
    uint32_t a,epoch,flags,thread;
    uint64_t birth;
    AfCpGamma406Tone tone;
    uint8_t fields[AF_CP_CAPTURE406_FIELDS];
} AfCpCapture406Record;
typedef struct {
    uint64_t birth;
    uint32_t a,epoch,thread,serial,channel,index;
} AfCpCapture406Token;
typedef struct {
    AfCpCapture406Token token;
    AfCpGamma406Tone tone;
    uint8_t shadow[84];
} AfCpCapture406Reverse;
typedef struct {
    void *context;
    int (*read)(void *,uint32_t,void *,size_t);
    int (*thread)(void *,uint32_t *);
    int (*shadow)(void *,AfCpGamma406Tone *,uint8_t image[84]);
} AfCpCapture406Ports;
typedef struct {
    AfCpCapture406Ports ports;
    AfCpCapture406Record *records;
    uint64_t next_birth;
    uint32_t magic,guard,fault,pool_busy,sequence;
    AfCpCapture406Token scope;
    uint32_t scope_active,scope_qualified,scope_formatted,scope_formatter;
} AfCpCapture406;
enum {AF_CP_CAPTURE406_NORMAL=1,AF_CP_CAPTURE406_RESTORE=2};
size_t af_cp_capture406_records_bytes(void);
/* state/490条工作区首次清零，必须独立且保持到同一CP启动期结束。
 * 工作区由已核原堆在bind时一次分配，拍摄热路径不分配或释放。 */
int af_cp_capture406_init(AfCpCapture406 *,const AfCpCapture406Ports *,void *records,size_t bytes);
int af_cp_capture406_ready(const AfCpCapture406 *);
int af_cp_capture406_birth(AfCpCapture406 *,uint32_t a);
int af_cp_capture406_release(AfCpCapture406 *,uint32_t a);
/* 所有撤销写者争用均poison；不持guard穿越原调用。未跟踪A仍走原厂。 */
int af_cp_capture406_write_begin(AfCpCapture406 *,uint32_t a,unsigned kind,AfCpCapture406Token *);
int af_cp_capture406_write_end(AfCpCapture406 *,const AfCpCapture406Token *,unsigned kind);
int af_cp_capture406_reverse_begin(AfCpCapture406 *,uint32_t destination,AfCpCapture406Reverse *);
int af_cp_capture406_reverse_end(AfCpCapture406 *,uint32_t destination,const AfCpCapture406Reverse *);
/* 每一次原845DB8（含不合资格的原厂输入）都占同步写者scope；重入/并发poison。
 * 即使返回EMPTY，已生成的非零serial也须由同一wrapper执行scope_end。 */
int af_cp_capture406_scope_begin(AfCpCapture406 *,uint32_t g,AfCpCapture406Token *);
int af_cp_capture406_scope_end(AfCpCapture406 *,const AfCpCapture406Token *);
/* AA7F08的真实正常分支构造事件；不从F与D的数值相等创造来源。 */
int af_cp_capture406_format_begin(AfCpCapture406 *,uint32_t d,uint32_t formatter,AfCpCapture406Token *);
int af_cp_capture406_format_end(AfCpCapture406 *,uint32_t d,uint32_t formatter,const AfCpCapture406Token *);
int af_cp_capture406_scope_read(AfCpCapture406 *,uint32_t formatter,uint32_t output,
    AfCpGamma406Tone *,AfCpCapture406Token *,uint8_t formatter_image[AF_CP_CAPTURE406_FORMATTER_BYTES]);
int af_cp_capture406_scope_current(AfCpCapture406 *,const AfCpCapture406Token *);
/* reset/池拆除使所有旧epoch失效；发生在写入/消费期间则关闭此伴随通路。 */
int af_cp_capture406_reset(AfCpCapture406 *);
int af_cp_capture406_pool_begin(AfCpCapture406 *);
int af_cp_capture406_pool_end(AfCpCapture406 *);

/* 真实ARM目标：完整调用原厂一次，最后归还只回收伴随条目，不释放原对象。 */
int af_cp_capture406_bind_target(void);
int af_cp_capture406_target_ready(void);
void af_cp_capture406_reset_target(void);
uint32_t af_cp_capture406_birth_target(uint32_t);
uint32_t af_cp_capture406_release_target(uint32_t);
uint32_t af_cp_capture406_pool_target(uint32_t);
uint32_t af_cp_capture406_rebuild_target(uint32_t);
uint32_t af_cp_capture406_restore_target(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t);
uint32_t af_cp_capture406_reverse_target(uint32_t);
uint32_t af_cp_capture406_gamma_target(uint32_t);
uint32_t af_cp_capture406_format_target(uint32_t,uint32_t);
uint32_t af_cp_capture406_rsource_target(uint32_t,uint32_t,uint32_t,uint32_t);
uint32_t af_cp_capture406_color_target(uint32_t,uint32_t,uint32_t,uint32_t);
void af_cp_capture406_request_invalidate_target(void);
int af_cp_capture406_request_publish_target(const AfCpInput406Token *,uint32_t,const AfCpRuntimeAsset406 *);
int af_cp_capture406_color_view_target(AfCpCaptureColor406View *);
int af_cp_capture406_color_current_target(const AfCpCaptureColor406View *);
int af_cp_capture406_color_scope_target(uint32_t r);
int af_cp_capture406_read_target(uint32_t formatter,uint32_t output,AfCpGamma406Tone *,
    AfCpCapture406Token *,uint8_t formatter_image[AF_CP_CAPTURE406_FORMATTER_BYTES]);
int af_cp_capture406_current_target(const AfCpCapture406Token *);
#endif
