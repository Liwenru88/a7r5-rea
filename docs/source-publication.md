# GitHub 源码发布与资源恢复

本轮整理发布候选集，不改变固件算法、签名身份或已有升级包。机器现场、生成的模板和用户目录路径不随源码发布；本地原件保留。`scripts/release_check.py` 的凭据、二进制和单文件 10 MiB 门槛保持不变。

## 新检出源码后的准备

先按根 README 准备 Python 环境，再在仓库根目录执行：

```sh
# 还原缺失的资源。只有显式 --download 才会访问固定上游地址。
.venv/bin/python -B scripts/prepare_source_assets.py restore --download
.venv/bin/python -B scripts/prepare_source_assets.py check
```

恢复脚本仅使用 Python 标准库，不需要管理员权限、Sony 固件或相机。它不自动安装依赖、不调用 USB、SSH 或卡写入工具。已有资源若摘要一致则跳过；若不同则停止，保留用户文件。

资源清单位于 [source-assets.json](../scripts/source-assets.json)，共十二项：

| 资源 | 源码分发方式 | 恢复与身份 |
|---|---|---|
| 四个超过 10 MiB 的独立包压缩增量 | `source-assets/chunks/` 内不超过 8 MiB 的分片 | 合并压缩流，核对分片及完整文件的长度和 SHA-256；原压缩文件、独立包清单和最终包摘要保持不变 |
| 三份冻结响应模型 JSON | 固定上游地址及摘要清单 | 从 Color Lab 提交 `fb464bdef54cae7b56092bd35d35dc3542793ff3` 恢复；不改写模型里的历史元数据，保留既有模型身份和旧工程兼容所需摘要 |
| 四份压缩合成色卡和一份标定报告 | 同一固定上游提交及摘要清单 | 用于训练、标定及复现；不包含用户实拍照片。完整资源留在本地，源站资源不可用时应提供摘要一致的已有副本 |

无网络时，可使用已有原件放回清单指定路径，再执行 `check`。四份分片增量无需联网即可恢复。恢复后再进行桌面客户端准备、独立包复现或 Color Lab 训练；普通模块化固件构建仍须另行提供适配的官方 DAT、工具链及相关 SDK。

恢复采用同卷临时文件、完整校验和独占发布，失败不会发布半个目标文件，也不会覆盖不同的已有文件。下载仅允许 HTTPS 的 `raw.githubusercontent.com` 固定 40 位 Git 提交路径，下载后再核对完整长度和摘要。

### 2026-11-12 固件冻结树补齐

完整快照检查还要求五项工作台材料及原 `.gitignore`。本轮按原清单恢复后，正常构建新的 4.19 包通过。Git 已跟踪文件对照又发现七项同类易漏输入，统一登记在 [snapshot-repair.json](../a7r5-firmware-features/materials/snapshot-repair.json)，共十三项。该文件只包含固定上游 URL、长度和摘要，没有嵌入口令哈希、配方或模板二进制。

```sh
# 默认不联网；已完整的树只核对并跳过。
.venv/bin/python -B a7r5-firmware-features/materials/restore_snapshot.py
# 新检出时显式允许恢复；另可使用 --source-dir 从精确本地副本离线恢复。
.venv/bin/python -B a7r5-firmware-features/materials/restore_snapshot.py --apply --download
```

快照清单和原检查器没有修改。未知二进制拒绝覆盖；仅根 `.gitignore` 可以显式加 `--restore-gitignore --backup NEW_DIRECTORY` 先备份再恢复。恢复出的模板仍为本地构建材料，不自动暂存或提交；现有二进制／固定口令哈希发布检查保持。源码检出并不代表已经拥有官方 DAT、LLVM、SDK 或设备授权。

## 109 项问题的处理

- **86 项用户绝对路径：** 机器生成的回执、日志和来源现场排除出源码候选；三个冻结模型按原摘要从固定上游恢复；十六份说明文档改用 `${PROJECT_ROOT}`／`${LOCAL_HOME}` 占位符。完整历史文档保留在本机私有归档。历史结论和摘要没有重写。
- **10 项超限文件：** 四个增量使用校验分片；五份上游资源使用固定版本恢复；机器清理快照保留本地。没有提高源码大小门槛或放行任意大文件。
- **4 项迁移旧路径：** 从 Git 索引登记旧文档删除，新模块目录中的实施文档继续保留；没有重新生成旧路径副本。
- **1 项固定口令哈希与 4 个 `.so` 模板的双重告警：** 生成的上游工作台模板清单和预编译模板取消跟踪、仅留本地。保留其模板构建源码和原许可证；本工程正式入口是 `a7r5-desktop`，冻结的 `R5FlashWorkbench` 不作为已准备好的独立应用发布。

四个 `.so` 各命中“本地产物”和“可执行二进制”两条规则，因此原来 109 条问题涉及 105 个文件。这里只修正发布候选，不将这些记录解释为固件功能故障。

## 研究脚本的显式输入

旧版 DAT 审计脚本 `final_verify.py` 与 `verify_candidate.py` 新增必填 `--source-dat`；历史 DAT 的原固定 SHA-256 检查保持，不能传任意同名文件通过。

Color Lab 历史色卡／R6 研究脚本用以下环境变量代替作者电脑的目录：

| 变量 | 输入 |
|---|---|
| `R5_RAW_SOURCE` | 本次固定前像要求的 Sony RAW，脚本原有摘要检查保留 |
| `R5_RAW_PARSER` | `build_synthetic_arw.py` 使用的外部 RAW 解析器源码 |
| `R5_IED_SOURCE` | RAF／ARW 生成研究使用的 IED 源码目录 |
| `R5_R6_RAW` | R6 对照 RAW |
| `R5_RAW_REPORT` | R6 研究所需的既有 RAW 对照报告 |

这些外部原件和工具需由使用者准备。缺少输入时应停止，不把历史脚本当作已具备所有素材的主训练入口；当前训练流程见 [TRAINING.md](../sony-r5-colorlab/R5ColorLab/TRAINING.md)。

## 提交边界与验证

本轮为使实际 Git 候选正确排除本地产物，对明确清单执行了取消跟踪。**Git 暂存区中会出现对应删除项，磁盘文件仍保留；没有将其他功能改动自动暂存，也没有提交或推送。** 提交前需一并审阅 `.gitignore`、恢复脚本／清单、分片、修改后的源码和新增模块文件。

```sh
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B scripts/release_check.py
```

发布检查继续检查被强制跟踪的忽略文件、未授权私钥、固定口令哈希、伪装二进制、未知大文件及机器目录。它检查当前源码候选集，不清除已有 Git 历史，也不替代完整秘密扫描或实机验收。

本机私有备份位于 `docs/private-publication/20261111/`，包含整改前的索引、文件摘要、原始文档和逐项记录；该目录不进入 Git。原有 `.local`、设备日志和升级包不因本轮发布整理而重建或修改。
