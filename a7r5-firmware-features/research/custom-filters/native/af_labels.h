/* 已提交文档名称的UI拥有者副本；不读写文件，不确认保存或成像。 */
#ifndef AF_LABELS_H
#define AF_LABELS_H
#include "af_slots.h"
#define AF_LABEL_BYTES 64u
typedef struct {
    uint64_t generation;
    uint32_t bytes;
    char text[AF_LABEL_BYTES];
} AfLabel;
typedef struct { AfLabel slots[AF_USERS]; } AfLabels;
void af_labels_init(AfLabels *);
/* 只在完整恢复/提交回读成功后调用。generation不得倒退；同代异名拒绝。
 * bytes=0且name=NULL表示明确墓碑，恢复默认编号；不会自动清空文件或目录。
 * name须与cache独立，验证完才写入，调用者在原UI线程串行执行。 */
int af_labels_publish(AfLabels *,uint32_t slot,uint64_t generation,const char *name,size_t bytes);
/* 成功返回NUL结尾的借用名称，最长63个UTF-8字节；下一次publish前消费。
 * 原TextSprite字符重载须先深拷贝，不能让异步组件长期借用此地址。
 * 无文档/墓碑返回AF_EMPTY且不写输出，适配器委派原编号资源。 */
int af_labels_read(const AfLabels *,uint32_t slot,const char **name,size_t *bytes);
#endif
