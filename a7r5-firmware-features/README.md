# A7R5 固件功能主线（当前稳定版本：4.28）

当前对外主线版本为 **4.28**（基于已实机验证可正常开机的 **4.27** 基线，叠加 `lens-af-compat` 镜头 AF 能力适配与 `unified-look.c` 轻量防抖保护）。

- 唯一原厂基底：**Sony ILCE-7RM5 / A7R V 官方 4.00 `BODYDATA.DAT`**（754,525,608 字节，SHA-256 `51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2`）。
- 4.28 发布身份与边界见 [`releases/4.28-427-af-debounce-20261117/README.md`](releases/4.28-427-af-debounce-20261117/README.md) 与 [`KNOWN-ISSUES.json`](releases/4.28-427-af-debounce-20261117/KNOWN-ISSUES.json)。
- 未经完整实机验收的实验性模块、历史多模块组合框架（`compose.py`）与历史规格已统一归档至 [`research/`](research/README.md)。

## 4.28 包含内容

| 模块 / 能力 | 说明 |
|---|---|
| `look24`（24 槽自定义滤镜） | 沿用 4.27 稳定实现：SD 卡冷启动导入 `R5NATIVE.BIN`、分组切换、横竖屏同步、八项相对调参、微调容量提示与重置锁 |
| `look-fl2-fl3` | 原厂创意外观组开放 FL2 / FL3，含机内 RAW 十二项备选目录 |
| `lens-af-compat` | 在 `cpapp-b.bin` `.text` 安全区（`0xbef780..0xbef7ac`）写入 44 字节辅助读取器并替换 5 处能力查询调用，自动兼容模式下保留镜头自身上报的 AF 能力位 |
| `unified-look.c` 轻量防抖 | 在 `apply()` 增加同目标队列去重与非忙态下发保护；在 `tune_changed()` 对忙态下的连续微调合并排队 |

**底层不变式**：严格保持 `WBI3`（`nflasha5` 首扇区偏移 `0x3` 为 `0x33`）、`nflasha15` 仅改 3 个文件、`cpapp-b.bin` `0x108000..0x128000` 早期引导区零改动。

## 一键构建 4.28

在仓库根目录执行：

```sh
./scripts/build_428_from_400.sh /path/to/4.00/BODYDATA.DAT -o ~/Desktop/a7r5-4.28
```

若本机已在 `a7r5-firmware-images/官方升级包/BODYDATA.DAT` 放置原厂 4.00 包，可直接运行 `./scripts/build_428_from_400.sh`。详细流水线与宿主工具链要求见 [`native24-combined/release428/SOURCE-ARCHIVE.md`](native24-combined/release428/SOURCE-ARCHIVE.md)。

## 当前验证范围

- **已完成（离线与实机）**：
  - **离线校验**：双次确定性构建（`runtime` 与 `rebuild`）、RSA 研究签名、736,841 帧全量解密回读、`e2fsck -fn` 检查，以及输出摘要核对（`BODYDATA.DAT`：`ed98e87af9e32fec7538a4579986528c1af694e4e55c855b3f7cebfb0eea4408`；`R5NATIVE.BIN`：`19e020fa48c79643aaf9526e9c720d38ec5a92c3df11d0852b0a93a25ee880b6`）。
  - **实机验证**：已由项目作者完成实机安装与功能验收，确认正常开机与各项功能均正常。
