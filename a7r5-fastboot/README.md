# A7R V Fastboot 救砖研究

适用机型为索尼 A7R V（ILCE-7RM5）。本模块汇总 RAM Fastboot 启动工具、接线资料、上游检索和 4.18 启动故障的离线证据。当前工具用于一次 RAM 引导和只读诊断。4.18 故障机的根因仍需现场回读确认，归档中的 WBI 候选只用于离线验证。

## 离线验证

从项目根目录运行。使用项目 Python 环境和本模块材料即可，项目根目录下的 `.local/` 无需存在。

```sh
.venv/bin/python -B a7r5-fastboot/r5_fastboot.py preflight
.venv/bin/python -B -m pytest -q -p no:cacheprovider a7r5-fastboot/test_offline.py
.venv/bin/python -B -m pytest -q -p no:cacheprovider a7r5-fastboot/native/test_configure_fastboot_usb.py
```

预检核对相机 RAM 载荷、RP2040 UF2、pySerial wheel、历史 SDM2 参考、两个 macOS USB 辅助程序和 64 条 BootROM 引导记录。测试使用伪终端和模拟 USB 回执。默认入口和 `preflight` 均只读取本地文件。

## USB 枚举与配置诊断

`host/configure_fastboot_usb --check` 只检查系统注册表中是否存在唯一的 `18d1:4ee0`，不打开 USB 设备、不发送控制请求。返回码 `0` 表示目标可见，`2` 表示不存在，`4` 表示存在多个目标；目标可见不等于通信就绪。

不带参数运行该工具会读取配置状态和配置描述符，必要时执行一次 USB 配置；它会改变临时 USB 接口状态，但不复位相机、不发送 Fastboot 重启命令、不写分区。读取配置失败时打印返回码和 `configuration=unknown` 并停止；已处于所需配置时不重复配置。日志即时输出每一步返回码，避免超时后丢失已完成阶段的信息。

`probe` 将被动枚举与实际配置分开：最多等待目标出现 15 秒，每次注册表检查限时 0.5 秒，注册表检查超时可继续等待；确认唯一目标后，实际配置只尝试一次、限时 15 秒。配置失败或超时后停止，不重新配置或重新引导。回执分别写入 `usb-presence.log`、`usb-config.log`。这些本地修复不代表相机 USB 通信已恢复。

原生配置工具的回归测试编译真实 C 源码，将 IOKit 设备边界替换为模拟接口；不连接相机。构建工具需要 macOS 和 Xcode Command Line Tools。

## 验证现有 Fastboot 会话（不复位）

相机已处于 Fastboot、当前保持终端仍在运行时，使用独立的 `usb-check`，不要重新运行会复位相机的 `probe`：

```sh
.venv/bin/python -B a7r5-fastboot/r5_fastboot.py usb-check \
  --output "a7r5-fastboot/runs/usb-check-$(date +%Y%m%d-%H%M%S)"
```

该入口不打开 RP2040 串口、不发送相机复位、引导记录、重启或分区写入。它等待唯一 Fastboot USB 设备，必要时配置一次临时 USB 接口，再查询协议与分区表，读取 SDM2 和 AP BootROM。基础检查通过后，以 5 秒间隔查询版本 13 次（至少一分钟），随后再次回读 SDM2 并比较内容。只有全部通过，`report.json` 的 `stable_communication_verified` 才为 `true`，程序才返回 `0`；一次成功查询或载荷的 UART ready 信息均不足以通过。

任一步失败或超时后停止并保留日志，不自动重配、复位或重新引导。输出目录必须是新目录。通过只表示本次有界观察中的通信稳定，不证明相机已正常启动或拍摄，也不证明与历史参考是同一物理机身。

## 持续持有 USB 连接

`host/read_fastboot_usb --hold /absolute/path/to/new-status.json` 会等待唯一的已配置 Fastboot 接口，然后打开并持续持有，每 5 秒只发送一次 `getvar:version`。启动时没有接口则每 2 秒只检查一次系统注册表，持续等待，不发送 USB 请求。该模式不打开串口、不选择 USB 配置，不发送相机复位、引导、重启或分区写入；关闭标准输入不会退出。状态文件必须是尚不存在的绝对路径，其父目录须已存在。

状态文件包含 PID、`state`、成功心跳次数、最后成功时间和错误码。`waiting_for_usb` 表示尚无可用接口，不能视为连接成功；`connected` 表示最近一次版本查询成功；通信或打开接口失败时转为 `blocked`，释放接口并保留进程供检查，不自动重新连接。`SIGTERM` 或 `SIGINT` 会关闭接口并将状态写为 `stopped`，不会重启相机。

后台启动应使用独立进程会话、空标准输入，并将日志写入文件。运行期间它独占 USB 接口，其他分区采集或 `usb-check` 必须先等待保持进程释放接口。当前 RP2040 保持终端应保留，不要再启动会复位相机的入口。该进程不能保证在相机掉电、数据线拔出或主机强制休眠后仍保持连接。

启动故障诊断还允许只读导出 `nflasha3`、`nflasha8`、`nflasha15`。完整逻辑分区分别为 75、64、715 MiB；单次上传上限为最大的 715 MiB，仍拒绝 `flash:*`、`erase:*`、`download:*`。应先核对当前分区表，并在一个独占会话中采集，异常即停止。与升级包比对时只对包内镜像长度计算摘要，分区容量与包内镜像长度不能混用。

## 手动进入 Fastboot 后暂停分析（macOS）

如果需要先让相机进入 RAM Fastboot，再由人工在其他终端分析，可使用独立入口。它会先完成本地材料校验和 RP2040 桥接版本检查；按第一次回车后只执行一次复位并发送完整 RAM payload，不会自动调用 USB 分区读取、写入、擦除或重启命令。进入后脚本保持串口和 UART 日志打开，回到该终端按第二次回车退出并生成 `report.json`。

```sh
python3 -B a7r5-fastboot/manual_fastboot.py \\
  --output "a7r5-fastboot/runs/manual-fastboot-$(date +%Y%m%d-%H%M%S)" \\
  --confirm-reset
```

默认会自动查找唯一的 RP2040 `/dev/cu.usbmodem*` 串口（VID `0x2E8A`）。如果检测到多个 RP2040 串口，或希望固定设备，也可以显式指定：

```sh
python3 -B a7r5-fastboot/manual_fastboot.py \\
  --port /dev/cu.usbmodem1101 \\
  --output "a7r5-fastboot/runs/manual-fastboot-$(date +%Y%m%d-%H%M%S)" \\
  --confirm-reset
```

输出目录必须是新目录。第一处提示按回车会触发相机复位；进入 `fastboot_waiting` 后，可以在其他终端执行人工只读分析。第二处提示按回车或按 Ctrl+C 会关闭桥接并保存 `uart.bin`、`report.json`。该入口仍会发送 RAM payload，因此取消只能阻止尚未触发的复位，不能撤销已经发生的设备状态变化。

## 手动回车触发并自动完成只读诊断（macOS）

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
| 4.18 启动故障 | [故障分析](../a7r5-firmware-features/firmware-runtime/4.18启动故障离线分析.md)、[原始对照和回放](private/cases/4.18-incident/)、[组件审计](private/cases/4.18-component-audit/) |
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
