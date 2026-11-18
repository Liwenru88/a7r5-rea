# 实施任务

- [x] T001 独立 AP 覆盖层：原十九行＋十二行，撤销独立主菜单和 Fn 候选，严格 ELF／逆还原收据；追加两份图形资源的十二对编号图标。
  _Requirements: REQ-001, REQ-005_
  _Acceptance: AC-001, AC-005_
  _Verification: V2 构建与真实 AP 注册、描述符测试_
- [ ] T002 接入原生选择、预览及参数隔离，沿用十二款事务与失败回退。
  已完成定向 CPU 回放与原有四项补丁回归；统一页的真实 E4 成功仍被原厂初始化等待阻塞，不能勾选完成。
  2026-11-03进一步以当前e833…真实AP／CP及文件协议补齐十二款分别返回ST、FL2／FL3、快速切换和恢复场景，9项通过；原E4外部执行和原厂UI服务为明确夹具，整机验收不据此勾选。
  _Requirements: REQ-002, REQ-003, REQ-004_
  _Acceptance: AC-002, AC-003, AC-004_
  _Verification: V2 AP 指令及后端回归，失败路径和越界写观察_
  _Depends: T001_
- [ ] T003 独立 QEMU 清单与实际 Qt 按键，截图复验原生／FL2／FL3／十二款及失败恢复、页面生命周期。
  已有原生页面、图标和明确失败提示的阶段截图；失败后四轮顶层MENU开关及重新进入ST有真实像素证据。十二款逐一成功、失败刷新列表、故障恢复、Fn 与完整启动生命周期未完成。
  2026-11-03新增真实Qt全十二款名称／编号、ST、FL2／FL3及四轮MENU／ST重入复验，72原帧逐像素一致；只补齐菜单显示，十二款实际成功应用、完整Fn和整机电源／介质验收仍未完成。见[冷启动版补验](../../native24-combined/dependencies/native12-combined/verification/2026-11-03-unified-cold/README.md)。
  _Requirements: REQ-001, REQ-003, REQ-004_
  _Acceptance: AC-001, AC-003, AC-004_
  _Verification: V3 有限菜单隔离验证；完整启动单独记录限制_
  _Depends: T002_
- [x] T004 归档源码、摘要、原帧和验证结论，明确未验证项；历史包不覆盖。
  归档11次运行并逐像素核对236帧；旧4.10／4.11 DAT和冻结上游331文件摘要一致。T002／T003未通过项原样保留，本项完成仅表示阶段材料归档。
  _Requirements: REQ-005_
  _Acceptance: AC-005_
  _Verification: V0 引用／摘要及差异检查_
  _Depends: T003 阶段证据；不以完整验收通过作为失败归档前提_
