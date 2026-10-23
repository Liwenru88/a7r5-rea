# A7R5 QEMU · macOS 原生项目

> GitHub 源码发布说明：当前研究签名公私钥经授权随源码保留；完整固件、其他私钥、SDK 二进制、真实操作包和历史验证现场仅留本地；旧链接可能指向未入库材料。环境与输入要求以 [根目录构建说明](../docs/build-inputs.md) 为准，本轮验证见 [验证记录](../docs/verification.md)。

2026-10-23 根目录 `analysis/` 删除后，创意外观材料准备入口改用本项目 `build/look-materials-77zf0trj/` 的固定摘要副本：在本目录执行 `.venv/bin/python -B tools/look_reference.py prepare`。保留原有完整性检查；当前默认菜单、客体及创意外观会话配置不变。本轮源码 Qt 菜单和离线回归记录见 [删除后验证](../a7r5-exec/verification/analysis-removal-20261023/修复与验证.md)。

当前默认入口使用 **`dist/A7R5 Emulator Expanded.app`**。已追加四组拨轮、模式拨盘、摇杆五向、C1/C2/C3 和 C4 拍摄页触摸开关用途；36 项控制中 19 项按已验证上下文开放。新版独立包通过 127 次真实 Qt 操作、128 张原始帧/PNG 独立核对及正常退出，另通过菜单帮助/导航和交付路径冒烟。操作与限制见 [按键扩展说明](specs/002-camera-function-expansion/button-expansion.md)。旧版应用、早期应用快照及专用旧版启动器已按确认范围移除，当前仅交付新版应用。历史验收文档和收据中的旧包路径保留用于追溯，不作为现有启动或回退入口。

合并后的开发环境入口已修复，工程可从当前中文目录运行。虚拟介质研究已完成原厂 SDK 的 14 组 Dataflow 双端连接，并推进后续固定配置回调；原厂 Fsys 对 4 MiB FAT 文件的读写、重新挂载及两张测试 JPEG 的读取已有独立证据。应用媒体挂载和照片显示、切换仍未完成，预览/成像也未实现。本批只更新模拟观察库以增加输入完成回执，没有装入媒体研究候选。当前媒体证据见[连接握手分析](specs/003-virtual-media-and-imaging/connection-handshake-analysis.md)和[验证记录](specs/003-virtual-media-and-imaging/verification.md)。

2026-10-22 新增独立的[原厂 CP 启动研究](specs/003-virtual-media-and-imaging/native-cp-bringup.md)：完整初始化请求捕获、原 CP 矩阵真实 QEMU 执行和四核启动现场。实验板未接入默认客户端，完整 CP 服务、AP/CP 传输和 ISP 成像仍未验收；不以软件滤镜画面替代。

在 Apple Silicon Mac 上，用定制 QEMU 运行 A7R5 / ILCE-7RM5 4.00 的原厂 Linux 和菜单应用。项目内包含内核、客体文件系统副本、模拟载荷、构建源码和验收资料，不依赖原研究工程、相机或 SD 卡。

## 启动与退出

先正常关闭旧窗口，再双击 **`启动A7R5原厂菜单.command`**，打开新版 Qt 客户端。脚本直接启动已验收的包内程序，关闭启动终端不会终止客户端；正常退出请使用客户端按钮。默认入口不启动网页。使用方向键、Enter、Escape 或窗口按钮；Escape 对应 MENU，顶层菜单可以反复开关。

系统直接打开 `.app` 时，本轮曾观察到首次启动停顿，原因尚未确认；推荐使用上述脚本。脚本直启已实测 26.42 秒完成原厂初始化、MENU 和退出全过程，GUI 已退出、worker 0 / QMP quit 0。它绕开该系统启动路径，不能表述为已经修复 macOS 启动服务。

控制清单包含 36 项，19 项按上下文开放，其余 17 项注明待实现或硬件限制。菜单中可使用四组拨轮和摇杆五向；模式、自定义键及 Fn 等需先完成首次设置。不会直接把所有灰色按钮无条件开放。

使用 Fn、DISP、回放、自定义键与模式拨盘前，在初始 My Menu / Add Item 点击 **“首次设置（启用功能键）…”**：确认原厂说明后，按 C4 **“在相机上设置”**，保留模拟器的测试区域和日期，温度设置选择 **Set Later**，关闭最后的说明。出现黑色启动页时按 MENU 返回菜单，再按 MENU 到拍摄信息页。选择虚拟模式 **P** 后，C1 可修改/读回白平衡，C2 可修改/读回对焦区域；C3 打开对焦模式，部分选项仍被原厂镜头状态拒绝。Fn 用方向键选择、确认，Fn 或 MENU 返回；DISP 切换信息布局；回放只显示无卡提示，再按回放返回。无需连接手机。

首次设置仅在本次客体 RAM 内生效，每次启动需重新完成。入口只允许从初始菜单请求一次；若取消向导，退出模拟器后重开。日常启动不会代替用户自动确认说明，也不直接写接受状态。C4 在拍摄信息页可切换触摸操作开关，但尚无真实触点/手势，也未验证删除照片。模式拨盘需当前布局显示模式标志，否则先用 DISP 返回拍摄信息布局。

