# 4.28：4.27 稳定基线 + lens-af-compat + 轻量防抖

## 身份

- 目标机身：Sony ILCE-7RM5 / A7R V；唯一原厂基底为项目固定的官方 4.00。
- 包版本号：4.28。
- 基线：已实机验证可正常开机使用的 4.27（4.24 + RAW 12 项 + 微调容量提示与重置锁）。
- 底层布局：严格保持 `WBI3` 不变、`nflasha15` 仅改 3 个文件、`cpapp-b.bin` `0x108000..0x128000` 早期引导区零改动。

## 相对于 4.27 的新增项

1. **`lens-af-compat`（镜头 AF 能力过滤适配）**：在 `cpapp-b.bin` `.text` 安全区（`0xbef780..0xbef7ac`）写入 44 字节辅助读取器并替换 5 处能力查询调用，在自动兼容模式下保留镜头自身上报的 AF 能力位。
2. **轻量防抖（`unified-look.c`）**：
   - 在 `apply()` 中增加同目标队列去重与非忙态下发保护（`!flow.active && !busy()`）；
   - 在 `tune_changed()` 中对忙态下的连续微调合并排队，避免重复打断当前事务；
   - 严禁引入 4.23 的 `confirm_target`、`sync_custom_tab`、`r5_filter_e4_stalled` 等阻塞性状态机改动。
