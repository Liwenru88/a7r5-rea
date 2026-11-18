# 原厂 C1–C6 固定滤镜历史单项版

基于原厂 4.00，使用已有 `looks` 单选构建器。C1–C6 分别是 Classic Neg.、Classic Chrome、Nostalgic Neg.、Astia、GR Positive Film、GR Negative Film。配方随 CP 内置，从原厂创意外观进入。

## 实施与资源

AP 恢复六个槽位的选择映射和各模式默认值，CP 处理 249–254 的六个选择值并消费原生色表、Gamma、矩阵和色度。68 份横竖语言名称资源按原厂 UXC 格式追加，包含完整前像和目标验证。选用 `looks=true`，其他三个历史开关关闭。需要同时保留当前 24 槽 SD 导入时使用[当前链路版](../factory-six-native24/README.md)。

[历史实施细节](../../../look-factory-six/02_六款自定义滤镜实施细节.md) · [六款配方资产](../../../materials/upstream-default-six) · [历史配方和资源锁](../../../materials/recipes.json) · [资源清单](resources.json)

## 复现与验收

完成[公共准备](../../README.md#公共准备)后执行。

```sh
"$python" -B "$tool" factory-six-stock --base "$stock" --output "$out/factory-six-stock"
```

独立核对 USR、CP 和分区校验表。功能验收逐个比较名称、选择值、原厂 ST 返回、横竖语言资源和原厂预览，区分数值回放与实际成片。 [本轮封包回执](verification.json)
