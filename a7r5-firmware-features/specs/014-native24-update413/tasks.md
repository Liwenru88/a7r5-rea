# 实施任务

- [x] T001 核验013组件及原回归／QEMU证据，锁定4.13镜像与签名输入。
  _Requirements: REQ-001, REQ-002, REQ-003_
  _Acceptance: AC-001, AC-002, AC-003_
  _Verification: 固定摘要、原回执及新拒绝测试_
- [x] T002 在新目录扩展USR、整合CP及原模板，签名生成4.13并独立完整回读。
  _Requirements: REQ-002, REQ-003_
  _Acceptance: AC-002, AC-003_
  _Verification: 全树／inode、只读e2fsck、完整明文与归档、全部帧和OpenSSL_
  _Depends: T001_
- [x] T003 发布本地4.13交付目录、校验清单及说明，更新索引并验证旧工件保持。
  _Requirements: REQ-004_
  _Acceptance: AC-004_
  _Verification: 新目录来源与摘要一致、无私钥／合成BIN、旧包摘要保持_
  _Depends: T002_
