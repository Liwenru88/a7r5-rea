# 手动热导入调查与验证

Feature ID: 007-manual-native12-import
Status: NOT_VERIFIED
Updated: 2026-11-03

当前范围已变更为保持冷启动导入；007方案状态为DEFERRED，功能未实现，以下未通过项只属于搁置的热导入候选，不作为本次冷启动版缺陷或发布门禁。运行时代码不变，继续原有SD冷启动导入与机内持久化。

本轮产出需求、设计与任务，没有实现热导入。用户确认的四项行为记录在[requirements.md](requirements.md)，待评审方案及G1门禁见[design.md](design.md)。没有连接相机或物理存储，没有改AP／CP运行时代码、冷启动行为、旧包或冻结上游。

2026-11-03语义修订：按用户最新要求，成功结果从“解除覆盖且保留原厂外观”改为“实际切换到ST”。REQ-001／AC-001明确无独立关闭项；REQ-003／AC-003增加原厂ST选择／刷新及保存／恢复确认；REQ-005／AC-005增加原厂外观与内部编号不一致的恢复检查。只更新规格和待执行验证，既有2项CP基线不构成ST验证。

## 实际证据

| Evidence | Code State | Command / Step | Result | Scope |
|---|---|---|---|---|
| E-001 | 当前冻结十二款上游及006候选 | 只读核对启动、Fsys、重载、CP代际、名称目录及006调度所有者 | 完成调查 | 重载函数固定-1；每库522152字节，旧库保留；SEAL公布新库；名称上限16。只读结论不代替热导入行为验证 |
| E-002 | 既有合并CP及现有回归 | 根目录设置`A7R5_NATIVE12_BASELINE="$PWD/.local/native12-combined-baseline-01"`后执行下列pytest命令 | 2 passed，exit 0，13.08秒 | 同配方复用及不同配方的堆资源失败保护；只证明显式预算模型，不证明实机剩余堆或安全热复用 |

实际命令：

```sh
A7R5_NATIVE12_BASELINE="$PWD/.local/native12-combined-baseline-01" .venv/bin/python -m pytest -q \
  a7r5-firmware-features/native24-combined/dependencies/native12-combined/tests/test_runtime_receiver.py::test_resume_reuses_sealed_bank_with_no_allocation_and_late_put_is_rejected \
  a7r5-firmware-features/native24-combined/dependencies/native12-combined/tests/test_runtime_receiver.py::test_shared_heap_resource_failure_preserves_published_generations \
  --junitxml=.local/native12-manual-import-baseline-20261103.xml
```

第二项在1048576字节显式预算内分配两份522152字节库，第三份拒绝且旧库未改。不能由此推断实机固定支持几次热导入；它用于确认累计分配策略不满足重复热导入的目标。

代码入口：

- [启动、机内保存和重载占位](../../native24-combined/dependencies/native12-combined/upstream/firmware/r5/src/import/r5_stage413_thread.c)
- [原厂Fsys边界及调用者前置条件](../../native24-combined/dependencies/native12-combined/upstream/firmware/r5/src/import/r5_fsys_adapter.h)
- [CP参数库接收与代际保留](../../native24-combined/dependencies/native12-combined/upstream/firmware/r5/src/cp/cp_stage413_probe.c)
- [CP选择及关闭view](../../native24-combined/dependencies/native12-combined/upstream/firmware/r5/src/cp/custom_filter423.c)
- [名称目录发布与上限](../../native24-combined/dependencies/native12-combined/upstream/firmware/r5/src/import/r5_filter_names423.c)
- [现有CP资源回归](../../native24-combined/dependencies/native12-combined/tests/test_runtime_receiver.py)
- [当前统一入口调度](../../native24-combined/dependencies/native12-combined/unified-look.c)

## 未验证与下一步

| Acceptance | Status | 说明 |
|---|---|---|
| AC-001 | NOT_RUN | 同级菜单及卡槽选择尚未实现 |
| AC-002 | NOT_RUN | 当前仍保留旧自动SD导入；本轮未改启动行为 |
| AC-003 | NOT_RUN | 运行中导入、解除覆盖及原厂ST实际选择／保存成功链尚未实现；内部0不能替代ST验证 |
| AC-004 | NOT_VERIFIED | 已确认旧资源限制；读者退出及有界复用方案尚需G1证据 |
| AC-005 | NOT_RUN | 含原厂外观状态的提交／恢复事务未实现；须覆盖内部0但原厂非ST的状态 |
| AC-006 | NOT_RUN | 导入与006调度／媒体生命周期联动未实现 |
| AC-007 | NOT_VERIFIED | 规格和基线可追溯，新候选／QEMU功能验证未开始 |

用户报告旧版本实机不存在E4初始化阻塞；当前QEMU成像状态模型缺口仍独立保留。它们都不能为新热替换的指针生命周期、掉电恢复或设备安装授予通过。
