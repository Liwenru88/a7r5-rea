# 实施任务

- [x] T001：新增强制新候选、质量警告发布与非法数据拒绝的回归用例，先确认失败。
  _Requirements: REQ-1, REQ-2, REQ-3, REQ-4_
  _Acceptance: AC-1, AC-2, AC-3, AC-4_
  _Verification: V1 定向回归_
- [x] T002：实现单一路由、候选池与发布策略，保留历史重放与读取。
  _Requirements: REQ-1, REQ-2, REQ-3, REQ-4_
  _Acceptance: AC-1, AC-2, AC-3, AC-4_
  _Depends: T001_
  _Verification: V2 相关模块回归、真实 MPS 缩减预算链路_
- [x] T003：更新工作台入口、警告文案、说明文档并复验页面。
  _Requirements: REQ-5_
  _Acceptance: AC-5_
  _Depends: T002_
  _Verification: V1 前端语法、V2 页面与预览导出一致性_
- [x] T004：记录实际证据、未验证范围与限制。
  _Requirements: REQ-1, REQ-2, REQ-3, REQ-4, REQ-5_
  _Acceptance: AC-1, AC-2, AC-3, AC-4, AC-5_
  _Depends: T003_
  _Verification: verification.md 与变更检查_
