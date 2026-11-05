# 实施任务

- [x] T001 新增原有界面与自动回退回归，在010组件上确认失败原因。
  _Requirements: REQ-001, REQ-002, REQ-003_
  _Acceptance: AC-001, AC-002, AC-003_
  _Verification: 定向机器码回放与委派结果_
- [x] T002 分离显示和写保护，实现有界后台回退、损坏日志协调及最后意图排队，移除ST恢复交互。
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_
  _Acceptance: AC-001, AC-002, AC-003, AC-004_
  _Verification: 新构建、定向及相关CPU回归_
  _Depends: T001_
- [x] T003 建立新组件固定身份的QEMU实验，真实Qt复验原厂与附加条目、调参、菜单往返并截图。
  _Requirements: REQ-001, REQ-003, REQ-004, REQ-005_
  _Acceptance: AC-001, AC-003, AC-004, AC-005_
  _Verification: 输入回执、原帧与PNG、真实后台快照及正常退出_
  _Depends: T002_
- [x] T004 归档新证据，更新当前候选及交付说明，列明QEMU和实机边界。
  _Requirements: REQ-005_
  _Acceptance: AC-005_
  _Verification: 摘要／源码／回执一致，旧归档保持_
  _Depends: T003_

T001～T004离线范围已完成：56项相关CPU回归、原厂参数委派契约、2项QEMU固定身份、107次Qt操作及107原帧核对通过。归档1036文件及压缩包逐成员校验完成。相机与成像仍未验收，整体NOT_VERIFIED；未生成DAT。
