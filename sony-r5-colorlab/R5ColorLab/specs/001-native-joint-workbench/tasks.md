# 任务

- [x] T001 抽取共享求解器并建立通用数据与验收适配，补回归。
  _Requirements: REQ-1, REQ-3_ _Acceptance: AC-1, AC-3_ _Verification: 定向测试、CPU/MPS和BIN回读_ _Boundary: 原格式与现有实验CLI_
- [x] T002 暖金日光筛查软约束与阶段候选策略，确认最终配置并固定协议。
  _Requirements: REQ-2, REQ-3_ _Acceptance: AC-2, AC-3_ _Depends: T001_ _Verification: GPU真实运行、完整开发复算、检查点_
- [x] T003 用固定配置完整运行推荐三款，锁定后最终评分，生成对照与十五款合并副本。
  _Requirements: REQ-3, REQ-4_ _Acceptance: AC-3, AC-4_ _Depends: T002_ _Verification: 三款GPU、留出及新相位、原十二款字段比较_
- [x] T004 新流程接入工作台标准profile与日志、预览、导出，重构相关说明和旧入口兼容。
  _Requirements: REQ-1, REQ-5_ _Acceptance: AC-1, AC-5_ _Depends: T002_ _Verification: 服务集成、项目保存导出、页面复验_
- [x] T005 完成相关回归、成果工程和交付文档，记录实际限制。
  _Requirements: REQ-4, REQ-5, REQ-6_ _Acceptance: AC-4, AC-5, AC-6_ _Depends: T003, T004_ _Verification: 相关回归与最终摘要、截图、交付文件_
