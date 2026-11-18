# 电子快门声音

基于原厂 4.00，复现 CP `type1` 声音模式的单项路线。声效仍由机身现有资源和原厂播放链提供。

## 实施与资源

在 `0x47f622` 接入条件包装器，并将代码放到已核对的空白映射区。包装器沿用原模式赋值和返回地址，按既有条件决定是否发出电子快门声。源构建器选择 `sound=true`，其余三项关闭。发布增量只替换 `nflasha8` 内的 `cpapp-b.bin`，原有 AP 菜单和 FAT 文件布局从输入保留。

[声音状态和撤回方案记录](../../../photo-electronic-shutter-sound/04_电子快门声音启用实施细节.md) · [源构建器](../../../../a7r5-desktop/scripts/feature_builder.py) · [资源清单](resources.json)

## 复现与验收

完成[公共准备](../../README.md#公共准备)后执行。

```sh
"$python" -B "$tool" electronic-shutter --base "$stock" --output "$out/electronic-shutter"
```

校验 `nflasha8` 和分区表，CP 之外的可执行组件使用原厂字节。功能验收覆盖电子快门、机械快门、静音、单张和连拍，并将真实出声与指令回放分开记录。 [本轮封包回执](verification.json)
