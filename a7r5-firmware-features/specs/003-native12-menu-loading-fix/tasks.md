# 修复任务

- [x] T001 定位中文方框的原生文字接口／字体根因，建立回归并最小修复。
  - _Requirements: REQ-001, REQ-005_
  - _Acceptance: AC-001, AC-005_
  - _Verification: 保留旧截图，原生接口／字形证据及新组件定向验证_
- [x] T002 补QEMU的真实BIN读取、内部存储和CP消息处理边界。
  - _Requirements: REQ-002, REQ-003, REQ-005_
  - _Acceptance: AC-002, AC-003, AC-005_
  - _Verification: 原AP状态机和真实CP代码、参数CRC及匹配ACK；失败不发布名称_
- [ ] T003 对十二项进行真实Qt截图复验，核对组件、像素和正常退出，交付修订结果。
  - _Requirements: REQ-001, REQ-002, REQ-004, REQ-005_
  - _Acceptance: AC-001, AC-002, AC-004, AC-005_
  - _Verification: 十二简称／中文全称可读、菜单往返、原始帧与PNG一致、QMP退出、旧材料保持_
  - 已完成十二项右栏全名截图、92帧逐像素核对、四轮MENU往返和正常退出；`Portra400`左列简称仍裁切，故不将本项无保留勾为完成。原生E4应用未通过，保留真实失败提示。详见verification.md。
