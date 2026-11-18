# A7R5 固件构建与工具工程（当前版本：4.28）

面向 **Sony A7R V / ILCE-7RM5、指定官方 4.00 固件前像、macOS Apple Silicon** 的固件构建与相机维护脚本工程。

当前对外最新主线版本为 **4.28**（基于已实机验证可正常开机的 **4.27** 基线，叠加 `lens-af-compat` 镜头 AF 能力适配与 `unified-look.c` 轻量防抖保护），并提供一键构建固件、一键更新信任环境、一键启动 SSH 以及 RAM Fastboot 快速脚本。

> **本项目仅限个人非商业研究使用，禁止商用。当前仅适配 macOS Apple Silicon，尚未适配 Windows、Linux 和 Intel Mac。** 用途限制适用于作者有权授权的原创内容；第三方代码继续遵循各自许可证，详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

> **验证状态：** 4.28 已完成离线双次确定性构建、RSA 研究签名、736,841 帧全量解密回读与 `e2fsck -fn` 校验，并**已由项目作者完成实机安装与全功能验证（正常开机与功能使用均正常）**。未做实机验证的实验性固件模块已统一归档至 [`a7r5-firmware-features/research/`](a7r5-firmware-features/research/README.md)。

---

## 目录

- [当前版本：4.28](#当前版本428)
- [快速脚本使用指南](#快速脚本使用指南)
- [环境准备与固定输入](#环境准备与固定输入)
- [存储卡升级与滤镜导入](#存储卡升级与滤镜导入)
- [工程结构](#工程结构)
- [离线测试与发布检查](#离线测试与发布检查)
- [交给 AI Agent 的完整提示词](#交给-ai-agent-的完整提示词)
- [参考与许可](#参考与许可)

---

## 当前版本：4.28

4.28 严格基于已实机验证可正常开机使用的 **4.27** 基线构建，仅包含当前稳定收敛的功能集合，不包含未实机验证的实验模块（如 `look-factory-six`、`photo-aspect-ratios`、4.23 阻塞状态机等）。

| 项目 | 说明与身份 |
|---|---|
| 目标机型与原厂基底 | Sony ILCE-7RM5 / A7R V，官方 **4.00** `BODYDATA.DAT`（754,525,608 字节，SHA-256 `51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2`） |
| 4.28 核心能力 | `look24`（24 槽自定义滤镜、SD 卡冷启动导入、横竖屏切组同步、微调容量提示与重置锁）、`look-fl2-fl3`（FL2/FL3 与机内 RAW 12 项备选目录）、`lens-af-compat`（镜头自动对焦能力过滤适配）、`unified-look.c` 轻量防抖（同目标去重与连续微调合并排队） |
| 底层不变式 | `WBI3`（`nflasha5` 首扇区偏移 `0x3` 为 `0x33`）、`nflasha15` 仅修改 3 个文件、`cpapp-b.bin` `0x108000..0x128000` 早期引导区零改动 |
| 输出 `BODYDATA.DAT` | 754,525,608 字节，SHA-256：`ed98e87af9e32fec7538a4579986528c1af694e4e55c855b3f7cebfb0eea4408` |
| 输出 `R5NATIVE.BIN` | 29,552 字节，SHA-256：`19e020fa48c79643aaf9526e9c720d38ec5a92c3df11d0852b0a93a25ee880b6` |
| 详细说明与归档 | [`releases/4.28-427-af-debounce-20261117/README.md`](a7r5-firmware-features/releases/4.28-427-af-debounce-20261117/README.md) · [`SOURCE-ARCHIVE.md`](a7r5-firmware-features/native24-combined/release428/SOURCE-ARCHIVE.md) |

---

## 快速脚本使用指南

仓库在 `scripts/`（以及 `a7r5-fastboot/`）提供了开箱即用的快速脚本，默认在仓库根目录执行。

### 1. 一键从原厂 4.00 构建 4.28 升级包

```sh
# 显式传入原厂 4.00 BODYDATA.DAT，并将最终产物导出到指定新目录
./scripts/build_428_from_400.sh /path/to/4.00/BODYDATA.DAT -o ~/Desktop/a7r5-4.28

# 若已将原厂 4.00 放置于 a7r5-firmware-images/官方升级包/BODYDATA.DAT，可直接无参执行
./scripts/build_428_from_400.sh
```

脚本会自动完成环境自检、原厂 4.00 解包、4.28 双次确定性编译（`runtime` + `rebuild`）、RSA 研究签名、736,841 帧回读与 `e2fsck -fn`，并核对输出 `BODYDATA.DAT` 与 `R5NATIVE.BIN` 的 SHA-256。

### 2. 一键更新研究签名信任环境（`scripts/trust_update/`）

用于将当前仓库的研究签名公钥写入相机更新器分区（`/dev/cnflasha1`，258 扇区 / 132,096 字节），使相机可校验并接纳由本项目研究私钥签名的自定义 `BODYDATA.DAT`。

- **双击入口**：`scripts/trust_update/一键更新信任环境.command`
- **命令行入口**：

```sh
# 1) 只读检测当前 USB 端口、连接模式（0e0a/0336/096f），不提权、不修改设备
.venv/bin/python -B scripts/trust_update/update_trust.py --check-only

# 2) 一键更新信任环境（支持 libjit 默认引擎或 kit 引擎）
.venv/bin/python -B scripts/trust_update/update_trust.py --engine libjit

# 3) 若相机滞留在 0336 服务模式，仅发送 STOP 恢复为普通 MSC 模式
.venv/bin/python -B scripts/trust_update/update_trust.py --restore-only
```

脚本特性：通过 macOS `ioreg` 动态识别任意 USB 端口、自动处理 `0336 -> STOP -> 0e0a` 预恢复、32 MiB 内存与 9 块扇区写入、机内整分区 SHA-256 与主机 9 块回读双重校验，并在完成后发送 `STOP` 恢复普通 MSC 模式。执行设备操作时会申请本机 `sudo` 管理员权限，请保持相机供电稳定与 MSC 连接，切勿中途拔线。

### 3. 一键启动相机 SSH 服务（`scripts/ssh_start/`）

用于通过 USB 服务通道在相机内存中按需拉起 `sshd`（监听 `0.0.0.0:2222`，默认 `ttl=0` 直至关机），并在结束后自动恢复相机为普通 MSC 模式。

- **双击入口**：`scripts/ssh_start/一键启动SSH.command`
- **命令行入口**：

```sh
# 只读检测当前 USB 连接与模式
.venv/bin/python -B scripts/ssh_start/start_ssh.py --check-only

# 交互输入 8~128 位密码并一键启动 SSH（推荐，不留明文密码）
.venv/bin/python -B scripts/ssh_start/start_ssh.py --engine libjit

# 指定相机 IPv4 与限时（秒）直接生成免确认 ssh 登录命令
.venv/bin/python -B scripts/ssh_start/start_ssh.py --ip 192.168.1.100 --ttl 3600
```

- **重复启动说明**：若相机内已有运行中的 SSH 服务，重复运行脚本不会强制终止或破坏现有 SSH 会话（40 秒超时后安全退出且不发送 `STOP`）；如需重新设置密码或重启 `sshd`，请先关闭再开启相机电源。
- 完成后终端会输出带专属 `known_hosts` 的完整 `/usr/bin/ssh ... -p 2222 root@CAMERA_IPV4` 登录命令。

### 4. RAM Fastboot 快速脚本（`a7r5-fastboot/`）

用于结合 RP2040-Zero 硬件触发 RAM Fastboot，进行分区只读采集与 SD 卡强制升级触发（详见 [`a7r5-fastboot/README.md`](a7r5-fastboot/README.md) 与 [`FASTBOOT操作与诊断总结.md`](a7r5-fastboot/FASTBOOT操作与诊断总结.md)）：

- `a7r5-fastboot/1_enter_fastboot.sh`：自动查找 RP2040（`0x2E8A`）串口并循环触发 RAM Fastboot 直至 USB 激活成功。
- `a7r5-fastboot/2_activate_usb.sh`：激活 Sony Fastboot USB 接口（`18d1:4ee0`）并读取分区表、SDM2 与 `nflasha2` 状态（支持 `--quick`）。
- `a7r5-fastboot/3_trigger_sd_update.sh`：受限写入 `nflasha2` 的 `/updater/mode5` 触发标志并重启进入 SD 卡强制升级流程。

---

## 环境准备与固定输入

### 1. 宿主机工具链（macOS Apple Silicon）

安装 Xcode Command Line Tools 与 Homebrew 依赖：

```sh
xcode-select --install
brew install uv llvm lld e2fsprogs libusb
```

### 2. 初始化 Python 3.14 虚拟环境

在仓库根目录执行：

```sh
uv python install 3.14
A7R5_BUILD_PYTHON="$(uv python find 3.14)" sh scripts/bootstrap.sh
chmod 600 a7r5-dat-tool/keys/research-signing-private.pem
```

- `.venv/`：用于 4.28 构建、快速脚本与离线测试。
- `a7r5-dat-tool/.venv/`：用于 DAT 解析、加解密与验签工具。

### 3. 准备固定输入

| 材料 | 默认位置 / 来源 | 要求 |
|---|---|---|
| 官方 4.00 `BODYDATA.DAT` | `a7r5-firmware-images/官方升级包/BODYDATA.DAT`（或构建时传入路径） | 754,525,608 字节，SHA-256 `51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2` |
| 一号明文分区前像（可选，用于独立对比） | `a7r5-firmware-images/标准固件_19项/明文分区_17项/cnflasha1.img` | 25,100,288 字节，SHA-256 `acf32d30dd883ed349738e66fb081e85e0d6a3c746f5e3ca169031e8d69ed731` |
| 目标 `libc` SDK 与 SFTP | `a7r5-exec/sdk/libc-2.25.so`、`a7r5-ssh/ssh-service/original-view/vendor/sftp-server.arm64` | 按 [`scripts/local-inputs.json`](scripts/local-inputs.json) 校验；SFTP 可用 `scripts/prepare_sftp.py` 从 Debian 包提取 |

---

## 存储卡升级与滤镜导入

1. 先通过 `scripts/trust_update/update_trust.py` 完成与当前研究公钥配对的更新器信任配置。
2. 备份存储卡资料，确认相机电池电量充足（建议取下竖拍手柄）。
3. 将构建生成的 4.28 **`BODYDATA.DAT`** 复制到已格式化 SD 卡的**根目录**（不要放入 `DCIM`，不要修改文件名），安全弹出后插入相机 **SLOT1**。
4. 开机进入 `MENU → 设置 → 设置选项 → 版本 → 软件更新`，按屏幕提示确认并等待升级完成重启；升级过程中切勿断电或拔卡。
5. 固件升级完成后，将随包生成的 **`R5NATIVE.BIN`** 复制到 SD 卡（按 `look24` 模块说明进行冷启动导入），即可在机内创意外观自定义组中使用 24 槽滤镜。

---

## 工程结构

```text
.
├── scripts/
│   ├── build_428_from_400.sh       一键从官方 4.00 构建 4.28 固件包
│   ├── trust_update/               一键更新研究签名信任环境（libjit / kit）
│   ├── ssh_start/                  一键启动相机 SSH 服务（libjit / kit）
│   ├── bootstrap.sh                创建并初始化 Python 3.14 虚拟环境
│   └── release_check.py            源码发布边界与凭据检查
├── a7r5-firmware-features/
│   ├── native24-combined/release428/  4.28 自包含构建源码与端到端流水线
│   ├── releases/4.28-427-af-debounce-20261117/  4.28 交付说明与已知问题清单
│   ├── look24/                     24 槽自定义滤镜模块（4.28 核心）
│   ├── look-fl2-fl3/               FL2 / FL3 与 RAW 12 项备选目录（4.28 核心）
│   ├── lens-af-compat/             镜头 AF 能力过滤适配（4.28 新增）
│   └── research/                   未实机验证的实验模块与历史研究归档
├── a7r5-dat-tool/                  DAT 容器解包、验签、组件替换与签名封包
├── a7r5-desktop/                   桌面客户端工程（macOS Apple Silicon）
├── a7r5-fastboot/                  RAM Fastboot 救砖、诊断与快速脚本
├── a7r5-exec/                      短命令与脚本执行工具
├── a7r5-libjit/                    libJit 加载协议与恢复研究
├── a7r5-ssh/                       SSH 服务载荷与旧版分阶段入口
├── a7r5-updater-trust/             更新器信任算法与专用部署器
├── a7r5-implementation-kit/        分区转存与受限 root 执行研究
├── a7r5-qemu/                      可选 QEMU 菜单与协议模拟研究
├── sony-r5-colorlab/               Color Lab 色彩训练与 R5NATIVE.BIN 工具
├── a7r5-firmware-images/           本地官方固件与分区镜像目录（不入 Git）
├── docs/                           构建输入说明与 AI Agent 提示词
└── tests/                          仓库发布边界与研究路径测试
```

---

## 离线测试与发布检查

以下测试仅在本地运行，不连接相机、不枚举 USB：

```sh
# 根目录发布边界与路径测试
.venv/bin/python -B -m unittest discover -s tests -v

# 4.28 补丁不变式与发布配置测试
.venv/bin/python -B -m pytest -p no:cacheprovider \
  a7r5-firmware-features/native24-combined/release428/test_patch_428.py \
  a7r5-firmware-features/native24-combined/release428/test_release.py -q

# 快速脚本离线单元测试与 USB 只读检查
.venv/bin/python -B scripts/trust_update/test_trust_update.py
.venv/bin/python -B scripts/ssh_start/test_ssh_start.py

# DAT 工具测试与发布检查
.venv/bin/python -B -m pytest -p no:cacheprovider a7r5-dat-tool/tests -q
.venv/bin/python -B scripts/release_check.py
```

---

## 交给 AI Agent 的完整提示词

用于引导 AI Agent 从源码分析开始，完成 **4.28** 构建、离线校验以及在获得明确授权后执行快速脚本与相机更新验收。完整文本同步维护于 [`docs/AI_AGENT_PROMPT.md`](docs/AI_AGENT_PROMPT.md)。

<details>
<summary>展开完整 Prompt：4.28 构建校验与快速脚本操作流程</summary>

```text
你是本次 Sony A7R V (ILCE-7RM5) 固件研究与工具工程 Agent。请从源码调查开始，围绕当前最新稳定主线 **4.28** 完成研究签名信任方案分析、4.28 升级包构建与离线校验，并按需提供快速脚本或相机更新验收步骤。用简体中文沟通，所有结论必须对应当前代码、实际命令输出或回执。

任务参数（未填写则使用括号中的默认值）：
- 仓库：https://github.com/Liwenru88/a7r5-rea.git
- 工作目录：（新建 a7r5-rea；已有目录则保留全部改动）
- 目标版本：（4.28，基于已实机验证开机的 4.27 基线 + `lens-af-compat` + `unified-look.c` 轻量防抖）
- 原厂 BODYDATA.DAT：（先查本地输入清单，缺失后向我索取合法取得的文件）
- 本轮设备授权：（无；默认只做离线工作，不枚举 USB、不连 SSH、不写卡、不操作相机）

一、获取与理解工程
1. 新目录使用 git clone 拉取上述仓库，记录分支、提交 SHA 和工作区状态。目录已存在时先检查 remote、分支和未提交改动；可 fetch 获取远端信息，但不得 reset、清理、覆盖或自动合并用户改动。
2. 先读根 `README.md`、`THIRD_PARTY_NOTICES.md`，以及：
   - `docs/build-inputs.md`、`docs/source-publication.md`、`scripts/local-inputs.json`、`scripts/release_check.py`；
   - `a7r5-firmware-features/README.md`；
   - `a7r5-firmware-features/native24-combined/release428/SOURCE-ARCHIVE.md` 与 `build_428_from_400.py`；
   - `a7r5-firmware-features/releases/4.28-427-af-debounce-20261117/README.md` 与 `KNOWN-ISSUES.json`；
   - `scripts/trust_update/update_trust.py` 与 `scripts/ssh_start/start_ssh.py`；
   - `a7r5-fastboot/README.md`（仅当涉及 Fastboot 诊断或救砖时）。
   `a7r5-firmware-features/research/` 下存放的是未实机验证的实验模块与历史研究材料，**不要**把其中的未验证模块或历史版本（如 4.19、4.17 等）当作当前稳定主线推荐。
3. 封印目录约束：不要修改 `a7r5-desktop`、`a7r5-exec`、`a7r5-updater-trust`、`a7r5-ssh` 下的源码。

二、离线准备与 4.28 构建（在授权范围内完成）
4. 优先复用项目 `.venv/bin/python`；缺少依赖时按锁文件准备环境，不全局安装 Python 包。当前主线仅适配 macOS Apple Silicon；含固件构建需要 `/opt/homebrew/opt/llvm/bin/clang`、`/opt/homebrew/opt/lld/bin/ld.lld`、`/opt/homebrew/opt/e2fsprogs/sbin/e2fsck`、`/usr/bin/openssl` 与 Xcode Command Line Tools (`clang`)。
5. 原厂基底必须是适配的 ILCE-7RM5 4.00 `BODYDATA.DAT`：754,525,608 字节，SHA-256 为 `51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2`。核对研究公私钥配对（`a7r5-dat-tool/keys/`）；不生成新身份替代机内已有身份，不输出私钥、密码或设备认证载荷。
6. 使用仓库根目录一键脚本构建 4.28：
   `./scripts/build_428_from_400.sh /path/to/4.00/BODYDATA.DAT -o /new/output/dir`
   验证输出产物摘要：
   - `BODYDATA.DAT` SHA-256：`ed98e87af9e32fec7538a4579986528c1af694e4e55c855b3f7cebfb0eea4408`
   - `R5NATIVE.BIN` SHA-256：`19e020fa48c79643aaf9526e9c720d38ec5a92c3df11d0852b0a93a25ee880b6`
7. 严格核对 4.28 底层不变式：
   - **WBI3 策略**：`nflasha5` 首扇区保留原厂快照，仅将偏移 `0x3` 的 1 字节由 `WBI2` 改为 `WBI3`（`0x32 -> 0x33`），严禁清零首 512 字节或擦除整分区；
   - **`nflasha15`**：仅修改 3 个文件；
   - **`cpapp-b.bin`**：`0x108000..0x128000` 早期引导区保持零改动，仅在 `.text` 安全区（`0xbef780..0xbef7ac`）写入 `lens-af-compat` 辅助读取器并替换 5 处调用；
   - **`unified-look.c`**：仅保留轻量防抖，严禁引入 4.23 阻塞性状态机改动。
8. 运行 4.28 与快速脚本的离线单元测试（`test_patch_428.py`、`test_release.py`、`scripts/trust_update/test_trust_update.py`、`scripts/ssh_start/test_ssh_start.py` 及根目录 `tests/`），记录实际命令与退出码。

三、快速设备脚本与授权门禁
9. 仅在我明确授权本轮连接或设备操作后，才可执行以下快速脚本：
   - **只读 USB 状态检查**：`.venv/bin/python -B scripts/trust_update/update_trust.py --check-only`
   - **一键更新信任环境**：`.venv/bin/python -B scripts/trust_update/update_trust.py --engine libjit`
   - **一键启动 SSH**：`.venv/bin/python -B scripts/ssh_start/start_ssh.py --engine libjit --ttl 0`
   - **RAM Fastboot 快速脚本**（仅在救砖/诊断并获得明确授权时）：`a7r5-fastboot/1_enter_fastboot.sh`、`2_activate_usb.sh`、`3_trigger_sd_update.sh`
10. 协议失步、短读/短写、摘要不符、写后验证失败或状态未知时，立即停止后续自动动作并保存 `.local/` 日志现场；不要重试写入、删锁或伪造成功。
11. 存储卡升级流程：将构建好的 `BODYDATA.DAT` 复制到已格式化的 SD 卡**根目录**（精确文件名，不要放入 `DCIM`），插回相机 **SLOT1**，在充足供电下通过 `MENU → 设置 → 设置选项 → 版本 → 软件更新` 执行。升级完成后再将 `R5NATIVE.BIN` 放入 SD 卡按 `look24` 说明冷启动导入。

四、交付格式
最终必须提供：源码提交身份与改动摘要；输入与产物 SHA-256；实际执行的构建/测试命令及退出码；是否连接过相机或执行设备操作；下一步操作建议与未验证边界。必须严格区分「已实现」「离线验证通过」「项目历史实机验证（4.28 稳定主线）」「本轮实机操作（待执行/已完成）」，不得把离线通过或历史实机记录等同于本轮新改动已实机验收。
```

</details>

---

## 参考与许可

- 原创代码、文档与整合实现仅限个人非商业研究使用。
- 上游参考与第三方代码（如 `Hearts-Ace/sony-a7r5-custom-firmware`、`Hearts-Ace/sony-r5-colorlab`、`ma1co/Sony-PMCA-RE`、`chocotan/a7c2-re`、`DavidBuchanan314/ILCE-7M4-RE`、Tauri、libusb 等）继续遵循其原有许可证，详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 与各模块许可文件。
