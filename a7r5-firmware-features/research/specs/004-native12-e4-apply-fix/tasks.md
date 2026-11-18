# 修复任务

- [x] T001 原厂E4链路观察与真实失败复现，定位阻断点。
  - _Requirements: REQ-001, REQ-004_
  - _Acceptance: AC-001, AC-004_
  - _Verification: 原执行入口/返回、底层请求、生产状态和正常退出；保留失败证据_
  - 已定位公共队列C3/触控及后续初始化依赖；UPM轮询阻塞由原厂DEBUG频率锁解除。完整启动仍缺0x4073/0x2040状态通知。
- [x] T002 最小修复及失败／恢复回归，保持生产完成门禁。
  - _Requirements: REQ-001, REQ-003, REQ-004_
  - _Acceptance: AC-001, AC-003, AC-004_
  - _Depends: T001_
  - _Verification: 真实原厂执行完成；故障时不误报成功，恢复可重试；身份拒绝_
  - 已修复0x20f0001进入原D9产生重复请求的问题。新AP在菜单隔离场景通过24次原E4及CP／文件交叉检查；错误第二次SELECT回执稳定失败、回退6并可手动重试7；不代表完整启动通过。
- [ ] T003 十二项、关闭及反向／重复切换的Qt验证并归档。
  - _Requirements: REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-002, AC-003, AC-004_
  - _Depends: T002_
  - _Verification: CP/AP/原E4/选择文件交叉核对、原帧与PNG、四轮MENU往返和正常退出_
  - 最终新AP隔离运行uielh6z1：12正向、12反向含关闭、重复选择无新事务；41原帧／PNG、41 Qt点击、AP／CP／worker退出0。故障运行32tf4to3另25帧与点击通过。缺完整启动及四轮MENU往返，保持未完成。
