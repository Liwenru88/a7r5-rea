# A7R V Fastboot 救砖研究

适用机型为索尼 A7R V（ILCE-7RM5）。本模块汇总 RAM Fastboot 启动工具、接线资料、上游检索和 4.18 启动故障的离线证据。当前工具用于一次 RAM 引导和只读诊断。4.18 故障机的根因仍需现场回读确认，归档中的 WBI 候选只用于离线验证。

## 离线验证

从项目根目录运行。使用项目 Python 环境和本模块材料即可，项目根目录下的 `.local/` 无需存在。

```sh
.venv/bin/python -B a7r5-fastboot/r5_fastboot.py preflight
.venv/bin/python -B -m pytest -q -p no:cacheprovider a7r5-fastboot/test_offline.py
```

预检核对相机 RAM 载荷、RP2040 UF2、pySerial wheel、历史 SDM2 参考、两个 macOS USB 辅助程序和 64 条 BootROM 引导记录。测试使用伪终端和模拟 USB 回执。默认入口和 `preflight` 均只读取本地文件。

## 手动回车触发（macOS）

确认更新已停止、电池充足、接线检查通过，相机保持 ON，并关闭占用串口的程序。在项目根目录的交互式终端运行：

```sh
.venv/bin/python -B a7r5-fastboot/r5_fastboot.py probe \
  --port /dev/cu.usbmodem101 \
  --output "a7r5-fastboot/runs/manual-$(date +%Y%m%d-%H%M%S)" \
  --confirm-reset --wait-for-enter
```

串口名称需以实际枚举结果为准。脚本先校验本地材料、打开 RP2040 并确认桥接版本，然后等待回车；等待期间不发送相机复位或引导记录。按回车后只进行一次复位、RAM 载荷发送和只读 USB 诊断，不自动重试，不刷写或擦除分区。输出目录必须是新目录，缺失的父目录会自动创建。

回车前按 Ctrl+C 或遇到输入关闭会取消，不触发复位；操作开始后取消不能撤销已经发生的复位或发送，记录会标注中断阶段。报告保存在输出目录的 `report.json`。`records_acknowledged=64` 只代表桥接端应答，不代表相机已执行载荷；`uart_ready_observed` 和 `usb_transport_verified` 分别记录 UART ready 标志与完整 USB 只读验证结果。此模式不修改原有引导时序，也不保证故障机能进入 Fastboot。

## 材料索引

| 材料 | 位置 |
| --- | --- |
| 主机入口与回归 | [r5_fastboot.py](r5_fastboot.py)、[test_offline.py](test_offline.py)、[USB 源码](native/)、[USB 程序摘要](host-sha256.json) |
| 本地运行材料 | [assets](assets/) 内的 `fastboot.bin`、`uart_boot.ino.uf2`、pySerial 3.5 wheel、历史 SDM2 参考，[host](host/) 内的 macOS arm64 程序 |
| 接线、照片、实机判读 | [接线与诊断说明](接线与诊断.md)、[本地接线图与照片](private/wiring/) |
| RP2040 源码和构建材料 | [准备清单](private/reference/preparation/准备清单.md)、[开漏桥源码](private/reference/preparation/uart_boot/)、[构建产物和参数](private/reference/preparation/bridge-build/)、[工具链版本及日志](private/reference/preparation/toolchain/)、[UF2 验证回执](assets/bridge-verification.json) |
| 历史主机实现 | [原准备阶段的脚本、清单与工具](private/reference/preparation/)、[Hearts-Ace USB 原始源码](private/reference/hearts-original/)、[迁移前独立工具说明](private/reference/fastboot-rebuild-readme.md) |
| 上游检索与原始资料 | [提交、Releases 与 ZIP 扫描结果](private/upstream/scan/)、[原始发布 ZIP](private/upstream/release-zips/)、[部分 Git 镜像](private/upstream/git-mirrors/) |
| 4.18 启动故障 | [故障分析](../a7r5-firmware-features/native24-combined/4.18启动故障离线分析.md)、[原始对照和回放](private/cases/4.18-incident/)、[组件审计](private/cases/4.18-component-audit/) |
| WBI 离线验证 | [验证回执](private/cases/4.18-wbi-verify/verification.json)、[原始 4.17 与 4.18 包](private/cases/inputs/)、[原厂 4.00 包](../a7r5-firmware-images/官方升级包/BODYDATA.DAT)、[历史 WBI2 回读](../a7r5-firmware-images/标准固件_19项/明文分区_17项/cnflasha5.img) |
| 校验记录 | [迁移清单与逐文件摘要](private/migration.json)、[迁移前测试](private/evidence/pre-migration/)、[隔离环境复验](private/evidence/relocated-offline.log) |

