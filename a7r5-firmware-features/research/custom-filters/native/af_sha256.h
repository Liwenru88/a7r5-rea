/* 完整成像字节摘要；只检测内容身份，不提供来源认证。 */
#ifndef AF_SHA256_H
#define AF_SHA256_H
#include <stddef.h>
#include <stdint.h>
int af_sha256(const void *data, size_t bytes, uint8_t output[32]);
#endif
