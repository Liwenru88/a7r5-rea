# 原厂 C1–C6 与 SD 24 槽并存

在[十档纵横比候选](../photo-aspect/README.md)上单独加入 C1–C6。使用与现有 4.18 相同的六款配方和成像实现。这条路线使用无镜头 AF 改动的十档 CP。想从原厂 4.00 只装历史六款时使用[历史单项版](../factory-six-stock/README.md)。

## 实施与资源

- AP 复用原厂 C1–C6 槽位和调参逻辑，使用 249–254 选择值，并追加 68 份横竖名称资源。
- CP 复用历史 1215 字节原生色表和 108 字节联合增量。六款 Gamma 私有行 75–86 与 SD 槽行 51–74 分开。配方包含 Classic Neg.、Classic Chrome、Nostalgic Neg.、Astia、GR Positive Film、GR Negative Film。
- 现有 `build_legacy_six.py` 会锁定十档 AP、CP、AVCAM 和资源前像。该源实现目前依赖十档组件建立的早期 CP 页映射。封包增量只更新 `nflasha15`、`nflasha8` 和分区校验表，十档基线的 AVCAM 与图标直接复用。

[六款源码构建与测试](../../../firmware-runtime/README.md#原厂组-c1c6-六款固定滤镜) · [配方资产](../../../materials/upstream-default-six) · [资源清单](resources.json)

## 复现

完成[公共准备](../../README.md#公共准备)后执行。若已有精确匹配的十档比例 DAT，可直接作为输入。

```sh
"$python" -B "$tool" native24 --base "$stock" --output "$out/native24"
"$python" -B "$tool" photo-aspect --base "$out/native24/BODYDATA.DAT" --output "$out/photo-aspect"
"$python" -B "$tool" factory-six-native24 --base "$out/photo-aspect/BODYDATA.DAT" --output "$out/factory-six-native24"
```

## 验收

核对六款名称、颜色、Gamma 与 SD 组往返。SD 库与六款原厂槽独立，六款本身无需 SD BIN，24 槽需要配方时取 [24 槽输出](../native24/README.md)中的文件。原始 4.18 组合的启动故障仍需区别于本包。 [本轮封包回执](verification.json)
