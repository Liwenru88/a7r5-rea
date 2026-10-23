# 本地构建输入与重建

发布仓库保存算法、配方、源码、固定输入摘要及经持有人授权公开的当前研究签名公私钥。固件、SDK 等材料继续留在原位置，由 Git 忽略；没有把原件迁移或替换为软链接，也不自动下载固件或生成新的签名身份。下表同时列出随源码提供的签名身份和需要自行准备的本地输入。

## Python 与开发工具

在工程根目录执行 `sh scripts/bootstrap.sh`，准备根 `.venv` 和 `a7r5-dat-tool/.venv`。脚本使用 Python 3.14 和 uv，版本固定在 `requirements-dev.txt` 与 DAT 工具的锁定清单。安装过程需要联网获取依赖，不操作硬件。本次验证复用现存开发环境；另在工程外建立新的环境验证源码测试。

客户端开发还需要 Rust、Xcode Command Line Tools，以及 Apple Silicon 常见安装位置 `/opt/homebrew/opt/llvm/bin/clang` 和 `/opt/homebrew/opt/lld/bin/ld.lld`。其他位置需要调整现有构建脚本；运行已封装应用不需要这些工具。

## 客户端

先运行只读输入检查：

```sh
.venv/bin/python -B scripts/check_local_inputs.py --module desktop
```

| 输入 | 放置位置 | 要求 |
|---|---|---|
| 指定官方 4.00 DAT | `a7r5-firmware-images/官方升级包/BODYDATA.DAT` | 754525608 字节，SHA-256 `51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2` |
| 完整逻辑分区前像 | `a7r5-firmware-images/标准固件_19项/明文分区_17项/cnflasha1.img` | 25100288 字节，SHA-256 `acf32d30dd883ed349738e66fb081e85e0d6a3c746f5e3ca169031e8d69ed731` |
| 原厂 AArch64 libc | `a7r5-exec/sdk/libc-2.25.so` | 固定摘要见 `scripts/local-inputs.json`；来自已核验的本地材料 |
| 固定 SFTP 服务程序 | `a7r5-ssh/ssh-service/original-view/vendor/sftp-server.arm64` | 从下面的固定 Debian 依赖包按摘要提取；不会由 Git 携带 |
| 当前研究签名私钥 | `a7r5-dat-tool/keys/research-signing-private.pem` | 已授权随源码提供；克隆后设为 0600，必须与研究公钥配对；安装依赖脚本不会生成新身份 |
| 研究和原厂验签公钥 | `a7r5-dat-tool/keys/research-public.pem`、`sony-original-public.pem` | 公钥随源码保留；信任模块还保留 `public-key.pem` |

私钥缺失时，源码测试和 DAT 验签仍可使用，真实研究签名封包不能完成。不能生成任意新密钥后继续沿用旧公钥或旧信任修改规则；更换身份属于独立适配工作。

`check_local_inputs.py` 检查主要文件是否存在、是否为链接、固定摘要和私钥权限；它不替代完整构建检查、签名配对检查或设备验收。

SFTP 的固定包地址、包与二进制摘要保存在 `a7r5-ssh/ssh-service/original-view/vendor/sftp-provenance.json`。自行获取对应 `openssh-sftp-server_7.4p1-10+deb9u7_arm64.deb` 后执行：

```sh
.venv/bin/python -B scripts/prepare_sftp.py /absolute/path/to/openssh-sftp-server_7.4p1-10+deb9u7_arm64.deb
```

脚本只读取本地包并提取指定普通文件，不执行安装脚本、不调用 sudo、不联网、不覆盖已有输出；包与文件摘要不符均停止。现有出处记录未宣称验证 Debian 发行签名或本地重建源码，这一边界保持不变。

准备输入后，按 [客户端构建说明](../a7r5-desktop/README.md) 执行 `build_usb.py → prepare.py all → notices.py → prepare.py seal → cargo build → package.py`。客户端会从项目内现存模块源码和冻结依赖生成运行材料；这些源码快照需要保持完整。`prepared/engine/` 和 `dist/` 都不入库。

当前最终本地包仍按已确认范围仅用于本地测试，不在本次 GitHub 发布范围内。不要对已签名 `.app` 递归删除缓存或修改资源；资源变更会影响摘要和签名。

## 旧执行与研究入口

`a7r5-exec` 使用本地 `TOOL.json` 绑定源码、SDK 和依赖摘要；源码发布不带开发机的材料封印。`a7r5-libjit` 的固定加载库位于忽略的 `packages/libjit-info-20261021-02/test-fixtures/libJiritsu.so`，摘要见输入清单；部分构建和中断恢复测试还使用原历史包的配置、协议回执和版本文件。

这些真实包、`ACTIVE_SERVICE.json`、`ACTIVE_SESSION.lock`、`ATTEMPT_LOCK*` 和存储卡身份资料保留在本地。它们不是可供新用户直接复用的配置。发布源码允许阅读与独立协议开发；需要这些入口时，须使用自己的精确输入，重新完成模块规定的准备、验证与批准，不能复制他人的批准或删锁放行。缺失本地材料时的停止是预期行为。

## 可选 QEMU

客户端不依赖本模块。QEMU 运行必须满足 `a7r5-qemu/runtime/manifest.json` 中全部文件的长度与摘要：

```sh
.venv/bin/python -B scripts/check_local_inputs.py --module qemu
```

本次整理前就已缺失 `runtime/menu-a95b001d61b77b98.cpio` 和 `runtime/virt-5aff1e79858f7eef.dtb`，本次没有恢复它们，没有改写清单或绕过校验。因此当前工程和公开源码副本均不能宣称 QEMU 菜单可直接启动。

`source/qemu/vendor/qemu-11.1.2.tar.xz` 为本地保留的固定构建输入，不进入 Git；使用自己有权使用、且与 `source/qemu/manifest.json` 的版本和摘要一致的源码归档。补丁、dtc 源码和许可证随仓库保留。客体内核、初始化归档、DTB、SDK 库同样由使用者提供。

Qt 开发环境可单独创建：

```sh
uv venv --python python3.14 a7r5-qemu/.venv
uv pip install --python a7r5-qemu/.venv/bin/python -r a7r5-qemu/requirements.txt -r a7r5-qemu/requirements-desktop.txt
```

材料不全时不要执行启动或客体重建入口。创意外观参考工具还引用本地研究工作副本；历史参数或截图不能替代缺失的真实客体输入。
