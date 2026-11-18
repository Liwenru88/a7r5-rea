# 稳定性实施任务

- [x] T001 建立拥有的稳定性源、精确派生合同和故障期望回归。
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-006_
  _Acceptance: AC-001, AC-002, AC-003, AC-006_
  _Verification: 复用上轮红灯，新增外部结果断言、来源及替换失败路径_
- [x] T002 实现失败协调、R5SEL6及恢复日志、库身份、启动终态与统一界面恢复保护。
  _Requirements: REQ-001, REQ-002, REQ-004_
  _Acceptance: AC-001, AC-002, AC-004_
  _Verification: 发送后丢ACK、双重失败、发布不确定及重启／手动恢复_
  _Depends: T001_
- [x] T003 实现短读、幂等导入、零字节保护、双卡优先及旧库备份／激活回退。
  _Requirements: REQ-002, REQ-003, REQ-005_
  _Acceptance: AC-002, AC-003, AC-005_
  _Verification: 原线程12／24槽读取、损坏／空／同库、两卡延迟和CP不足_
  _Depends: T001, T002_
- [x] T004 实现CP资源健康门禁、RAM诊断、共享暂存和栈／代码／段预算。
  _Requirements: REQ-001, REQ-004, REQ-005_
  _Acceptance: AC-001, AC-004, AC-005_
  _Verification: 实际CP资源诊断、旧指针保持、嵌套栈／共享缓冲及无SD写诊断_
  _Depends: T002, T003_
- [x] T005 完成严格来源／工具链／组件清单和独立新构建，执行相关CPU回归。
  _Requirements: REQ-005, REQ-006_
  _Acceptance: AC-005, AC-006_
  _Verification: 前像、连续账本、逆还原、容量与本地四项及原厂／快速切换_
  _Depends: T001, T002, T003, T004_
- [x] T006 进行固定身份有限QEMU复验，归档独立组件包、证据与明确剩余门禁。
  _Requirements: REQ-001, REQ-003, REQ-006_
  _Acceptance: AC-001, AC-003, AC-006_
  _Verification: 实际Qt与原帧、新状态、ST往返／菜单开关／正常退出；硬件项MANUAL_REQUIRED_
  _Depends: T005_

本轮T001～T006均指离线实施及明确边界内验证完成。最终46项CPU、2项QEMU身份及96原帧通过，研究组件归档988文件并重新读取校验；真实堆／成像／介质／机身仍MANUAL_REQUIRED，整体NOT_VERIFIED。详见verification.md。
