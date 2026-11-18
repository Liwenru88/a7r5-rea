# Sony A7R5 4.29 自定义固件升级包

基于 `4.28` 稳定基线构建，新增 6 种自定义照片纵横比（`17:6`、`65:24`、`5:4`、`7:6`、`1.91:1`、`2.35:1`），同时保留 24 槽创意外观/LUT、AF 防抖修复与快门音/RAW 增强功能。

## 本版修复要点
1. **CP `lateMMU` 卸载崩溃修复**：将 CP 纵横比常驻代码移至永久映射区 `.text` (`0xbef7b0..0xbf0000`)，并把末尾两条曲线安全重定位至 BSS 映射页 (`0x1a39b80..0x1a3a000`)。
2. **AP 1 秒菜单崩溃修复**：移除 `ap_persist` 后台 `pthread_create` 线程与跨线程 UI 通知，并将 `O_DIRECTORY` 修正为 AArch64 的 `0x4000`，同时移除 `0x402d` IPC 热路径上的文件 I/O。
3. **AP 取景页崩溃修复**：修复 `ap_guide` 将 `W1` Scene ID 误作 `layer` 的缺陷（改为从 `view+8` 读取），使用 `-mgeneral-regs-only` 纯整数遮罩计算与完整 `SAVE_ALL`/`RESTORE_ALL` 寄存器保护。
4. **容器与资源稳定性**：保留 `nflasha5` (`WBI3`) 与 `nflasha15` 全部 68 个语言 `.uxc` 文件零修改，通过 `n12_text()` 返回新增纵横比文本。

## 交付物
- `BODYDATA.DAT`：已签名的升级镜像
- `R5NATIVE.BIN`：配套 12 款胶片模拟 LUT 配方文件（复制到存储卡根目录）
- `research-public.pem` / `SHA256SUMS`：验签公钥与校验和
