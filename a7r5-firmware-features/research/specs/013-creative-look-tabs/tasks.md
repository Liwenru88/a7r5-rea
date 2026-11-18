# 实施任务

- [x] T001 锁定原D9列表、焦点及渲染结构，建立切Tab不应用和按键分层的可执行回归。
  _Requirements: REQ-001, REQ-002, REQ-003_
  _Acceptance: AC-001, AC-002, AC-003_
  _Verification: 原指令／模型前像与旧012失败回归_
  _Boundary: 原AP只读取证及拥有测试_
- [x] T002 实现限定页面的两组投影、Tab渲染和焦点导航，隔离浏览与应用，保留原调参／确认。
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_
  _Acceptance: AC-001, AC-002, AC-003, AC-004_
  _Verification: 机器码主路径、无写入、空组／快速输入／退出及原操作回归_
  _Depends: T001_
  _Boundary: AP菜单拥有源与严格构建接线_
- [x] T003 建立新候选固定身份的QEMU实验，实际按键验证两组、无自动应用、调参、确认、重入及截图。
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005_
  _Acceptance: AC-001, AC-002, AC-003, AC-004, AC-005_
  _Verification: Qt回执、只读状态、原帧／PNG、多轮MENU及三侧正常退出_
  _Depends: T002_
  _Boundary: 独立QEMU实验和新构建目录，原默认运行时保持_
- [x] T004 完成相关回归与独立重建，封存组件／源码／回执，更新候选与交付说明。
  _Requirements: REQ-005_
  _Acceptance: AC-005_
  _Verification: 严格归档门禁、来源新鲜度和历史摘要保持_
  _Depends: T003_
  _Boundary: 新研究归档、当前索引及文档，不封DAT、不接设备_

T001～T004离线范围完成。80项相关CPU回归、2项固定身份检查、满库115次／空库39次实际Qt操作通过，154原帧与PNG一致，三侧正常退出。09／10独立重建四组件一致，新归档1369项文件及压缩包逐成员核对通过。长列表滚动的既有顶部文字缺失、原E4／成像、真实介质和机身验收仍未解决或验证，整体NOT_VERIFIED；未连接相机，未封DAT。
