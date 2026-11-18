#ifndef R5_ASPECT_REQUESTS_H
#define R5_ASPECT_REQUESTS_H

#include "geometry.h"

enum { R5_ASPECT_NOTIFY_BYTES = 0x468, R5_ASPECT_RESIZE_FIELDS = 10 };

/* 调整 A7R5 Stage_Notify 请求副本中的 HEIF 主图、场景图及缩略图。 */
int r5_aspect_heif_request(uint32_t id, uint8_t *packet, uint32_t bytes);

/* 调整 JPEG 的缩略图输入区域及其在原 160×120 画布中的位置。 */
int r5_aspect_thumbnail(uint32_t id, uint16_t *input, uint16_t *output);

#endif
