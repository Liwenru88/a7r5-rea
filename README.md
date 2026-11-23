# A7R5 固件构建与工具工程（当前版本：4.31）

面向 **Sony A7R V / ILCE-7RM5、指定官方 4.00 固件前像、macOS Apple Silicon** 的固件构建与相机维护脚本工程。

当前对外最新稳定主线版本为 **4.31**（基于 **4.28** 稳定基线，叠加 **6 档自定义照片纵横比 JPEG/HEIF 全功能裁切**、原厂创意外观放行隔离修复与冷启动加固、AP BSS 安全隔离区扩容），并提供一键构建固件、一键更新信任环境、一键启动 SSH、一键清理 `/tmp/jiritsu/` 残留以及 RAM Fastboot 快速脚本。

> **本项目仅限个人非商业研究使用，禁止商用。当前仅适配 macOS Apple Silicon，尚未适配 Windows、Linux 和 Intel Mac。** 用途限制适用于作者有权授权的原创内容；第三方代码继续遵循各自许可证，详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

> **验证状态：** 4.31 与其底层 4.28 基线均已由项目作者完成**实机安装与全功能验证**；未纳入主线的实验性固件模块归档于 [`a7r5-firmware-features/research/`](a7r5-firmware-features/research/README.md)。

---

## 目录

