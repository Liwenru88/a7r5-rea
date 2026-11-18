# 排查与修复任务

- [x] T001 固定实机四组件／配置／启动标识并保留现有日志，建立只读证据。
  _Requirements: REQ-001_
  _Acceptance: AC-001_
  _Verification: SSH原回执、摘要、精确状态及日志_
- [x] T002 复现实际十二款配置及原UI资格／导航链，定位根因并建立失败回归。
  _Requirements: REQ-002_
  _Acceptance: AC-002_
  _Verification: 原生机器码／真实配置QEMU、最小失败测试_
- [x] T003 执行最小修复及相关兼容复验，绑定新组件身份。
  _Requirements: REQ-002, REQ-003_
  _Acceptance: AC-002, AC-003_
  _Depends: T002_
  _Verification: 失败回归转绿、必要QEMU与相关回归_
- [ ] T004 交付可审查修复、残余风险及带精确范围的机身验证方案。
  _Requirements: REQ-004_
  _Acceptance: AC-004_
  _Depends: T003_
  _Verification: 新旧摘要、回退条件、实际未验证项_

T003只完成离线修复。用户已确认三文件持久替换及正常重启；T004备份与预检完成，但/usr空间18.61 MiB不足以暂存111.73 MiB新文件，已在改挂载前停止，实机执行与验收仍未完成。建议改为完整升级包，路径和版本待确认。整体仍为NOT_VERIFIED，不以QEMU通过关闭实机故障。
