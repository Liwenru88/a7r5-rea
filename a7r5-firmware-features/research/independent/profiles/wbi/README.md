# WBI 标记 2→3

> **策略更新（2026-11-16）：本页原先采用的“首扇区清零”已废弃。** 正确做法是保留原厂快照，只把 `nflasha5` 头标记由 `WBI2` 改为 `WBI3`（偏移 `0x3` 的 1 字节 `0x32`→`0x33`），并按变化后的镜像重算 `part_image.sum`（CRC 由 `0ff04cda` 变为 `76ce0feb`）。清零后包内与设备都不再带有效头标记，2026-11-14 故障机回读即为此状态；恢复需写回完整已知 `WBI3` 首扇区。下文保留旧零清候选的复现步骤，只用于对照历史包，新包不要再走该分支。

在指定旧 4.18 上只调整 `nflasha5`。4.18 更新器先执行原厂的 WBI 清理，再写入包内镜像，原清零状态因此被 `WBI3` 覆盖。候选把最终写入的首扇区也置零，让包内状态与原厂清理动作一致。

## 实施与资源

1. 校验指定 4.18 DAT 和 `WBI3` 前像。只将偏移 `0x000–0x1ff` 的 512 字节置零，保持镜像长度 243,789,184 字节和所有后续数据。
2. 由 DAT 工具将该分区在 `part_image.sum` 的 CRC32 从 `76ce0feb` 更新为 `dfa823fc`。正常更新流程在结束前读回核对该分区镜像。
3. 独立解包复核全零首扇区及其余字节。候选仍为 4.18，预期 SHA-256 为 `03fc45513ac7612ed0b9e131f079d1b32c865cbf4ca8720c91ee6f1757a67fbc`。

新策略下的对应步骤：保留 `WBI3` 前像的全部 512 字节，只把偏移 `0x3` 改回 `0x33`（若输入为 `WBI2`），镜像 SHA-256 预期为 `eac727efd7af2142ddd9b8ae22387614eaaaba9dc9f04ce0434bf8e7c766d693`，CRC32 为 `76ce0feb`。

[故障与更新顺序](../../../native24-combined/4.18启动故障离线分析.md) · [正式构建入口的处理逻辑](../../../native24-combined/release417/container_package.py#L157) · [资源清单](resources.json)

## 复现与验收

完成[公共准备](../../README.md#公共准备)后执行。已有精确匹配的旧 4.18 时，可直接作为第三条命令的输入。

```sh
"$python" -B "$tool" native24 --base "$stock" --output "$out/native24"
"$python" -B "$tool" baseline418 --base "$out/native24/BODYDATA.DAT" --output "$out/baseline418"
"$python" -B "$tool" wbi --base "$out/baseline418/BODYDATA.DAT" --output "$out/wbi"
```

离线验收只允许 `nflasha5` 和分区校验表变化。故障机上的实际落盘、冷启动及 4.18 的其他启动环节仍待验证。 [本轮封包回执](verification.json)