点击“退出本次模拟器”或窗口关闭按钮，等待工作进程退出码与 QMP 回执核对后窗口关闭；异常会保留窗口、错误说明与日志入口，不自动重试。源码入口和应用包共用一个用户级 VM 锁。

**`启动A7R5网页回退.command`** 显式打开旧网页入口；客户端失败时不会自动切换。**`启动A7R5桌面开发.command`** 使用项目 `.venv` 运行同一客户端源码。

**`启动A7R5原厂系统终端.command`** 提供模拟器内的 root shell，不自动启动菜单。输入 `exit` 或按 Ctrl-D 正常退出。这里的 root 属于 QEMU 客体，命令不能直接操作相机或 Mac 的物理磁盘。

## 功能与限制

画面由原厂应用、库和资源生成，以 640 × 480 AP 软件绘图快照显示。启动入口只对已经核对的初始化页面发送固定按键，完成首次触控提示后进入真实菜单。每次输出画面均校验快照长度、身份、序列和内容校验和。

显示快照后 QMP 暂停客体，下一次导航时恢复，避免空闲等待推进尚未完整建模的硬件定时器。菜单设置只在本次 RAM 中，退出后不持久化。

功能扩展已核对八个菜单分类，并验证 **Display From My Menu** 的 Off→On→重进回读→Off 还原。初始 My Menu 页按下五次、确认即可进入该选项；选项内可用 C4 查看原厂帮助，再确认返回。分类可达不代表各项硬件功能可用。Fn/回放此前被尚未完成的原厂首次设置状态过滤；DISP 使用控制轮上键，原候选键码无对应事件。修复与证据见 [按键分析与操作说明](specs/002-camera-function-expansion/fn-disp-playback.md)及[功能状态表](specs/002-camera-function-expansion/capabilities.md)。

按键刷新已做分段计时和优化：同一组 16 次真实 Qt 点击，中位延迟从 3.37 秒降至 0.44 秒，最慢一次从 3.81 秒降至 0.59 秒。移除每键固定一秒等待，改为等待新快照且像素来源连续 20 毫秒稳定（最多 2 秒）；MENU 从拍摄信息页重开时还核对原厂页面切换。传输使用无损 RLE16，接收后还原整个原始容器，保留原有长度、身份、序列、FNV 与 SHA 校验。解码只做一次，PNG 转换使用 Pillow 的原生操作。

计时为本机点击到 Qt 图像加载、控件更新完成，不是物理屏幕扫描输出测量，也不代表持续视频帧率。每次运行的 `latency.jsonl` 记录按键、导出、校验、PNG 和保存耗时；对比数据见 `logs/latency-optimization/comparison.json`，验证说明见 `specs/001-cross-platform-desktop/latency-verification.md`。

上述 0.44 秒是前一轮 16 次导航的历史测量。本轮增加了原厂输入完成屏障和模式显示核对，各新增操作的实际计时保存在 `logs/function-expansion/package-expanded-controls-127.json`，不能用历史数字代表全部新增功能。

取景视频、拍摄、录像、完整 CP 硬件及整机电源管理尚未模拟。菜单启动包含模拟服务和受限初始化适配，不代表完整相机硬件仿真，也不证明镜像能安全回刷相机。

## 目录

| 目录 | 内容 |
| --- | --- |
| `bin/` | 本机 Mach-O ARM64 QEMU |
| `runtime/` | 已提取的内核、当前客体归档、设备树、固定输入清单 |
| `tools/` | 共用会话、平台能力、固定输入、网页回退、终端与构建 |
| `client/`、`config/` | PySide6 窗口、控制注册表、语义与上下文门槛 |
| `packaging/`、`dist/` | 自包含 macOS 应用的构建配方和交付物 |
| `source/guest/` | 菜单模拟载荷、服务及辅助程序的 C 源码 |
| `source/qemu/` | 固定版本 QEMU 源码包、Sony 补丁、DTC 源码、摘要及许可证 |
| `sdk/lib/` | 客体 glibc 链接库及已适配的 GPE 库副本 |
| `tests/` | 原生边界、初始化、客体替换及端到端验收 |
| `build/` | 可重新生成的构建工作区和构建收据 |
| `runs/` | 每次运行的控制台、原始帧、PNG 和退出回执 |
| `logs/` | 本次迁移、重建、测试和验收记录 |
| `evidence/history/` | 迁移前的历史证据，原路径文字仅用于追溯 |

项目不保存 37 个分区镜像的重复副本。`runtime` 中的约 406 MiB 客体是运行菜单需要的提取副本，和桌面原始分区镜像相互独立。模拟库与快照辅助程序有各自的定向重建入口，其他归档条目逐项保持一致。

## 本机依赖与重建

当前应用包面向 macOS 14 及以上 Apple Silicon，已在本机 macOS 27 验收。包内自带 Python 3.14、Qt 6.12、QEMU 和运行动态库，不需要开发 `.venv` 或 Homebrew。当前使用本地临时签名，未做外部分发公证；不能据此宣称已验收所有 Mac。

