# A7R5 Studio 本地测试版

> GitHub 源码发布说明：当前研究签名公私钥经授权随源码保留；完整固件、其他私钥、SDK 二进制、真实操作包和历史验证现场仅留本地；旧链接可能指向未入库材料。环境与输入要求以 [根目录构建说明](../docs/build-inputs.md) 为准，本轮验证见 [验证记录](../docs/verification.md)。

Rust + Tauri 的 Mac Apple Silicon 客户端。随包携带 Python、固件处理与 USB 库、预编译机内载荷、当前研究私钥和配对公钥。用户无需安装 Python、Node、Homebrew、LLVM 或 QEMU。最低构建目标为 macOS 14；本次仅在当前 macOS 27.0.1 主机验证。

最终交付目录为 `dist/final/`，包含应用、ZIP及包描述。首轮预览和中间测试包已清理；最终包补严了 USB 退出结果判断，并保留输出容器版本设置。

## 用户入口

解压最终 ZIP 后双击 `A7R5 Studio.app`。这是临时签名的本地测试包，尚无 Developer ID 签名、公证或本轮实机验收；请保留整个应用包。

| 页面 | 能力 | 使用方式 |
|---|---|---|
| 相机维护 | 完整备份更新器分区 | 相机选择 MSC，点击备份，阅读提示后交给 macOS 系统授权 |
| 相机维护 | 更新研究签名信任环境 | 先完成备份；选择该任务的 `result.json`，再点击更新 |
| SSH 服务 | 上传三个程序并启动 SSH | 输入两次相机 SSH 密码，点击启动；上传与启动共享一次 USB 会话 |
| SSH 服务 | 停止本应用的 SSH 实例 | 同一电脑、同一 USB 端口，选择 MSC 后停止；不会停止未记录的其他实例 |
| 固件工坊 | 四项功能自由组合 | 选择指定官方 4.00 原包，选择新输出位置，勾选功能并封包 |
| 任务记录 | 回执、备份、失败现场和恢复确认 | 打开对应任务；完成机内操作后核对 MSC，再人工确认屏幕 |
| 使用指引 | MSC、管理员授权与卡刷说明 | 每次操作前阅读提示；生成 DAT 旁另附独立 HTML 说明 |

SSH 密码支持 8–128 个非控制字符、最多 512 个 UTF-8 字节。明文不写入请求、文件或命令参数；Rust 内部生成固定 10000 轮 SHA-512-crypt。任务材料中会保留机内认证所需的口令哈希和配置载荷，目录为本人可读写。Mac 管理员密码仅由 macOS 系统窗口接收。

SSH 服务的账户为 `root`，端口为 `2222`。IP 需要依据相机实际网络环境确定；应用不自动配置或探测网络。使用 SSH 客户端连接时核对任务目录 `device/session/host-public-key` 中的已验证主机公钥，不要禁用主机密钥检查。开启服务的回执不等于网络登录已经通过。

应用启动不枚举相机。用户点击设备动作、阅读准备提示并继续后，才申请管理员权限，观察 MSC 主机元数据并开始 USB 操作。不存在独立检测按钮或离线模式。

## 支持边界

- 仅支持 ILCE-7RM5、指定 4.00 版本文件与加载库、已知接口格式及已适配完整分区前像。未知内容停止。
- 官方 DAT 大小为 754525608 字节，SHA-256 为 `51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2`。
- 完整分区原像 SHA-256 为 `acf32d30dd883ed349738e66fb081e85e0d6a3c746f5e3ca169031e8d69ed731`；目标为 `a3733332c2a1b336226bb9000e01665ce54bec970aefc3334b88863b80f40ceb`。
- USB 端口从本次唯一普通身份绑定；不沿用开发机历史端口。停止 SSH 仍要求启动时的物理端口。
- 信任更新非原子：完整校验前像、258 个扇区的写入日志、同步、完整回读和再次打开后的捕获，都不能保证任意断电或硬件故障下恢复。
- 四项为 FL2/FL3、六款自定义滤镜、关闭 NTSC 提示、电子快门声音。关闭某项恢复其入口，但部分组合仍共享必要的数据布局。全不选同样使用研究签名。
- 输出版本沿用既有客户端的 `4.06` 默认值，可按两位小数设置；只改变容器标识，内容仍来自指定官方 4.00，不代表同号官方固件功能，也不保证相机接纳。
- 卡刷接纳、相机启动/功能、真实 SSH 网络登录、管理员授权到实际 USB 接管、真实恢复均未在本轮验证。测试不会自动操作存储卡或启动卡刷。
- 现有研究私钥按用户授权随本地包携带。没有生成新身份，也没有公开上传此包或密钥。

## 操作提示与恢复

每次 USB 操作前：开机、可靠数据线连接电脑、在相机选择「海量存储器 / MSC」。尚未开始且没有模式选项时，才建议重新拔插。执行中或结果不明时保留连接、供电与现场，不自动重试。

完成机内验证并成功返回唯一 STOP 请求后，只观察主机元数据，等待原有媒体和驱动连续两次稳定恢复。仍需选 MSC 时，由用户选择；已核实任务完成后，才允许重新拔插并点「已选择 MSC，重新检查」。随后人工确认屏幕正常，才解除应用内待恢复状态。失败任务没有一键清锁入口，日志和永久锁保留。

管理员授权用于 USB 接管；固件封装不需要管理员权限。用户取消系统授权时不执行设备事务。未知授权助手结果保留待恢复状态。

