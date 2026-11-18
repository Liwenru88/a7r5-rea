# 十档照片纵横比

在精确 4.17 上加入真实裁切。四个原厂比例为 3:2、4:3、16:9、1:1，新增 17:6、65:24、5:4、7:6、1.91:1、2.35:1。取景显示构图范围，JPEG／HEIF 改有效区域，RAW 维持完整幅面。新增选择仅在当前开机期间记忆。

## 实施与资源

1. 使用 AP 构建器扩展原厂描述符，绑定菜单私有行和 `0xe0–0xe5` 消息。回到原厂比例时清除私有选值，避免下一张沿用旧裁切。
2. 使用 CP 构建器将比例在拍摄任务内锁存。沿用原有请求布局和画布，调整 JPEG／HEIF 有效区域。使用默认 4.17 CP `35eb911d…`，因此本增量不含镜头 AF 改动。
3. 使用 AVCAM 构建器按格式和槽位接收几何，保持 LIRO 布局与文件长度。一起生成两份图标和 68 份横竖文字资源。
4. 对工作副本内 USR 做文件扩展和 `e2fsck -fn`，在两个 FAT 分区等长替换 CP 与 AVCAM。最终只更新 `nflasha15`、`nflasha8`、`nflasha3` 和对应分区校验表。

[四个源构建器和 19 项回放命令](../../../photo-aspect-ratios/src/README.md) · [资源清单](resources.json)

## 复现

完成[公共准备](../../README.md#公共准备)后执行。若已有匹配摘要的 4.17 DAT，可跳过第一条。

```sh
"$python" -B "$tool" native24 --base "$stock" --output "$out/native24"
"$python" -B "$tool" photo-aspect --base "$out/native24/BODYDATA.DAT" --output "$out/photo-aspect"
```

## 验收

逐档核对菜单、取景横竖构图、3:2 往返、两张在途任务隔离和 RAW-only。以 9504×6336 夹具，1.91:1 和 2.35:1 预期 JPEG／HEIF 有效区域为 9504×4976、9504×4048。成片尺寸、实际 LCD／EVF 和真机启动单独验收。 [本轮封包回执](verification.json)
