# 修复任务

- [x] T001 建立忙态误判及最后目标合并的失败回归，记录原AP摘要和观察结果。
  冻结旧候选的同一组最终回归出现7项预期失败，记录于before.xml；当前模块27项通过。
  _Requirements: REQ-001, REQ-002, REQ-004_
  _Acceptance: AC-001, AC-002, AC-004_
  _Verification: V2真实AP提交器及页面入口交错；明确服务夹具边界_
- [x] T002 实现非阻塞串行调度、按目标状态及原厂／生命周期保护。
  真实AP提交器／忙态／序列回放通过；worker终态与部分UI服务为明确夹具。QEMU实际观察到F12→F11→F10期间跳过F11，确认键等待时保留页面。
  _Requirements: REQ-001, REQ-002, REQ-003, REQ-004_
  _Acceptance: AC-001, AC-002, AC-003, AC-004_
  _Verification: 合并、失败、序列替换、原厂退出、MENU取消及Enter保护回放_
  _Depends: T001_
- [x] T003 构建独立候选，执行相关回归及有限QEMU观察，归档并明确整体验收缺口。
  27项模块、15项相关回归、13项环境合同通过；87帧逐像素一致，四轮顶层MENU／ST重入和三侧退出正常。旧DAT及上游331文件保持；原E4初始化阻塞使应用终态仍失败，整体验收保持NOT_VERIFIED，不封DAT。
  _Requirements: REQ-005, REQ-004_
  _Acceptance: AC-005, AC-004_
  _Verification: 收据／逆还原、受影响回归、真实帧／正常退出及摘要核对_
  _Depends: T002_
