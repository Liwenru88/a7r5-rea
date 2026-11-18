# 4.13独立封包与回读

Feature ID: 014-native24-update413
Status: IMPLEMENTED_OFFLINE

新增`native24-combined/release413/build.py`，不修改013构建器或封存回执。输入固定为013归档四组件、当前候选索引、已核验上游4.36基线，以及原4.00 DAT。新输出位于`.local/native24-update413-20261103-01`，交付复制至`native24-combined/releases/4.13`，均拒绝覆盖。

USR以冻结上游基线`bfaf6c1e…`为源，保持其机内lut目录及原布局。复用已有尾部块扩展算法，新增仅在本封装器生效的三项固定绑定（AP、23／32图形资源，原inode及源／目标长度和完整SHA均锁定）；不放宽通用Patch或旧图标白名单。扩展AP及两资源后，独立Audit比较全部路径、inode、内容／块映射和非容量元数据，e2fsck只读检查。CP定长替换既有FAT数据区，其他字节保持。

沿用上游WBI和十二份参数模板；以原TAR定长覆盖视图独立构造预期明文及清单。DAT工具从原官方包建立新工作副本，由工具自行重算清单、将版本改为4.13并正常研究签名。再用独立解包器逐帧检查、逐成员对比、回读四组件、比对完整明文及原updater，另用OpenSSL验签。

先复用013的源码新鲜度、80项完整相关回归及115／39帧QEMU证据；不重复运行未变化的运行时。封装层定向拒绝测试与现有尾部扩展／DAT工具回归负责新增边界，最终完整DAT回读为主要集成验证。失败输出保留现场，不覆盖旧包、不安装。回退仅指重新选择旧离线工件，不声称机身可降级。

| 文件 | 职责 | Requirement |
|---|---|---|
| `native24-combined/release413/build.py` | 固定输入、镜像扩展、封包及独立核对 | REQ-001～003 |
| `native24-combined/release413/test_release.py` | 未知载荷／不完整回执拒绝 | REQ-001、003 |
| `native24-combined/releases/4.13/` | 新DAT、BIN、公钥、必要源码和证据 | REQ-004 |
| 当前索引及README | 清晰区分离线封装与机身验收 | REQ-004 |
