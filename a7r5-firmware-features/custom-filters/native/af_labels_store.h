/* 完整存储回执到名称缓存；不制造保存或成像成功回执。 */
#ifndef AF_LABELS_STORE_H
#define AF_LABELS_STORE_H
#include "af_labels.h"
#include "af_store.h"
/* 同一串行拥有者在persist成功之后调用，无额外I/O。
 * 只有store和catalog的完整预设/代号一致才发布名称副本；不确定/陈旧不改变名称。
 * recovering=1仅用于显式完整恢复，允许坏副本回退到较早完整代号并同步其名称。
 * recovering=0用于提交后通知，保持名称代号单调；不能用恢复标志接收迟到消息。 */
int af_labels_from_store(AfLabels *,const AfCatalog *,const AfStore *,const AfStoreBuffers *,int recovering);
#endif
