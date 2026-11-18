# 手动热导入任务

Status: DEFERRED

2026-11-03用户决定保持冷启动导入。本方案不纳入当前版本，T002～T006保留未完成但不继续执行；T001只代表已经完成的调查。没有热导入代码需要回退，不删除历史设计。

产品行为已确认；实施范围和新风险见design.md。当前仅完成只读调查与现有基线测试，尚未编辑运行时代码。

最新澄清：没有独立关闭项；导入成功须按原厂逻辑实际回到ST。内部自定义编号0不等于ST已生效，T002～T005按此验证，不改变既有基线结果。

- [x] T001 核对冷启动、重载空接口、CP保留代际与名称目录限制，记录需求及现有基线。
  _Requirements: REQ-001, REQ-002, REQ-004, REQ-007_
  _Acceptance: AC-001, AC-002, AC-004, AC-007 的调查基础，不表示功能通过_
  _Verification: 代码所有者及两项真实CP机器码回归；verification.md E-001／E-002_

- [ ] T002 完成G1读者生命周期与内存方案验证，固化可实施设计。
  _Requirements: REQ-004, REQ-006_
  _Acceptance: AC-004, AC-006_
  _Verification: 持有／退出点、导入页至原厂ST选择／保存路径源绑定，CP及名称峰值预算，保留旧读者时拒绝复用、退出后重复复用；不将SELECT0／E4回复当成释放证明_
  _Boundary: 未取得证据不得推进活跃库覆写或释放；若无法证明，保留门禁且不得宣称实现完成_
  _Depends: T001_

- [ ] T003 实现单一导入所有者、固定卡槽读入及准备／提交／恢复事务。
  _Requirements: REQ-003, REQ-004, REQ-005, REQ-006_
  _Acceptance: AC-003, AC-004, AC-005, AC-006_
  _Verification: 真实AP／CP协议、内存文件、精确回执、原厂ST实际生效及保存、候选提交与恢复故障；内部0但原厂仍为PT等状态不得报成功；跨过旧资源上限且内存有界_
  _Boundary: 使用G1已经证明的布局与生命周期，不修改冻结upstream；协议和恢复文件的具体格式先更新design_
  _Depends: T002_

- [ ] T004 改为机内启动读取，兼容已有机内v4配方和选择文件，补齐未完成事务恢复。
  _Requirements: REQ-002, REQ-005, REQ-007_
  _Acceptance: AC-002, AC-005, AC-007_
  _Verification: 卡上不同文件也不导入、SD打开次数0、无配置／损坏配置仍能进原厂与导入入口、提交阶段断点恢复；导入成功后的ST可恢复，普通历史编号0不被强制改成ST_
  _Depends: T003_

- [ ] T005 增加同级导入页面、目录代际刷新及006快速切换互斥。
  _Requirements: REQ-001, REQ-003, REQ-006_
  _Acceptance: AC-001, AC-003, AC-006_
  _Verification: 原注册树、卡槽映射、无独立关闭项、成功后实际聚焦ST、异步状态／取消、旧意图不重放、同掩码改名也刷新；ST／PT／FL2／FL3走各自原厂路径_
  _Depends: T003, T004_

- [ ] T006 独立构建与有限QEMU／相关回归，归档交付边界。
  _Requirements: REQ-007_
  _Acceptance: AC-007，以及AC-001／AC-003的实际菜单证据_
  _Verification: 源摘要／严格前像／逆还原、AP与CP匹配、原始帧／PNG、MENU往返、正常退出、所有AC及实机未验证项分别记录_
  _Boundary: 不连接相机，不覆盖旧DAT，不把重启后才生效或模型成功位称为热导入通过_
  _Depends: T004, T005_