源码开发使用项目 `.venv`；QEMU 源码运行依赖本机 GLib、Pixman，重建使用 LLVM clang 与独立 lld。Windows/Linux 只完成界面与能力边界设计，固件后端尚未验收，拒绝启动。

新建环境时，在本项目目录执行：

```sh
brew install llvm lld glib pixman ninja meson pkg-config
uv venv .venv --python 3.14
uv pip install --python .venv/bin/python -r requirements-desktop.txt
```

先退出全部 VM，再双击 **`重建模拟器与载荷.command`**，或执行：

```sh
.venv/bin/python -B tools/build-native.py
.venv/bin/python -B tools/build-guest.py
```

第一步从项目内固定源码包和补丁重建 QEMU，校验源码摘要，并更新 `bin` 和运行清单。第二步用本机 LLVM 交叉编译 AArch64 Linux ELF，直接链接项目内 glibc 2.25 副本；以当前已校验客体为种子，仅替换 `simulation/menu-observe-a7r5-baseline.so`，逐项核对归档后原子切换清单。构建不需要容器或旧工程，也不重新提取原始分区镜像。

客体采用内容寻址文件名，构建中断保留旧清单。后续开发产生的旧候选可以在退出所有 VM、核对当前 `runtime/manifest.json` 后单独清理。首次迁移只保留已验收候选。

本次优化的快照辅助程序可单独重建：`.venv/bin/python -B tools/build-frame-export.py`。该入口只替换 `simulation/headless-osd-export`，逐项核对其他归档条目，更新设备树容量参数，并在原指纹匹配时同步控制注册表。不会重建或改写原厂应用、内核，也不会访问原始分区镜像。重建后仍需真实菜单验收。

## 应用构建、数据与验证

在项目目录执行 `.venv/bin/python -B packaging/build-macos.py`，构建记录写入 `logs/desktop-implementation/`。打包后固件位于 `.app/Contents/Resources/a7r5/runtime/`，按包内清单只读加载，只有一份约 406 MiB 客体归档。源码当前归档和旧基线保留在 `runtime/`；它们不重复塞入应用包。

应用运行证据写入 `~/Library/Application Support/A7R5 Emulator/runs/`，源码运行写入项目 `runs/`。每个会话保留原始帧、PNG、请求、状态、工作进程退出码和 QMP 回执。设置仍只保存在客体 RAM。

本次验证和所有任务状态见 `specs/001-cross-platform-desktop/verification.md`；当前回归清单见 `logs/desktop-implementation/regression.json`。主要入口：

```sh
.venv/bin/python -B tests/test-desktop-session.py
.venv/bin/python -B tests/test-desktop-resources.py
.venv/bin/python -B tests/test-input-registry.py
.venv/bin/python -B tests/test-input-context.py
.venv/bin/python -B tests/test-input-release.py
.venv/bin/python -B tests/accept-desktop.py
.venv/bin/python -B tests/accept-function-keys.py
.venv/bin/python -B tests/smoke-web.py
```

Qt 端到端验收涵盖 C4 帮助往返、四轮 MENU、六键、17 张原始帧/PNG、空闲暂停和正常退出。原网页完整导航记录仍作为历史基线保存，不用历史记录替代客户端证据。

独立包可显式使用 `--acceptance-functions` 进行固定 Qt 功能验收：仅此测试模式自动完成本次 RAM 内的原厂向导，随后执行 Fn、五种 DISP 布局、空介质回放以及条目层/分类层各四轮 MENU，共 53 次操作。该模式不接受自定义脚本或原始键码。结果在用户数据目录的 `package-functions.json`，本次已独立核对 54 张原始帧与 PNG、GUI/worker/QMP 退出码均为 0。额外桌面自动化复核因 ScreenCaptureKit 捕捉服务错误未完成，未将失败会话算作通过；真实 Qt 控件及原厂帧验收已完成。见 `logs/key-dispatch/package-delivery.json`。

M2 仅增加了模拟库的可选输入接收日志，原厂应用、库和内核没有修改；1226 个归档条目中只变更 `simulation/menu-observe-a7r5-baseline.so`，设备树仅更新归档结束地址。

## 隔离边界

原生 VM 强制使用默认拒绝的 macOS 沙箱。固定内核、归档和设备树只读；仅能写本次运行目录和临时 QMP 目录。QEMU 无网卡、主机目录共享、物理磁盘或 USB 直通，TCP 网络禁止。HTTP 入口仅监听 `127.0.0.1`，保留 Host、Origin、会话令牌和固定按键校验，不暴露任意 shell 接口。

源码参考 `chocotan/a7c2-re` 的 QEMU 实验，参考提交 `5ec277d8aa50704c1211a7c114730391fcd25a40`。固定 QEMU、DTC 及相关许可证见 `source/qemu/licenses/` 和源码包。Sony 固件来自用户自己的转存副本，本项目中的个人研究副本不作为固件分发包。
