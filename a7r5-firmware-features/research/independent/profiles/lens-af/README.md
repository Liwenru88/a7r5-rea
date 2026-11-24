# 镜头 AF 能力过滤

在精确 4.17 的 CP 上单独加入自动兼容模式适配。它让五个指定消费者保留镜头已上报的能力。原厂分类器、强制兼容模式、镜头协议和未上报的能力维持原有处理。

## 实施与资源

1. 核对 4.17 CP 前像 `35eb911d27be…`。
2. 用 `lens_af.S` 编译 Thumb 辅助代码，固定在 `0xbef780`，确认末尾不超过 `0xbef7c0`。检查五处原始调用指令后修改，输出 CP 摘要 `530b45341bd1…`。
3. 等长替换 `nflasha8` 内的 `cpapp-b.bin`。AP、AVCAM、原厂纵横比资源和 WBI 使用输入版本。

[源码](../../../lens-af-compat/src/lens_af.py) · [移植记录和回放命令](../../../firmware-runtime/A7M4功能移植记录.md#镜头-af-能力过滤) · [五处补丁回执](cp-patch.json) · [资源清单](resources.json)

## 复现与验收

完成[公共准备](../../README.md#公共准备)后执行。若已有匹配 `resources.json` 的 4.17 DAT，可直接将它用作 `--base`。

```sh
"$python" -B "$tool" native24 --base "$stock" --output "$out/native24"
"$python" -B "$tool" lens-af --base "$out/native24/BODYDATA.DAT" --output "$out/lens-af"
```

归档变化应只有 `nflasha8` 和分区校验表。原生回放核对分类、自动／强制分流和逐位发布。实际镜头 AF-C、连拍和能力上报待实镜验收。呼吸补偿和镜头专属校准属于其他路径。 [本轮封包回执](verification.json)
