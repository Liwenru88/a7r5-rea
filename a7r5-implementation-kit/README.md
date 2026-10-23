# A7R5 4.00 固件转存与 root shell 实施材料：第二版

> GitHub 源码发布说明：当前研究签名公私钥经授权随源码保留；完整固件、其他私钥、SDK 二进制、真实操作包和历史验证现场仅留本地；旧链接可能指向未入库材料。环境与输入要求以 [根目录构建说明](../docs/build-inputs.md) 为准，本轮验证见 [验证记录](../docs/verification.md)。

本包把当前研究整理成两条可审查、可重复准备的实施流程。适用于本人的 Sony ILCE-7RM5 / A7R5、固件 4.00，以及此前使用的 Apple Silicon Mac。**“已验证执行链”不等于所有新增入口都已实机通过，也不能保证零风险或整机可刷回。**

本轮只准备文档、源码、载荷和离线测试，没有连接相机、读取原始 SD 卡、写相机、认证、START、DEBUG、STOP、格式化或修复文件系统。

## 从哪里开始

| 目标 | 实施文档 | 默认产物 |
|---|---|---|
| 转存相机内部固件 | [01_A7R5固件转存实施.md](01_A7R5固件转存实施.md) | 默认19项约1.87GB，显式扩展模式37项约5.69GB；两者均不制作整张SD分区副本 |
| 在相机内以 root 执行自己的 shell 脚本 | [02_A7R5_ROOT_SHELL实施.md](02_A7R5_ROOT_SHELL实施.md) | 一次固定脚本的输出、退出码、UID/EUID、部署和恢复记录 |

**已有固件无需再转存。** 此前 37 个镜像已经在 Mac 验收通过；如果目的只是分析固件，直接使用原有 `verified/images/` 即可。本包不重复装入这些约 5.69GB 的个人镜像。

本版默认 `prepare-dump --profile standard`：17个 `cnflasha*` 明文分区加2个 `nflashaB*` 启动区，合计 **1,872,691,200 字节（1.873GB / 1.744GiB）**，与a7c2-re选择口径一致。只有明确使用 `--profile extended` 才包含额外17个物理分区和1个整个闪存视图。模式绑定于载荷、主机盘点、批准和取回清单，不能运行时切换。

当前本机37项原件已重新校验并增加分类链接，详见 `verification/local-classification-result.json`：标准19项与额外物理18项分开浏览，原件没有移动或删除，没有增加一套镜像数据。

## 证据等级

| 内容 | 当前证据 |
|---|---|
| Mac/libusb 两阶段认证、服务文件读写、预加载与一次 DEBUG 执行链 | A7R5 实机已验证 |
| 历史相机端转存：mmcb2、37视图、DONE 0、卸载和中和 | A7R5实机已验证；历史成功构建保留在 `historical/` |
| 第二版标准19项/显式扩展37项模式 | C选源、主机模式绑定、真实ext2夹具及载荷构建离线通过；**新模式载荷尚未实机复验** |
| 本机 37 个镜像长度、MD5、SHA-256 及 COMPLETE 验收 | 历史真实产物已验证，记录随包保存 |
| 本包新一次性 root 脚本执行器 | 本机同源 C 进程测试、协议测试、AArch64 构建与 ABI 检查通过；**新入口尚未实机验证** |
| 本包不复制SD分区的按文件取回入口 | 标准19项和扩展37项均在普通ext2文件夹具通过；**原始读卡器路径尚未实机验证** |
| 交互式终端、SSH、开机持续 root、隐藏区全覆盖、刷回 | 未实现或未验证 |

第二版45项相关回归通过。历史311项及第一版35项只作为对应旧版本证据，不冒充第二版实机证明。包内没有有效实机批准；旧版本材料和锁保留。

## 包里有什么

```text
kit.py                         统一入口；默认没有连接设备动作
tools/                         一次性准备、批准、执行及精简取回逻辑
payload/root_once.c            新 root 执行器源码
examples/root-info.sh           固定只读 shell 示例
examples/prepared-root/         示例载荷、配置、脚本、目标文件字节；无批准
examples/prepared-dump-standard/ 默认19项构建示例；无批准
examples/prepared-dump-extended/ 显式37项构建示例；无批准
engine/mac/                    从成功版本适配的双模式引擎；认证和恢复门槛沿用
engine/libs/                   已有 PyUSB、Cryptodome、ELF 解析依赖
engine/sources/                PMCA 认证源码和目标 libc 构建样本
profiles/                      指定备用卡收据和固定版本对照
historical/                    成功构建、实机/本机验收记录、37 项清单、参考源码
tools/classify.py              本机37原件校验及19+18分类链接入口
tests/                         两模式、失败路径、分类及root回归
verification/                  来源、依赖、测试与交付检查记录
MANIFEST.sha256                本包所有文件的 SHA-256
```

`historical/` 内的载荷和令牌属于历史会话，只供复核；不能重跑历史会话或复用它们的 run_id。`engine/` 内旧研究入口是封存源码，实施统一从 `kit.py` 开始。不要直接调用其旧格式化、通用部署或旧恢复入口。

第一版仍默认37项，保留作历史。本次实施使用本第二版；不使用旧包的批准或删除旧锁来重跑。源码改动范围和旧版对照见 `verification/v2-verification.json`。

`examples/prepared-*` 用于看清全部中间材料，不提供现成批准。搬动/解压材料包后，必须用 `prepare-*` 在最终位置生成自己的新操作；旧操作绑定原材料绝对路径。

## 依赖与离线检查

材料包携带 Python 通信/解析依赖及目标 libc，**不携带整个 Python、macOS 工具链或 Homebrew 安装树**。当前 Mac 已具有：

| 项目 | 当前实现使用的位置 |
|---|---|
| Python | `../.venv/bin/python` |
| clang | `/usr/bin/clang` |
| AArch64 ELF 链接器 | `/opt/homebrew/opt/lld/bin/ld.lld` |
| libusb | `/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib` |
| e2fsprogs | `/opt/homebrew/opt/e2fsprogs/sbin/`，精简取回使用 `debugfs` |
| 测试环境 | 原工程 `.venv` 中的 pytest；版本见 `requirements.txt` |

外部文件的实际路径和摘要见 `verification/dependencies.json`。本轮没有安装新依赖。换电脑、升级工具或更换读卡器不属于已经验证的环境；缺依赖应先离线解决，不可跳过校验直接连机。运行操作时会核对 Python、libusb、debugfs 和所有实施源码摘要。

在最终解压目录执行以下命令，只核对文件和入口帮助：

```bash
cd "/最终解压位置/a7r5-implementation-kit-20261018-v2"
/usr/bin/shasum -a 256 -c MANIFEST.sha256
TASK_PY="../.venv/bin/python"
"$TASK_PY" -B kit.py --help
```

不要用 sudo 执行 `prepare-*`、`check` 或 `approve`。只有分别审阅并确认具体实机操作后，才在本机 Terminal 中使用 sudo 执行 `execute`。密码只在本机 Terminal 输入。

## 当前能力边界

本机成功产物覆盖此次发现并识别的 37 个闪存视图，包含物理/明文以及整设备/分区重叠；不是 37 块独立物理闪存，也不是已经证明覆盖隐藏区、OTP 或同时点一致快照的刷回包。

此前相机最初未知的预加载原字节没有恢复；已做到的是精确 512 个换行的中和。研究文件残留、独立工作进程退出和拍摄功能没有完整验收。本包保留这些限制，不以普通 USB 和正常屏幕代替相机完全恢复原样的证明。
