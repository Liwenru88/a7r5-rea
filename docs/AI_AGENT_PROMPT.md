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
   ```sh
   ./scripts/build_428_from_400.sh /path/to/4.00/BODYDATA.DAT -o /new/output/dir
   ```
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
   - **一键更新信任环境**：`.venv/bin/python -B scripts/trust_update/update_trust.py --engine libjit`（或双击 `scripts/trust_update/一键更新信任环境.command`；默认支持动态 `ioreg` 端口识别、`0336` 预恢复、258 扇区写入与全量回读、`STOP` 恢复普通 MSC）
   - **一键启动 SSH**：`.venv/bin/python -B scripts/ssh_start/start_ssh.py --engine libjit --ttl 0`（或双击 `scripts/ssh_start/一键启动SSH.command`；如相机已有运行中的 SSH 服务会安全超时保留现有会话，不会发送 `STOP`）
   - **RAM Fastboot 快速脚本**（仅在救砖/诊断并获得明确授权时）：`a7r5-fastboot/1_enter_fastboot.sh`、`2_activate_usb.sh`、`3_trigger_sd_update.sh`
10. 协议失步、短读/短写、摘要不符、写后验证失败或状态未知时，立即停止后续自动动作并保存 `.local/` 日志现场；不要重试写入、删锁或伪造成功。
11. 存储卡升级流程：将构建好的 `BODYDATA.DAT` 复制到已格式化的 SD 卡**根目录**（精确文件名，不要放入 `DCIM`），插回相机 **SLOT1**，在充足供电下通过 `MENU → 设置 → 设置选项 → 版本 → 软件更新` 执行。升级完成后再将 `R5NATIVE.BIN` 放入 SD 卡按 `look24` 说明冷启动导入。

四、交付格式
最终必须提供：源码提交身份与改动摘要；输入与产物 SHA-256；实际执行的构建/测试命令及退出码；是否连接过相机或执行设备操作；下一步操作建议与未验证边界。必须严格区分「已实现」「离线验证通过」「项目历史实机验证（4.28 稳定主线）」「本轮实机操作（待执行/已完成）」，不得把离线通过或历史实机记录等同于本轮新改动已实机验收。
