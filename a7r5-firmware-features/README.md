# A7R5 固件功能主线（当前稳定版本：4.31）

当前对外稳定主线版本为 **4.31**（包含 **6 档自定义照片纵横比 JPEG/HEIF 全功能裁切**、原厂创意外观放行隔离修复与冷启动加固、AP BSS 安全隔离区扩容）。

- 唯一原厂基底：**Sony ILCE-7RM5 / A7R V 官方 4.00 `BODYDATA.DAT`**（754,525,608 字节，SHA-256 `51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2`）。
- 4.31 流水线与说明见 [`firmware-runtime/stable-build/PACKAGE-README.md`](firmware-runtime/stable-build/PACKAGE-README.md) 与 [`KNOWN-ISSUES.json`](firmware-runtime/stable-build/KNOWN-ISSUES.json)。
- 未经完整实机验收的实验性模块、历史多模块组合框架（`compose.py`）与历史规格已统一归档至 [`research/`](research/README.md)。

## 4.31 包含内容

| 模块 / 能力 | 说明 |
|---|---|
| `look24`（24 槽自定义滤镜） | 支持冷启动探测（3s 超时 / 8 次重试）及 `bank_unavailable_only()` 隔离，SD 卡冷启动导入 `R5NATIVE.BIN`、分组切换、横竖屏同步、八项相对调参 |
| `look-fl2-fl3` | 原厂创意外观组开放 FL2 / FL3，含机内 RAW 十二项备选目录 |
| `lens-af-compat` | 在 `cpapp-b.bin` `.text` 安全区（`0xbef780..0xbef7ac`）写入 44 字节辅助读取器并替换 5 处能力查询调用，自动兼容模式下保留镜头自身上报的 AF 能力位 |
| `unified-look.c` 轻量防抖 | 在 `apply()` 增加同目标队列去重与非忙态下发保护；在 `tune_changed()` 对忙态下的连续微调合并排队 |
| `aspect-431`（6 档自定义照片纵横比） | 新增 `17:6`、`65:24`、`5:4`、`7:6`、`1.91:1`、`2.35:1`，CP 常驻 `.text` 安全区（`0xbef7b0..0xbf0000`），AP BSS 扩容至 `0x8f13000`；支持 **JPEG 与 HEIF（4:2:0 / 4:2:2、单拍与 RAW+HEIF、全画幅 L/M/S 及 APS-C L/M/S）** 全功能裁切 |

**底层不变式**：严格保持 `WBI3`（`nflasha5` 首扇区偏移 `0x3` 为 `0x33`）、`nflasha15` 修改 4 个文件（`appFw.so`、`libmpr.so`、2 个 `.uxc`）、`nflasha8` 更新 `cpapp-b.bin`、`nflasha3` 原簇链更新 `AV-CAM.BIN`。

## 一键构建 4.31

在仓库根目录执行：

```sh
./scripts/build_from_400.sh /path/to/4.00/BODYDATA.DAT -o ~/Desktop/a7r5-4.31
```

若本机已在 `a7r5-firmware-images/官方升级包/BODYDATA.DAT` 放置原厂 4.00 包，可直接运行 `./scripts/build_from_400.sh`。

## 当前验证范围

- **已完成（离线与实机）**：
  - **离线校验**：双次确定性构建（`runtime` 与 `rebuild`）、RSA 研究签名、736,841 帧全量解密回读、`e2fsck -fn` 检查，以及 `test_build.py` / `test_runtime_sources.py` 单元测试。
  - **实机验证**：已由项目作者完成 4.31 实机安装与全功能验收，确认正常开机、自定义滤镜、原厂创意外观与 JPEG/HEIF 画幅裁切均正常。
