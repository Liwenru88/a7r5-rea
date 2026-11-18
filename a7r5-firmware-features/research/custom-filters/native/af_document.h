/* 完整预设的显式字节格式；无文件接口，不定义实际ISP载荷schema。 */
#ifndef AF_DOCUMENT_H
#define AF_DOCUMENT_H
#include "af_slots.h"
#define AF_DOCUMENT_HEADER 256u
#define AF_DOCUMENT_NAME_MAX 63u
#define AF_DOCUMENT_IMAGE_MAX 262144u
#define AF_DOCUMENT_MAX (AF_DOCUMENT_HEADER+AF_DOCUMENT_NAME_MAX+AF_DOCUMENT_IMAGE_MAX)
enum AfDocumentResult {
    AF_DOCUMENT_OK=0, AF_DOCUMENT_INVALID=-1,
    AF_DOCUMENT_CAPACITY=-2, AF_DOCUMENT_UNSUPPORTED=-3
};
typedef struct {
    uint32_t samples, clipped, delta_e[5], scope;
    uint8_t model_sha256[32];
} AfFitReport;
typedef struct {
    uint32_t present;
    AfPreset initial, saved;
    uint32_t schema, converter;
    const char *name;
    size_t name_bytes;
    const uint8_t *image;
    size_t image_bytes;
    AfFitReport report;
} AfDocument;
/* schema=0只允许纯参数。非零值由调用者批准；当前没有机身批准值。
 * 成功解码的name/image借用输入；输出和输入必须独立。失败不发布。
 * 纯参数的saved基底可不同于initial；LUT仍绑定同一基底和完整载荷。
 * 误差报告只对initial有效；调参后的成像误差需重新测量。 */
int af_document_encode(const AfDocument *, uint32_t schema, void *, size_t, size_t *);
int af_document_decode(const void *, size_t, uint32_t schema, AfDocument *);
/* 只用于已成功解码的document；当前预设偏离initial时返回0，不沿用拟合保证。 */
int af_document_report_applies(const AfDocument *,const AfPreset *current);
#endif