历史清单、编译日志、Git 镜像和故障回放脚本按原样归档，其中的旧绝对路径是原实验记录。如需重放历史实验，使用 `private/migration.json` 的源路径与归档路径对照来重建输入。旧脚本可能写入输出或生成候选 DAT，日常离线自检使用上面的两个入口。

2026-11-11 容量清理后，`4.18-incident/desktop`、`release418`、`4.18-wbi-verify/workspace`、`readback`、`wbi-before.bin` 和 `4.18-component-audit/rebuild` 的普通文件已去重压缩归档，重放相关历史脚本前需恢复输入。原始 DAT、原厂 `stock` 对照、WBI 顺序回放和审计回执仍保留；日常预检不依赖这些已清理的副本。恢复方法见[本轮清理结果](../docs/cleanup-audit-20261111/本轮清理结果.md)。

`assets/`、`host/`、`private/` 和 `runs/` 已设为 Git 忽略。本机迁移时需连同这些目录一起备份，单独克隆 Git 仓库只会得到源码和说明。Arduino 已安装工具链、下载缓存和重复发布包保留在原处，运行和离线测试无需这些文件。

## 清理范围

本模块已归档以下五个项目临时目录中与 Fastboot 和故障分析相关的材料。

- `.local/fastboot-prep-20261109.8bMDTF/`
- `.local/fastboot-rebuild-20261109.IgSU9e/`
- `.local/a7r5-418-incident.aHVJqD/`
- `.local/a7r5-418-wbi-verify.Qd4QmQ/`
- `.local/a7r5-418-audit.m4AeQB/`

`.local/native24-release418-20261107-232048/` 只归档了用于故障对照的发布 DAT。其余固件构建目录和缓存请按各自任务核对后清理。

## 来源与构建

在三份公开仓库共 142 个可达提交和 12 份 Release ZIP 内未找到原版 `bootloader脚本.zip`。本模块保留独立重建的入口。其 `fastboot.bin` SHA-256 与 Hearts-Ace 的 R5 入口锁定值一致，64 条引导记录与 David、Erlla 的公开实现逐字节一致。[David 串行引导源码](https://github.com/DavidBuchanan314/ILCE-7M4-RE/blob/e85e137fc3b88b7cb26e69faa9f1304184678ff7/scripts/push_payload.py) · [Erlla 载荷清单](https://github.com/Erlla/sony-a7m4-custom-firmware/blob/72a6ae26cfcb9db87c531d2240f0b0096f385699/fastboot/assets/manifest.json) · [Hearts-Ace R5 启动入口](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware/blob/be3dc9a622a797ce72270ff39a5d44ccaa33edc8/tools/r5-slots/ram_boot.py)

RP2040 UF2 使用 Arduino CLI 1.5.1、Arduino-Pico 6.3.0、板型 `rp2040:rp2040:waveshare_rp2040_zero` 和构建属性 `compiler.cpp.extra_flags=-DOPEN_DRAIN`。归档包含原草图、PIO 源码及生成头文件，也保留了当时的 UF2 和 ELF，可直接对照原构建结果。macOS USB 辅助源码使用 Xcode Command Line Tools，通过 `clang -O2 -Wall -Wextra -framework IOKit -framework CoreFoundation` 分别构建。随模块迁移的是已校验的原程序和摘要。