卡刷说明会提示：将 DAT 命名为 `BODYDATA.DAT`，放到 SD 卡根目录并插入 SLOT1，从机身版本菜单进入软件更新。官方 4.00 参考状态是黑屏、存取灯 1→3→5 次分组闪烁、约 6 分钟后重启。异常的 5 慢+6 快、7 慢+7 快与正常进度分开说明；自定义包没有据此自动拔电或重复刷写的流程。

来源：[索尼中国 4.00 升级说明](https://service.sony.com.cn/download/firm/00003037.html)、[Sony A7R5 更新说明](https://www.sony.com/electronics/support/e-mount-body-ilce-7-series/ilce-7rm5/software/00292267)。这些现象描述官方更新包，不能作为自定义包实机成功的证据。

## 工程结构与实现

| 目录 | 职责 |
|---|---|
| `src-tauri/src/runtime.rs` | 资源摘要、固定动作、原生口令哈希、系统授权助手、提权隔离副本和退出 root 后导出 |
| `src-tauri/src/tasks.rs` | 单实例/任务锁、任务回执、待恢复状态、SSH 活动记录和人工屏幕确认 |
| `web/` | 无前端构建依赖的中文界面；自定义 Tauri 命令与本机文件选择 |
| `engine/device.py` | 分开的备份/更新与合并 SSH 事务；完整门槛通过后才认为任务完成 |
| `engine/host.py` | 当前端口绑定与 MSC 恢复观察；只在显式动作后运行 |
| `engine/firmware.py` | 16 种预构建补丁组合、原 DAT 引擎和卡刷 HTML |
| `sources/` | 原生载荷源码副本；原始模块不修改 |
| `scripts/` | 构建材料、固定 USB 库、依赖版权、封装与独立沙箱验证 |
| `tests/` | 真实会话调度器+协议替身、普通文件写入故障注入、路径/状态契约 |
| `prepared/` | 可重建运行材料；不包含原官方 DAT 或开发机分区镜像 |
| `verification/` | 载荷一致性、组合、测试、构建和独立运行证据 |

Rust 不重写既有 Senser 协议。管理员助手只接受四种固定动作，先把摘要匹配的引擎复制到 root 私有目录后运行；导出前退出 root 身份。用户路径不作为任意 shell 命令执行。SSH 的 load/start 两阶段共用同一 Channel 的序列号及失步标志，不能在阶段之间重建同步状态或发送 STOP。

载荷可变字符串位于独立 `.a7r5_cfg` 段，运行时只替换等长会话号与口令哈希。各模板均验证替换后与另一份独立重编译结果逐字节相同。新源码副本还把 AArch64 `O_NOFOLLOW` 修正为 32768；原封存源码不变。该修正与配置段均只有本机/静态证据，没有据此宣称机身动态加载通过。

用户任务保存在 `~/Library/Application Support/local.a7r5.studio/tasks/`。备份任务的外层 `result.json` 包含完整备份路径；不要选 `device/result.json` 代替外层结果。活动记录只说明本应用过去的操作，不证明相机现在仍运行服务。

## 开发构建和验证

开发机需要 Rust、Xcode Command Line Tools、现有 Python 构建环境、LLVM/lld 及项目原始材料。这些仅用于开发，不装进最终应用。构建步骤：

```sh
.venv/bin/python -B a7r5-desktop/scripts/build_usb.py
.venv/bin/python -B a7r5-desktop/scripts/prepare.py all
.venv/bin/python -B a7r5-desktop/scripts/notices.py
.venv/bin/python -B a7r5-desktop/scripts/prepare.py seal
MACOSX_DEPLOYMENT_TARGET=14.0 cargo build --manifest-path a7r5-desktop/src-tauri/Cargo.toml --release --locked
.venv/bin/python -B a7r5-desktop/scripts/package.py a7r5-desktop/dist/final
```

完整运行材料封存后才能构建 Rust。改引擎需同步 `prepared/engine/` 并重新 seal、构建、打包。macOS 27 的 strip 会破坏部分宏动态库的 LINKEDIT 对齐，因此构建覆盖保留宏符号；应用发布配置只剥离调试信息。内层本机库先临时签名，再封存摘要，最外层应用最后签名；不能用 `codesign --deep --force` 重写内层签名后沿用旧摘要。

```sh
cargo test --manifest-path a7r5-desktop/src-tauri/Cargo.toml --locked --offline
.venv/bin/python -B -m pytest a7r5-desktop/tests -q
.venv/bin/python -B a7r5-desktop/scripts/verify_independent.py 'a7r5-desktop/dist/final/A7R5 Studio.app'
```

独立验证会把应用和原 DAT 复制到项目外临时目录，在禁止读取工程、Homebrew、网络及 IOKit 的沙箱内运行；仅删除其新建临时副本，保留摘要与回执。不要对这些验证任务引入相机、原始磁盘、sudo 或网络登录。

功能组合的构建源码位于 `scripts/feature_builder.py`，不再从旧客户端导入；它使用原有四项功能材料与 LLVM 进行开发机重建，运行中的应用只使用随包预构建补丁。

构建缓存、GUI验证用DAT和旧测试包已按确认清单清理；`prepared/engine/`、`prepared/dependencies/`、验证回执及GUI更新说明保留。下次Rust测试或打包需要重新编译，图标集和Tauri schema会随构建重新生成。独立验证脚本默认选择最终包，历史回执中的临时输出路径不保证继续存在；清理不否定当时的验证结果。

2026-10-23 经用户确认，迁移并验证后删除 `a7r5-client/`、`a7r5-tools/`（含其历史任务）、根目录 `a7r5.sh` 与 `启动A7R5脚本.command`。此前的验证报告与来源清单保留为历史证据，已删除的来源不再是构建依赖；其他原模块、操作包、活动记录和失败锁保持不变，未恢复 `analysis/`。
