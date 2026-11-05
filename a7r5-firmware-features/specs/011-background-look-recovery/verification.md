# 验证记录

Feature ID: 011-background-look-recovery
Status: NOT_VERIFIED

本轮只验收离线实现与真实菜单交互，整体仍为`NOT_VERIFIED`，相机连接、真实介质、成像及DAT封包不在本次范围内。

## 当前证据

| Evidence | Command / Step | Result | Scope |
|---|---|---|---|
| E-001 | 010组件执行新增原厂显示、无操作自动回退、损坏日志修复三项回归；`.local/native24-background-red-20261103-01.xml` | 三项均按预期失败：标题被覆盖、CP仍停在失败目标、日志没有自动修复 | AC-001／002的旧行为复现 |
| E-002 | 新组件`cc3dde64…`上运行`test_background_interaction.py`及两项旧E4／回退用例；`.local/native24-background-20261103-01/directed.xml` | PASS，12项，137.91秒 | 原厂显示与写保护、无人工回退、日志修复、迟到E4、最后目标、有限重试 |
| E-003 | 复用`test_native_parameters_delegate_and_custom_parameters_cannot_write(candidate)`；`.local/native24-background-20261103-02/native-parameter-contract.json` | PASS | 正常原厂参数读取／八项编辑／入口委派，附加值写隔离 |
| E-004 | 独立QEMU实验的`unittest discover`及`run_validation.py`；运行`native-native12-410-xwuaneij` | PASS，2项固定身份检查、107次真实Qt操作；107原帧重新生成PNG逐一一致；Qt worker／AP QMP／CP均退出0 | 原厂标题及参数、ST调参入口、PT／NT往返、24槽双向遍历、FL2／FL3、四轮菜单往返 |
| E-005 | 新组件上一次完整相关CPU回归；`verification/2026-11-03-background-01/tests/cpu/session-result.json`及原始XML | PASS，56项，653.54秒；源码前后不变、组件与构建收据一致 | 最终集成门禁 |
| E-006 | 010封存988项SHA清单、旧4.10／4.11 DAT摘要、两次独立新构建四组件比较 | PASS，历史材料未变，新构建组件一致 | AC-005 |
| E-007 | `native24-combined/archive.py`以完整CPU结果、新清单、107原帧和实际Qt／退出回执归档 | PASS，1036文件及压缩包逐成员重新读取校验 | AC-005 |

当前AP为`cc3dde6456dbcb40378bb93e2cbf64c661ee3543673028c7e560e62784523467`，CP为`35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300`，CP及两份图形资源相对010不变。构建02在归档门禁适配后重新生成，四组件与QEMU所用构建01完全相同；最终回归绑定构建02的源码和收据。

| Acceptance | Status | Evidence |
|---|---|---|
| AC-001 原有界面及正常操作 | PASS（离线） | E-002／003／004／005 |
| AC-002 无需人工的后台回退 | PASS（机器码＋明确服务夹具） | E-001／002／005 |
| AC-003 保护、有界协调及最后目标 | PASS（离线） | E-002／004／005 |
| AC-004 克制反馈、删除ST修复要求 | PASS（离线） | E-002／004／005 |
| AC-005 独立、可追溯、无设备交付 | PASS | E-004／005／006／007 |

归档入口：[本轮研究组件](../../native24-combined/verification/2026-11-03-background-01/README.md)、[结果](../../native24-combined/verification/2026-11-03-background-01/results.json)、[交互说明与截图](../../native24-combined/后台恢复交互优化说明.md)。压缩包SHA256为`9af12386f3c47fbd9d0464bba68e7c68422315c7551e70a0c6386836c4aa6d3c`。

实际最终命令（仓库根目录）：

```sh
A7R5_NATIVE24_BUILD="$PWD/.local/native24-background-20261103-02" \
A7R5_NATIVE24_EVIDENCE="$PWD/.local/native24-background-20261103-02/final-cpu" \
.venv/bin/python -m pytest -q a7r5-firmware-features/native24-combined/tests \
  --tb=short --junitxml=.local/native24-background-20261103-02/final-regression.xml
```

QEMU命令及新输出路径见[独立实验说明](../../../a7r5-qemu/experiments/native24-background-menu/README.md)。没有提交、推送、签名或连接相机。

## QEMU边界

最终ST／PT／NT截图对应`command_state=5`、`native_E4_inflight=1`、`recovery_required=1`，没有把后台状态改成成功。标题和参数区正常显示，危险写入继续受保护。原生E4完整成像初始化的QEMU缺口尚未解决；本轮不能声称滤镜成功应用或成像通过。

真实UI截图来自原客体帧，没有绘制替代菜单；首次失败驱动现场保留，仅更正调参确认键返回上级菜单的脚本预期。机身／真实存储／色彩／声音／照片叠加验收均为`MANUAL_REQUIRED`。
