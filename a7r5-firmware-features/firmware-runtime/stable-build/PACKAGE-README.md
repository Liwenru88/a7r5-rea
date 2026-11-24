# 4.31 稳定版：自定义照片纵横比（JPEG / HEIF 裁切）

## 身份
- 目标机身：Sony ILCE-7RM5 / A7R V；唯一原厂基底为官方 4.00 `BODYDATA.DAT`。
- 包版本号：4.31（当前最新稳定主线）。
- 底层布局：严格保持 `WBI3` 不变、`nflasha15` 修改 4 个文件（`appFw.so`、`libmpr.so`、`image_00_23_IPSX.uxc`、`image_00_32_IPSX.uxc`）、`nflasha8` 更新 `cpapp-b.bin`、`nflasha3` 原簇链更新 `AV-CAM.BIN`。

## 核心能力与修复要点
1. **6 档自定义照片纵横比（JPEG / HEIF 全功能裁切）**：支持 `17:6`、`65:24`、`5:4`、`7:6`、`1.91:1`、`2.35:1`，CP 常驻 `.text` 安全区（`0xbef7b0..0xbf0000`），AP 取景遮罩纯整数绘制，行号迁至 `0x1640..0x1645`；`r5_cp_notify_jpeg()` 直接按槽位宽高裁切，`AV-CAM.BIN` 的 `aspect_avcam_heif_entry` 正确读取 `w21` 槽位号并补齐 APS-C S（`3120×2080`）尺寸表，完整覆盖 JPEG 与 HEIF（4:2:0 / 4:2:2、单拍与 RAW+HEIF、全画幅 L/M/S 及 APS-C L/M/S）。
2. **原厂创意外观放行与冷启动加固**：`unified-look.c` 新增 `bank_unavailable_only()` 隔离判定，配合 `r5_stage413_probe.c`（3s 超时）与 `r5_stage413_thread.c`（8 次重试），避免开机早期 CP 响应慢导致滤镜未导入或原厂创意外观被锁死。
3. **AP BSS 安全隔离扩容**：画幅状态区从 `0x8f12b60` 后移至 `0x8f13000`（`state_size=0x3300`），与 `unified-look` BSS 末尾（`0x8f12b50`）留出 1,200 字节安全隔离带。
