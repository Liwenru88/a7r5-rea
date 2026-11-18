# 关闭指定 NTSC 提示

基于原厂 4.00，跳过两处已定位的 NTSC 制式提示路径。适用范围是对应的提示调用，视频制式、帧率及其他警告仍走原流程。

## 实施与资源

从 [历史 AP 方案](../../../video-ntsc-prompt/03_关闭NTSC提示实施细节.md)核对两个条件路径和完整前像。当前资源由 `ntsc=true` 单选的 AP 结果派生，对 `appFw.so` 的两个 AArch64 写点做定长替换，CP 保持输入。与旧 `reproduce.py --feature ntsc-only` 的历史封包相比，这份档案只复现提示功能，独立的 WBI 处理见[启动保护](../wbi/README.md)。 [源构建器](../../../../a7r5-desktop/scripts/feature_builder.py) · [资源清单](resources.json)

## 复现与验收

完成[公共准备](../../README.md#公共准备)后执行。

```sh
"$python" -B "$tool" ntsc --base "$stock" --output "$out/ntsc"
```

验证只允许 `nflasha15` 与对应分区校验表变化。功能验收需要原触发条件下提示不再弹出，PAL／NTSC 实际制式和录像帧率正常，并验证其他提示路径。 [本轮封包回执](verification.json)
