# 验证记录

Feature ID: 012-native24-parameters
Status: NOT_VERIFIED

本轮只验收离线实现与真实菜单操作，整体仍为`NOT_VERIFIED`。相机／真实介质／实际成像／升级包均未操作，011证据只作历史基线。

## 当前证据

| Evidence | 实际执行 | 结果与边界 |
|---|---|---|
| E-001 | 011执行新增八项显示回归；04执行ST工作值与默认值隔离回归 | 均按预期失败：原来八项隐藏、04误读取ST工作字段；QEMU失败现场另保留 |
| E-002 | 02八项参数集合、03四项边界、最终07三项定向检查 | 分别8项、4项、3项PASS；最终定向93.71秒；均绑定各自组件，不能替代最终全回归 |
| E-003 | 当前真实AP叠加→原CP任务分派→原刷新快照→C4上下文→锐度／颜色消费窗口 | 八项字段一致，锐度／精细度及颜色派生值有可执行断言；帧元数据及E4外部执行是明确夹具，非像素效果证明 |
| E-004 | 独立QEMU固定身份检查与真实Qt驱动；`native-native12-410-a20dwgjz` | PASS：2项固定身份、106次操作、106原帧与PNG一致；八项逐项编辑、重入保留、确认重置、四轮菜单开关与ST返回；Qt／AP／CP退出0 |
| E-005 | 当前07一次完整相关CPU回归；原始XML及`regression/session-result.json` | PASS：70项，1152.45秒；退出0、源码前后不变、完整相关集合，AP／CP与构建收据一致 |
| E-006 | 独立07／08四组件重建、原厂80次参数委派、010／011清单及旧DAT摘要 | PASS：四组件完全一致，原厂委派保持，010的988项、011的1036项及旧4.10／4.11 DAT未变；CP和两图形资源保持011 |
| E-007 | 当前候选归档门禁；`verification/2026-11-03-parameters-01` | PASS：1048项摘要清单、同组件及来源、八项编辑／重入／重置、原帧和正常退出门禁，压缩包逐成员重新读取核对 |

AP：`e0ef19eae2be9873946e61ddf52ae72f60cef767b1cea4325268a7f1bfa8d165`。

CP：`35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300`。AP BSS为290520字节，RX实际67912字节，128KiB限额；私有RW位于`0x8eb0000`，不与统一菜单段重叠。CP代码7544字节，堆请求947000字节；真实余量未测量。

最终回归命令（仓库根目录）：

```sh
A7R5_NATIVE24_BUILD="$PWD/.local/native24-parameters-20261103-07" \
A7R5_NATIVE24_EVIDENCE="$PWD/.local/native24-parameters-20261103-07/regression" \
.venv/bin/python -m pytest -q a7r5-firmware-features/native24-combined/tests \
  --tb=short --junitxml=.local/native24-parameters-20261103-07/regression.xml
```

QEMU命令见[独立实验说明](../../../a7r5-qemu/experiments/native24-parameters-menu/README.md)。最终清单为`build/native24-parameters-menu-20261103-03/manifest.json`，只读状态2404字节，仅采样生产getter，不改成功状态。

| Acceptance | 状态 | 证据 |
|---|---|---|
| AC-001 八项编辑、范围和重置 | PASS（离线） | E-002／004／005／006 |
| AC-002 身份保存及重导入隔离 | PASS（机器码与明确文件夹具） | E-001／002／005 |
| AC-003 原生参数与CP消费 | PASS（消费窗口，非实际像素） | E-003／005 |
| AC-004 固定快照、最后目标和失败回退 | PASS（离线） | E-002／005 |
| AC-005 可追溯交付与QEMU截图 | PASS | E-004／005／006／007 |

归档：[研究组件与证据](../../native24-combined/verification/2026-11-03-parameters-01/README.md)、[结果](../../native24-combined/verification/2026-11-03-parameters-01/results.json)、[交付说明与截图](../../native24-combined/八项调参交付说明.md)。压缩包SHA256：`4e6bde0421db5661c20275b7fea5f692d1a610e9a455829a8b17196e842a7546`。没有提交、推送、签名或设备操作。

## 验收边界

八项实际工作值从`0/0/0/0/0/4/3/1`改为`1/1/1/1/1/5/4/2`，重新进入保留，原重置框确认后恢复初始值。QEMU最后`command_state=5`、`native_E4_inflight=1`、`recovery_required=1`，附加项显示“等待切换”；这些值未获原E4应用／保存确认。菜单验证与CPU文件／CP消费证据分开，不将截图当成成功应用证明。

真实LCD／EVF／JPEG、介质掉电、全模式适用性、堆与线程高水位及机身安装验收仍为`MANUAL_REQUIRED`，不在本次禁止设备操作的范围内。新增13～24号是合成容量测试配方，不能作为新增成品滤镜交付。
