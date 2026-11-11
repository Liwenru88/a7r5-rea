# 照片 2.35:1 构图标记

基于原厂 4.00 生成 AP 单项候选。照片标记菜单提供开关、比例和透明度，2.35:1 用于构图辅助。保存照片的尺寸由原纵横比功能控制。需要 JPEG／HEIF 实际裁切时使用[十档纵横比](../photo-aspect/README.md)。

## 实施与资源

1. 继承标记功能的三个属性登记、原厂范围校验器和机型列 16 的 28 个支持位。
2. 原有整合代码的三个范围包装器、三个文件内登记指针及三个 RELA addend 保持相同代码和数据。
3. 从原厂 ELF 自己的 `e_phoff` 定位活动 RX Program Header。核对原段终点 `0x500fbb7`、同页零填充和下一段边界，再扩至 `0x500fc70`。整合基底的 PHDR 地址不可直接沿用。
4. 对 37 个变更范围逐一核对局部前像并做逆还原。只替换 USR 内的 `appFw.so`，原厂 CP、AVCAM 和图标来自基线。

[属性与重定位清单](../../../aspect-guide406/patch-plan.json) · [原始文件补丁实现](../../../native24-combined/dependencies/native12-combined/patches.py) · [原厂前像逐处记录](ap-patch.json) · [资源清单](resources.json)

## 复现

完成[公共准备](../../README.md#公共准备)后执行。

```sh
"$python" -B "$tool" photo-markers --base "$stock" --output "$out/photo-markers"
```

## 验收

新单项包以独立解包和字节白名单为证据。此前 QEMU 的菜单及参数选择来自历史候选，不能直接作为这份单项候选的取景叠加证据。复核时单独记录照片 M 模式的 2.35:1、透明度、横竖显示、原厂互斥和照片尺寸。 [历史界面证据](../../../aspect-guide406/README.md) · [本轮封包回执](verification.json)