- [当前版本：4.31](#当前版本431)
- [快速脚本使用指南](#快速脚本使用指南)
- [环境准备与固定输入](#环境准备与固定输入)
- [存储卡升级与滤镜导入](#存储卡升级与滤镜导入)
- [工程结构](#工程结构)
- [离线测试与发布检查](#离线测试与发布检查)
- [交给 AI Agent 的完整提示词](#交给-ai-agent-的完整提示词)
- [参考项目、滤镜来源与许可](#参考项目滤镜来源与许可)

---

## 当前版本：4.31

4.31 基于已实机验证的 **4.28** 自包含基线构建，集成全部稳定功能并完成 6 档自定义照片纵横比（JPEG / HEIF 全功能裁切）。

| 项目 | 说明与身份 |
|---|---|
| 目标机型与原厂基底 | Sony ILCE-7RM5 / A7R V，官方 **4.00** `BODYDATA.DAT`（754,525,608 字节，SHA-256 `51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2`） |
| 4.31 核心能力 | 继承 4.28 全部能力（`look24` 24 槽滤镜、`look-fl2-fl3`、`lens-af-compat`、轻量防抖），新增 **6 档自定义照片纵横比**（`17:6`、`65:24`、`5:4`、`7:6`、`1.91:1`、`2.35:1`，支持 **JPEG 与 HEIF 4:2:0/4:2:2、单拍与 RAW+HEIF、全画幅 L/M/S 及 APS-C L/M/S** 全功能裁切）、`bank_unavailable_only()` 原厂创意外观放行、冷启动 CP 探测加固及 AP BSS 安全隔离扩容（`0x8f13000`） |
| 底层不变式 | `WBI3`（`nflasha5` 首扇区偏移 `0x3` 为 `0x33`）、`nflasha15` 修改 4 个文件（`appFw.so`、`libmpr.so`、2 个 `.uxc`）、`nflasha8` 更新 `cpapp-b.bin`、`nflasha3` 原簇链更新 `AV-CAM.BIN` |
| 输出 `R5NATIVE.BIN` | 58,976 字节（24 槽精选默认包），SHA-256：`c8777b689e9c37506abbee49a5dc3964d0000e37b27ef033625122eaf5b77e4f` |
| 详细说明与归档 | [`release431/PACKAGE-README.md`](a7r5-firmware-features/native24-combined/release431/PACKAGE-README.md) · [`4.28 基线归档`](a7r5-firmware-features/releases/4.28-427-af-debounce-20261117/README.md) |

---

## 快速脚本使用指南

仓库在 `scripts/`（以及 `a7r5-fastboot/`）提供了开箱即用的快速脚本，默认在仓库根目录执行。

### 1. 一键从原厂 4.00 构建 4.31 升级包

```sh
# 显式传入原厂 4.00 BODYDATA.DAT，并将最终产物导出到指定新目录
./scripts/build_431_from_400.sh /path/to/4.00/BODYDATA.DAT -o ~/Desktop/a7r5-4.31

# 若已将原厂 4.00 放置于 a7r5-firmware-images/官方升级包/BODYDATA.DAT，可直接无参执行
./scripts/build_431_from_400.sh
```

（如需仅构建不含画幅裁切的 4.28 底层基线，可执行 `./scripts/build_428_from_400.sh`。）

脚本会自动完成环境自检、原厂 4.00 解包、4.28/4.31 编译、RSA 研究签名、736,841 帧回读与 `e2fsck -fn`，并核对输出 `BODYDATA.DAT` 与 `R5NATIVE.BIN` 的构建状态。

### 2. 一键更新研究签名信任环境（`scripts/trust_update/`）

用于将当前仓库的研究签名公钥写入相机更新器分区（`/dev/cnflasha1`，258 扇区 / 132,096 字节），使相机可校验并接纳由本项目研究私钥签名的自定义 `BODYDATA.DAT`。

- **双击 / 快捷入口**：`scripts/trust_update/一键更新信任环境.command`（默认使用 `libjit`，也可命令行传入 `kit`：`scripts/trust_update/一键更新信任环境.command kit`）
- **命令行入口**：

```sh
# 1) 只读检测当前 USB 端口、连接模式（0e0a/0336/096f），不提权、不修改设备
.venv/bin/python -B scripts/trust_update/update_trust.py --check-only

# 2) 一键更新信任环境（支持 libjit 与 kit；若 /tmp/jiritsu 槽位已满建议使用 kit）
.venv/bin/python -B scripts/trust_update/update_trust.py --engine libjit
.venv/bin/python -B scripts/trust_update/update_trust.py --engine kit

# 3) 若相机滞留在 0336 服务模式，仅发送 STOP 恢复为普通 MSC 模式
.venv/bin/python -B scripts/trust_update/update_trust.py --restore-only
```

脚本特性：通过 macOS `ioreg` 动态识别任意 USB 端口、自动处理 `0336 -> STOP -> 0e0a` 预恢复、32 MiB 内存与 9 块扇区写入、机内整分区 SHA-256 与主机 9 块回读双重校验，并在完成后发送 `STOP` 恢复普通 MSC 模式。`kit` 引擎全部载荷走 `/tmp_wbshd/` 内存盘，**零写入 `/tmp/jiritsu/`**。执行设备操作时会申请本机 `sudo` 管理员权限，请保持相机供电稳定与 MSC 连接，切勿中途拔线。

### 3. 一键启动相机 SSH 服务（`scripts/ssh_start/`）

用于通过 USB 服务通道在相机内存中按需拉起 `sshd`（监听 `0.0.0.0:2222`，默认 `ttl=0` 直至关机），并在结束后自动恢复相机为普通 MSC 模式。程序（`.service`/`.session`/`.sftp`）与 `kit` 触发载荷均平铺于 `/tmp_wbshd/` 内存盘，`kit` 引擎实现**零写入 `/tmp/jiritsu/` 持久分区**。

- **双击 / 快捷入口**：`scripts/ssh_start/一键启动SSH.command`（默认 `libjit`；命令行可传参数切换：`scripts/ssh_start/一键启动SSH.command kit`）
- **命令行入口**：

```sh
# 只读检测当前 USB 连接与模式
.venv/bin/python -B scripts/ssh_start/start_ssh.py --check-only

# 交互输入 8~128 位密码并一键启动 SSH（推荐 kit 或 libjit，不留明文密码）
.venv/bin/python -B scripts/ssh_start/start_ssh.py --engine kit
.venv/bin/python -B scripts/ssh_start/start_ssh.py --engine libjit

# 指定相机 IPv4 与限时（秒）直接生成免确认 ssh 登录命令
.venv/bin/python -B scripts/ssh_start/start_ssh.py --engine kit --ip 192.168.1.100 --ttl 3600
```

- **重复启动说明**：相机重启后可随时重新启动 SSH（会生成新公钥与新 `known_hosts`，请使用当次输出的新 `login_command`）。若相机未重启且原有 `sshd` 仍在运行，重复执行不会破坏现有会话（约 40 秒等待超时退出且不发送 `STOP`，相机停留在 `0336` 模式；随后执行 `.venv/bin/python -B scripts/trust_update/update_trust.py --restore-only` 或重启即可恢复普通 MSC）。
- 完成后终端会输出带专属 `known_hosts` 的完整 `/usr/bin/ssh ... -p 2222 root@CAMERA_IPV4` 登录命令；连上 SSH 后还可使用只读诊断脚本 [`scripts/ssh_start/dump_filter_diag.py`](scripts/ssh_start/dump_filter_diag.py) 抓取 `appFw.so` 滤镜状态。

### 4. 一键扫描与清理 `/tmp/jiritsu/` 残留（`scripts/clean_jiritsu/`）

相机 `/tmp/jiritsu` 挂载自持久化分区 `/dev/nflasha6`（FAT12 文件系统，根目录固定仅 512 个目录槽位）。若历史研究或失败任务留下的文件占满槽位，写入 `/tmp/jiritsu/`（含 `libjit` 必需的 `/tmp/jiritsu/libJit.so`）会报 `0x10000008`（断电重启不会清空该分区）。本工具通过 **`kit` + `/tmp_wbshd/` 内存盘**执行，可在槽位已满状态下直接运行并恢复普通 MSC。

- **双击 / 快捷入口**：`scripts/clean_jiritsu/一键清理Jiritsu.command`
- **命令行入口**：

```sh
# 1) 只读扫描：枚举 /tmp/jiritsu/ 文件清单与 FAT12 槽位占用情况，不删除任何文件
.venv/bin/python -B scripts/clean_jiritsu/clean_jiritsu.py --scan-only

# 2) 一键白名单安全清理（仅删除匹配 libJit.so 或 a7r5-[jit-|ljssh-]<32hex>.* 的普通文件）
.venv/bin/python -B scripts/clean_jiritsu/clean_jiritsu.py

# 3) 若扫描清单中还有明确需要移除的其他单级研究残留文件名，可额外指定
.venv/bin/python -B scripts/clean_jiritsu/clean_jiritsu.py --extra-name 残留文件名
```

安全边界：原生载荷仅对普通文件（跳过所有目录与符号链接）执行精确白名单删除，**不会删除任何原厂系统文件、子目录或未匹配规则的文件**；每次执行前后完整文件列表与统计结果均保存在 `.local/clean-jiritsu-*/entries.json`。

### 5. RAM Fastboot 快速脚本（`a7r5-fastboot/`）

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

- `.venv/`：用于 4.31 / 4.28 固件构建、快速设备脚本与离线测试。
- `a7r5-dat-tool/.venv/`：用于 DAT 解析、加解密与验签工具。

### 3. 准备固定输入

| 材料 | 默认位置 / 来源 | 要求 |
|---|---|---|
| 官方 4.00 `BODYDATA.DAT` | `a7r5-firmware-images/官方升级包/BODYDATA.DAT`（或构建时传入路径） | 754,525,608 字节，SHA-256 `51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2` |
| 一号明文分区前像（可选，用于独立对比） | `a7r5-firmware-images/标准固件_19项/明文分区_17项/cnflasha1.img` | 25,100,288 字节，SHA-256 `acf32d30dd883ed349738e66fb081e85e0d6a3c746f5e3ca169031e8d69ed731` |
| 目标 `libc` SDK 与 SFTP | `a7r5-exec/sdk/libc-2.25.so`、`a7r5-ssh/ssh-service/original-view/vendor/sftp-server.arm64` | 按 [`scripts/local-inputs.json`](scripts/local-inputs.json) 校验；SFTP 可用 `scripts/prepare_sftp.py` 从 Debian 包提取 |

---

## 存储卡升级与滤镜导入

1. 先通过 `scripts/trust_update/update_trust.py` 完成与当前研究公钥配对的更新器信任配置（推荐 `--engine kit` 或清理后用 `libjit`）。
2. 备份存储卡资料，确认相机电池电量充足（建议取下竖拍手柄）。
3. 将构建生成的 4.31 **`BODYDATA.DAT`** 复制到已格式化 SD 卡的**根目录**（不要放入 `DCIM`，不要修改文件名），安全弹出后插入相机 **SLOT1**。
4. 开机进入 `MENU → 设置 → 设置选项 → 版本 → 软件更新`，按屏幕提示确认并等待升级完成重启；升级过程中切勿断电或拔卡。
5. 固件升级完成后，将随包生成的 **`R5NATIVE.BIN`** 复制到 SD 卡（按 `look24` 模块说明进行冷启动导入），即可在机内创意外观自定义组中使用 24 槽滤镜（`sony-r5-colorlab/filters/` 亦收录了配套滤镜预设库与样张）。

---

## 工程结构

```text
.
├── scripts/
│   ├── build_431_from_400.sh       一键从官方 4.00 构建 4.31 固件包
│   ├── build_428_from_400.sh       一键从官方 4.00 构建 4.28 基线固件包
│   ├── trust_update/               一键更新研究签名信任环境（libjit / kit）
│   ├── ssh_start/                  一键启动相机 SSH 服务（libjit / kit）与只读诊断脚本
│   ├── clean_jiritsu/              一键扫描与白名单安全清理 /tmp/jiritsu/（kit）
│   ├── bootstrap.sh                创建并初始化 Python 3.14 虚拟环境
│   └── release_check.py            源码发布边界与凭据检查
├── a7r5-firmware-features/
│   ├── native24-combined/release431/  4.31 主线构建源码、6 档画幅裁切与端到端流水线
│   ├── native24-combined/release428/  4.28 稳定基线自包含构建源码
│   ├── releases/4.28-427-af-debounce-20261117/  4.28 交付说明与已知问题清单
│   ├── look24/                     24 槽自定义滤镜模块
│   ├── look-fl2-fl3/               FL2 / FL3 与 RAW 12 项备选目录
│   ├── lens-af-compat/             镜头 AF 能力过滤适配
│   └── research/                   未实机验证的实验模块与历史研究归档
├── a7r5-dat-tool/                  DAT 容器解包、验签、组件替换与签名封包
├── a7r5-desktop/                   桌面客户端工程（macOS Apple Silicon）
├── a7r5-fastboot/                  RAM Fastboot 救砖、诊断与快速脚本
├── a7r5-exec/                      短命令与脚本执行工具
├── a7r5-libjit/                    libJit 加载协议与恢复研究
├── a7r5-ssh/                       SSH 服务载荷与旧版分阶段入口
├── a7r5-updater-trust/             更新器信任算法与专用部署器
├── a7r5-implementation-kit/        分区转存与受限 root 执行研究
├── a7r5-qemu/                      QEMU 菜单与协议模拟研究
├── sony-r5-colorlab/               Color Lab 色彩训练、Web 工作台、滤镜库与 R5NATIVE.BIN 工具
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

# 4.31 与 4.28 补丁不变式及发布配置测试
.venv/bin/python -B -m pytest -p no:cacheprovider \
  a7r5-firmware-features/native24-combined/release431/test_patch_431.py \
  a7r5-firmware-features/native24-combined/release428/test_patch_428.py \
  a7r5-firmware-features/native24-combined/release428/test_release.py -q

# 快速脚本离线单元测试（更新信任 / SSH 启动 / Jiritsu 清理）
.venv/bin/python -B scripts/trust_update/test_trust_update.py
.venv/bin/python -B scripts/ssh_start/test_ssh_start.py
.venv/bin/python -B scripts/clean_jiritsu/test_clean_jiritsu.py

# DAT 工具测试与发布检查
.venv/bin/python -B -m pytest -p no:cacheprovider a7r5-dat-tool/tests -q
.venv/bin/python -B scripts/release_check.py
```

---

## 交给 AI Agent 的完整提示词

用于引导 AI Agent 从源码分析开始，完成 **4.31** 构建、离线校验以及在获得明确授权后执行快速脚本与相机维护操作。完整文本同步维护于 [`docs/AI_AGENT_PROMPT.md`](docs/AI_AGENT_PROMPT.md)。

<details>
<summary>展开完整 Prompt：4.31 构建与快速脚本操作引导</summary>

````text
你是本次 Sony A7R V (ILCE-7RM5) 固件研究与工具工程 Agent。请从源码分析出发，围绕当前最新稳定主线 **4.31** 开展固件构建、离线校验，并按需在获得设备授权后执行相机快速维护脚本。用简体中文沟通，所有结论必须对应当前代码、实际命令输出或实机日志。

任务参数（未填写则使用括号中的默认值）：
- 仓库：https://github.com/Liwenru88/a7r5-rea.git
- 工作目录：（新建 a7r5-rea；已有目录则保留全部改动）
- 目标版本：（4.31，基于 **4.28** 稳定基线，集成 6 档自定义照片纵横比 JPEG/HEIF 全功能裁切、原厂创意外观放行隔离修复与冷启动加固、AP BSS 安全隔离区扩容）
- 原厂 BODYDATA.DAT：（先查本地默认输入路径；缺失时向用户确认合法取得的文件路径）
- 本轮设备授权：（无；默认仅做离线工作，不连接 USB、不连 SSH、不写卡、不操作相机）

一、获取与理解工程
1. 新目录使用 git clone 拉取上述仓库，记录分支与提交 SHA。目录已存在时先检查工作区和未提交改动；不得擅自 reset、丢弃或覆盖用户已有改动。
2. 先读根 `README.md`、`THIRD_PARTY_NOTICES.md`，按任务需要再查看：
   - `docs/build-inputs.md`、`docs/source-publication.md`、`scripts/release_check.py`；
   - `a7r5-firmware-features/README.md`；
   - `a7r5-firmware-features/native24-combined/release431/PACKAGE-README.md` 与 `build_431_from_400.py`；
   - `a7r5-firmware-features/native24-combined/release428/SOURCE-ARCHIVE.md`（4.28 底层基线）；
   - `scripts/trust_update/update_trust.py`、`scripts/ssh_start/start_ssh.py` 与 `scripts/clean_jiritsu/clean_jiritsu.py`；
   - `a7r5-fastboot/README.md`（仅当涉及 Fastboot 诊断或救砖时）。
   `a7r5-firmware-features/research/` 下存放的是未实机验证的实验模块与历史研究归档，不要把其中的未验证模块当作当前稳定主线推荐。
3. 保护已有研究包边界：除非用户明确要求，不要随意改动 `a7r5-desktop`、`a7r5-exec`、`a7r5-updater-trust`、`a7r5-ssh` 下的封存源码。

二、离线准备与 4.31 构建（在授权范围内完成）
4. 优先复用项目 `.venv/bin/python`；缺少依赖时按仓库说明准备环境，不全局污染系统 Python。当前主线主要适配 macOS Apple Silicon，固件构建依赖 `/opt/homebrew/opt/llvm/bin/clang`、`/opt/homebrew/opt/lld/bin/ld.lld`、`/opt/homebrew/opt/e2fsprogs/sbin/e2fsck`、`/usr/bin/openssl` 与 Xcode Command Line Tools (`clang`)。
5. 原厂基底采用适配的 ILCE-7RM5 4.00 `BODYDATA.DAT`（由构建脚本按当前工程逻辑自行识别和校验，不在提示词中硬编码固定哈希或字节数）；核对研究公私钥工具链存在且权限正确（`a7r5-dat-tool/keys/`），不随意替换机内或仓库现有身份，不在输出中泄露私钥或密码。
6. 使用仓库根目录一键脚本构建 4.31：
   ```sh
   ./scripts/build_431_from_400.sh /path/to/4.00/BODYDATA.DAT -o /new/output/dir
```
   以构建脚本实际通过状态与生成的 `BODYDATA.DAT`、`R5NATIVE.BIN` 产物路径为准（不强行写死校验固定哈希）。
7. 保持各模块当前源码设计原则与对应单元测试一致（如 `WBI3` 分区策略、`nflasha3` 原簇链更新、早期引导区不变等），一切具体偏移与结构约束以当前版本源码和单元测试为准。
8. 按需运行离线单元测试并记录实际执行命令与结果：
   - `a7r5-firmware-features/native24-combined/release431/test_patch_431.py`
   - `a7r5-firmware-features/native24-combined/release428/test_patch_428.py`、`test_release.py`
   - `scripts/trust_update/test_trust_update.py`、`scripts/ssh_start/test_ssh_start.py`、`scripts/clean_jiritsu/test_clean_jiritsu.py`
   - 根目录 `tests/` 与 `scripts/release_check.py`

三、快速设备脚本与授权门禁
9. 仅在用户明确授权连接或操作相机后，才可执行以下快速脚本：
   - **只读 USB 状态检查**：`.venv/bin/python -B scripts/trust_update/update_trust.py --check-only`
   - **一键更新信任环境**：`.venv/bin/python -B scripts/trust_update/update_trust.py --engine libjit`（或使用 `--engine kit` / 双击 `scripts/trust_update/一键更新信任环境.command`，支持动态 `ioreg` 端口识别与 `0336` 预恢复；`kit` 模式全部走 `/tmp_wbshd/` 内存盘，零写入 `/tmp/jiritsu/`）
   - **一键启动 SSH**：`.venv/bin/python -B scripts/ssh_start/start_ssh.py --engine kit --ttl 0`（亦支持 `libjit` 或双击 `scripts/ssh_start/一键启动SSH.command`；如已有 SSH 在运行会超时退出并保留原会话，不发送 `STOP`，可通过 `update_trust.py --restore-only` 恢复普通 MSC）
   - **一键扫描/清理 `/tmp/jiritsu/` 残留**：`.venv/bin/python -B scripts/clean_jiritsu/clean_jiritsu.py --scan-only`（只读查看 FAT12 512 槽位与文件清单；去掉 `--scan-only` 按严格白名单清理研究残留文件以恢复 `libjit` 槽位）
   - **RAM Fastboot 快速脚本**（仅在救砖/诊断并获得明确授权时）：`a7r5-fastboot/1_enter_fastboot.sh`、`2_activate_usb.sh`、`3_trigger_sd_update.sh`
10. 设备操作过程中遇到协议失步、短读/短写、校验失败或异常错误时，立即停止后续动作并保留 `.local/` 日志现场，如实汇报原因与相机当前模式，不要盲目重试写入或伪造成功。
11. 存储卡升级流程：将构建生成的 `BODYDATA.DAT` 复制到已格式化 SD 卡根目录，插回相机 **SLOT1**，在充足供电下通过 `MENU → 设置 → 设置选项 → 版本 → 软件更新` 升级；完成后将 `R5NATIVE.BIN` 放入 SD 卡按 `look24` 说明冷启动导入。

四、输出汇报
汇报应真实、简明、可执行：说明改动内容、实际运行过的构建/测试命令及真实结果、是否涉及真实相机连接与操作、当前未验证项与下一步建议；严格区分「离线验证通过」与「实机验证通过」。
````

</details>

---

## 参考项目、滤镜来源与许可

### 1. 主要参考项目

本工程的固件功能、容器工具、色彩训练及维护脚本参考或整合了以下开源与逆向研究项目：

| 参考项目                                                     | 对应模块与参考内容                                           |
| ------------------------------------------------------------ | ------------------------------------------------------------ |
| [`Hearts-Ace/sony-a7r5-custom-firmware`](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware) | A7R V 4.00 原生色彩参数、24 槽网格生命周期、FL2/FL3 色彩整合、镜头 AF 能力过滤，以及自定义照片纵横比（AP/CP/`AV-CAM.BIN`/`libmpr.so`）核心参考 |
| [`Hearts-Ace/sony-r5-colorlab`](https://github.com/Hearts-Ace/sony-r5-colorlab) | `R5ColorLab` 色彩训练工作台、`R5GridCalibrator` 网格标定、24 槽 `R5NATIVE.BIN` 打包与公开滤镜预设库（本仓库额外集成 Apple Silicon Metal/MPS 训练适配） |
| [`Erlla/sony-a7m4-custom-firmware`](https://github.com/Erlla/sony-a7m4-custom-firmware) | 自定义纵横比 CP 侧逐张任务锁存、HEIF/JPEG 裁切边界与部分相机维护工具思路参考 |
| [`QAQLeonard/a7c2-fl23-research`](https://github.com/QAQLeonard/a7c2-fl23-research) | FL2 / FL3 创意外观移植与默认六档参数研究（[`materials/upstream-default-six/`](a7r5-firmware-features/materials/NOTICE.txt)） |
| [`DavidBuchanan314/ILCE-7M4-RE`](https://github.com/DavidBuchanan314/ILCE-7M4-RE) · [`ma1co/Sony-PMCA-RE`](https://github.com/ma1co/Sony-PMCA-RE) · [`chocotan/a7c2-re`](https://github.com/chocotan/a7c2-re) | Sony 固件容器解包、USB/Fastboot 引导及服务通道协议研究       |
| 其他开源依赖                                                 | Tauri、libusb 等基础组件（详见各子目录清单与许可证文件）     |

### 2. 滤镜来源说明

- **随 4.31 更新包默认输出的 `R5NATIVE.BIN`（58,976 字节，24 槽精选）**：存放于 [`a7r5-firmware-features/native24-combined/release431/filters/`](a7r5-firmware-features/native24-combined/release431/filters/export_audit.json)（SHA-256：`c8777b689e9c37506abbee49a5dc3964d0000e37b27ef033625122eaf5b77e4f`），由 [`sony-r5-colorlab/filters/`](sony-r5-colorlab/filters/README.md) 中的 24 款单款滤镜按 `format_version=5` 打包而成，覆盖富士（`RA`、`CC`、`NC`、`AS`、`PRO400H`、`NN`、`ET`、`VN`）、徕卡（`LM9S`、`LLCHR`、`LLTEA`、`LL100M`）、尼康（`NRTP`、`NDRE`、`NDEN`）、柯达（`P400`、`Gold200`、`PORTRA800`、`500T`、`E100`）与理光（`RRETRO`、`RP`、`RN`、`RCIN-G`）。
- **底层 4.28 基线默认滤镜包**：若单独使用 `./scripts/build_428_from_400.sh` 构建 4.28 基线，仍默认附带 [`FUJ_12_v45/R5NATIVE.BIN`](a7r5-firmware-features/native24-combined/dependencies/native12-combined/upstream/filters/FUJ_12_v45/R5NATIVE.BIN)（29,552 字节，源自 `Hearts-Ace` 公开的富士常用 12 款正式参数包）。
- **多品牌单款滤镜库与自训练工作台**：完整单款 `.bin` / `.json` 预设收录于 [`sony-r5-colorlab/filters/`](sony-r5-colorlab/filters/README.md)（源自 [`Hearts-Ace/sony-r5-colorlab`](https://github.com/Hearts-Ace/sony-r5-colorlab) 与 [`Hearts-Ace/sony-a7r5-custom-firmware`](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware) 公开滤镜库），可通过 [`sony-r5-colorlab/`](sony-r5-colorlab/README.md) 自由选配 24 槽打包导出 `R5NATIVE.BIN`，或基于 Apple Silicon MPS 自行训练新滤镜。

### 3. 许可声明

- 本仓库原创代码、文档与整合实现**仅限个人非商业研究使用，禁止商用**。
- 上游参考与第三方代码、工具及滤镜预设继续遵循其原有许可证（如 `R5ColorLab` 与 `R5GridCalibrator` 使用 GNU AGPL v3 等），详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 与各模块许可文件。
