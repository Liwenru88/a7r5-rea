# 旧 4.18 故障对照基线

从精确 4.17 恢复旧 4.18 发布文件，预期 DAT SHA-256 为 `2354e2639ad781162bebbd152b831df72134f1ac212b4ee7a418a4e380c24fef`。该历史组合包含 24 槽、十档裁切、六款和镜头 AF 组件，原始 WBI 为 `WBI3`。该包曾在机身更新后无法启动，此处只用于故障对照和 WBI 修复输入。

## 复现

完成[公共准备](../../README.md#公共准备)后执行。

```sh
"$python" -B "$tool" native24 --base "$stock" --output "$out/native24"
"$python" -B "$tool" baseline418 --base "$out/native24/BODYDATA.DAT" --output "$out/baseline418"
```

该增量由固定 4.17 和旧 4.18 的独立解包比较生成，只记录 `nflasha3`、`nflasha8`、`nflasha15` 三个发生变化的镜像，分区校验表自动重建。固定签名和输出摘要用于识别历史文件。 [源封包回执](../../../native24-combined/releases/4.18/verification.json) · [资源清单](resources.json) · [本轮封包回执](verification.json)
