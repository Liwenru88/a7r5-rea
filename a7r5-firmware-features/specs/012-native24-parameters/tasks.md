# 实施任务

- [x] T001 锁定原参数包／回调结构，新增身份、保存及参数通路的失败回归。
  _Requirements: REQ-001, REQ-002, REQ-003_
  _Acceptance: AC-001, AC-002, AC-003_
  _Verification: 精确前像及实际AP／CP执行_
- [x] T002 实现色彩SHA256、独立八项状态与有界机内存储，导入及启动接线。
  _Requirements: REQ-002, REQ-004_
  _Acceptance: AC-002, AC-004_
  _Verification: 同配方／换槽／新内容／损坏／发布故障与BIN保持_
  _Depends: T001_
- [x] T003 接入原生参数打包、固定事务快照及失败回退；保持原厂路径。
  _Requirements: REQ-003, REQ-004_
  _Acceptance: AC-003, AC-004_
  _Verification: 原CP字段／消费与连续输入及E4故障回放_
  _Depends: T002_
- [x] T004 开放附加滤镜的原八项页面、编辑／显示／重置和异步保存反馈。
  _Requirements: REQ-001, REQ-004_
  _Acceptance: AC-001, AC-004_
  _Verification: 虚拟身份隔离、实际回调／显示及原厂编辑保持_
  _Depends: T003_
- [x] T005 新候选构建、相关回归与独立QEMU实际八项编辑、往返及截图，归档边界。
  _Requirements: REQ-005_
  _Acceptance: AC-005_
  _Verification: 固定输入、原帧／PNG、真实状态与正常退出，源码及组件摘要_
  _Depends: T004_

T001～T005离线范围已完成：70项相关CPU回归、80次原厂参数委派、2项QEMU固定身份、106次实际Qt操作及106原帧／PNG核对通过。归档1048文件及压缩包逐成员重新读取校验通过。相机、真实介质、像素效果及安装仍未验收，整体NOT_VERIFIED；未生成DAT。
