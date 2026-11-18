# 4.29 自定义照片画幅裁切研究成果归档

本目录归档了在 `4.28`（`native24-combined` + 24 槽创意外观 + `lens-af-compat` + `WBI3`）基础上叠加 6 种自定义照片纵横比（`17:6`、`65:24`、`5:4`、`7:6`、`1.91:1`、`2.35:1`）的 `4.29` 实验研究代码、离线 Unicorn 测试与实机故障定位记录。

因实机测试中出现了与创意外观（Creative Look）功能冲突的 Bug，主线已回退至唯一稳定版本 `4.28`，此目录保留全部画幅裁切适配成果供后续排查与复研使用。

## 1. 归档文件索引

| 文件 | 作用说明 |
| --- | --- |
| `cp_aspect_compact.c` | 精简版 CP 侧纵横比状态与编码请求裁切逻辑 |
| `cp_resident.py` | CP 常驻段重定位脚本：将常驻代码放入 `.text` 末尾 `0xbef7b0..0xbf0000`，并将末尾两条曲线重定位到 BSS 页 `0x1a39b80` |
| `test_cp_resident.py` | CP 常驻段重定位与 Unicorn 仿真回归测试 |
| `ap_guide_429.S` / `ap_guide_429.c` | AP 取景框遮罩适配：修复 `view+8` 真实 `layer` 读取，采用 `-mgeneral-regs-only` 纯整数计算与完整 `SAVE_ALL` / `RESTORE_ALL` |
| `ap_persist_429.c` | AP `/setting/r5_aspect10_v1.dat` 持久化：移除后台 `pthread_create` 与跨线程 UI 通知，修正 AArch64 `O_DIRECTORY=0x4000` |
| `ap_transport_429.S` | AP `0x402d` IPC 热路径钩子：移除热路径文件 I/O |
| `build_ap_429.py` / `test_ap_429.py` | AP 侧编译注入脚本与 Unicorn 仿真测试 |
| `patch_429.py` | `unified-look.c` 补丁：通过 `n12_text()` 拦截 `0x0200ab60..0x0200ab65` 返回画幅文本（零 `.uxc` 修改，保持 `WBI3` 不变），以及 `0x1600 -> 0x1640` 状态扩展 |
| `KNOWN-ISSUES.json` / `PACKAGE-README.md` | 4.29 实验包修复摘要与待实机验证项记录 |

## 2. 已验证解决的移植问题

1. **CP `lateMMU` 卸载映射崩溃**：将 CP 常驻代码从 `0x100000..0x128000` 卸载区迁至永久映射的 `.text` 末尾（`0xbef7b0..0xbf0000`）与 BSS（`0x1a39b80`）。
2. **AP 进入菜单 1 秒后崩溃**：移除 `ap_persist` 后台线程与跨线程 UI 刷新，修正 AArch64 `O_DIRECTORY=0x4000`，并移除 `0x402d` 热路径文件读取。
3. **AP 取景页遮罩崩溃**：修正 `ap_guide` 误把 `W1` Scene ID 当作 `layer` 的问题（改为从 `view+8` 读取），使用纯整数遮罩绘制并在 `3:2` 原生模式下保持原厂绘制。
4. **实机画幅裁切表现**：P 档拍照模式下 6 种自定义画幅可正常工作，无死机或重启。

## 3. 实机未解决 Bug 记录（回退原因）

尽管离线 `appFw.so` + `cpapp-b.bin` 在 Unicorn 仿真中通过了 24 槽 UI 与 `R5NATIVE.BIN` 传输测试（`final available_mask: 0xfff`），实机刷写 `4.29` 后出现以下创意外观故障：

1. **自定义滤镜异常**：相机已导入 `R5NATIVE.BIN`，但自定义滤镜页提示“未导入自定义滤镜”（对应 `r5_filter_available_mask() == 0`）。
2. **原厂创意外观异常**：在创意外观菜单移动光标时取景画面完全无变化；选定滤镜按中键确认后，再次进入创意外观仍退回 `ST`。
3. **根因方向定位**：
   - `unified-look.c` 中 `release_native()` 在 `command_state` 处于恢复锁定/失败状态（`7` / `5` / `1`）时返回 `0`，会同时阻断 `n12_stock_preview_menu` 与 `n12_stock_select`，与“光标移动画面不变 + 确认后退回 `ST`”现象完全吻合。
   - 后续若基于 `4.28` 恢复开发 `4.29+`，需重点排查新增画幅补丁与 `native24-combined` 的 `command_state` / `CP-AP` 握手或共享状态区是否存在实机冲突。
