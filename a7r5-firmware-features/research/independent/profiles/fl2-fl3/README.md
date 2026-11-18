# FL2／FL3 单项实施

基于锁定的原厂 4.00，复现已有桌面 `fl23` 单选路线。两款使用同一选择器、默认表和 CP 色彩数据布局，因此以一组交付。现有六款 C1–C6、声音、NTSC 提示分别由其他档案管理。

## 实施与资源

- AP 按原厂能力表开放两档。选择器将 FL2／FL3 分别映射到 CP 编号 19／20，初始和重置采用各自的原生基底默认字段。
- CP 保留 FL2／FL3 的原生 Gamma 路由，装入对应 CC1、矩阵和 Gamma 数据。共享空间保留布局，入口按单选逻辑生成。不能把矩阵数据和另一份 CP 的分支混装。
- 单项源由 `build_ap` 与 `build_cp` 以 `fl23=true`、其余开关为 `false` 生成。资源冻结 `nflasha15` 与 `nflasha8` 的定长增量，分区校验表由封包器派生。上游 4.36 的地区模板路线另见 24 槽文档。

[源构建器](../../../../a7r5-desktop/scripts/feature_builder.py) · [色彩与原生入口说明](../../../look-fl2-fl3/01_FL2和FL3启用实施细节.md) · [资源清单](resources.json)

## 复现

完成[公共准备](../../README.md#公共准备)后执行。

```sh
"$python" -B "$tool" fl2-fl3 --base "$stock" --output "$out/fl2-fl3"
```

## 验收

独立解包只接受 `nflasha15`、`nflasha8` 和对应 `part_image.sum` 的固定摘要。功能验收分别观察原厂 ST、FL2、FL3 往返、两档实际选择值、重置、取景和成片。FX2 捐赠数据的适配须以 A7R5 的 CP 消费链解释，原色彩矩阵数值与真机像素表现分开记录。 [本轮封包回执](verification.json)
