# A7R5 DAT 本地打包与解包工具

> GitHub 源码发布说明：当前研究签名公私钥经授权随源码保留；完整固件、其他私钥、SDK 二进制、真实操作包和历史验证现场仅留本地；旧链接可能指向未入库材料。环境与输入要求以 [根目录构建说明](../docs/build-inputs.md) 为准，本轮验证见 [验证记录](../docs/verification.md)。

独立于原研究目录的命令行工具，支持当前 A7R5 4.00 派生格式。提供 DAT 查看、验签、解包、AP／CP／文字资源替换、分区校验更新、加密签名打包及独立解密回读。**没有 USB、SSH、写卡或刷写入口。**

**本目录与交付 ZIP 附带真实研究签名私钥。** 这是当前研究 DAT 的配对身份，不是索尼官方私钥。持有人已明确授权这一研究身份随 GitHub 源码提供，按公开身份使用；其他 SSH 私钥仍不公开。私钥位于 `keys/research-signing-private.pem`，权限为 `0600`；公钥位于同目录，另附原厂验签公钥。不会把私钥打印到终端或写入打包回执。

## 1. 运行准备

本机目录已创建专用 `.venv` 并安装依赖，可直接执行：

```sh
./dattool --help
```

从 ZIP 解压或迁移到另一台电脑后，进入工具目录执行：

```sh
chmod +x dattool 安装依赖.command
./安装依赖.command
```

安装入口只创建工具自己的 `.venv`，不改系统 Python。需要 Python 3.12 及以上；依赖下载可能需要联网。实际验收为 **macOS arm64 / Python 3.14**，没有完成 Windows、Linux 或其他 Python 版本验收。源码和 Python 入口没有依赖 macOS 专用 API。

也可以使用已安装依赖的解释器运行 `python dattool.py ...`，或通过环境变量 `A7R5_DAT_PYTHON` 为启动脚本指定解释器。ZIP 不携带机器相关的 `.venv` 或整套固件镜像；依赖固定在 `requirements-lock.txt`，开发测试依赖见 `requirements-dev.txt`。

## 2. 查看与完整验证

```sh
./dattool inspect /path/to/BODYDATA.DAT
./dattool verify /path/to/BODYDATA.DAT
```

- `inspect`：检查整个 DAT 的外层 CRC 和 RSA 签名，读取首段明文格式头，显示版本和摘要；**不验证全部解密帧**。
- `verify`：在上述基础上验证全部解密帧、头 CRC，并遍历归档计算成员摘要。此命令不展开文件，也不模拟相机更新器。
- 默认尝试附带的研究公钥和原厂公钥；其他研究身份需要显式传入 `--public-key /path/to/public.pem`。没有跳过签名检查的开关。
- `verify` 验证容器完整性，不验证全部归档 `.sum` 的业务一致性；`unpack` 核对原包全部可识别 `.sum`，`pack` 再更新其对应目标。

## 3. 解包

```sh
./dattool unpack /path/to/BODYDATA.DAT --output ./work
```

输出父目录必须已存在，`work` 必须是全新目录。解包空间门槛为 2 GiB。正常工作目录约 0.8 GiB，不会生成整张 SD 卡镜像，也不额外保留完整的解密 DAT／TAR 副本。

```text
work/
  manifest.json                       版本、摘要、布局和归档元数据
  archive/                            DAT 全部普通归档文件及原始分区镜像
  components/
    cpapp-b.bin                        可编辑的 CP
    usr/lib/appFw.so                   可编辑的 AP
    usr/share/app/string_*.uxc         可编辑的 68 份菜单文字资源
  format/
    header.bin                        格式头：不要手工修改
    updater.bin                       原更新器：工具要求保留原样
```

归档符号链接只保存在清单中，不在主机创建链接。解包失败会保留 `INCOMPLETE.json` 和现场，工具拒绝打包该目录；不自动重试、覆盖或删除现场。

## 4. 修改后打包

修改 `components/` 中的 AP、CP 或菜单资源，再执行：

```sh
./dattool pack ./work --output ./BODYDATA-custom.DAT --version 4.05
./dattool verify ./BODYDATA-custom.DAT
```

也可以直接替换 `archive/` 中已有的普通成员，但须保持成员长度。**同一分区的原始镜像和内部组件不能同时修改**，否则拒绝打包，避免静默覆盖。

打包行为：

1. 核对目录结构、输入文件和签名密钥配对；不允许链接、设备路径或额外归档文件。
2. 将变更组件合入临时分区。AP／CP 要求定长，UXC 可保持原长或小幅增长；保留 inode，按现有 ext2 工具能力分配空闲块，空间或映射不支持即停止。
3. 自动同步归档 `.sum` 中对应普通文件的 CRC32；拒绝手工改动校验清单。保持归档成员集合、长度和原始归档布局，保留更新器。
4. 使用附带研究私钥签名、加密，检查外层 CRC 和 RSA，再用另一密码实现解密所有输出帧，与待打包明文逐字节对照。
5. 核对工作目录在打包期间未变；验证通过后才发布最终 DAT，附带 `BODYDATA-custom.DAT.json` 回执。

输出 DAT 和回执必须均不存在。打包至少需要 3 GiB 空闲临时空间。工具不覆盖旧包，不静默增减归档文件，不接受原始磁盘路径，不自动绕过版本比较。

不传 `--version` 会保留输入版本。版本采用 `4.05` 形式，仅设置格式头并更新头 CRC，不表示加入某个官方版本的功能。该版本是否满足机身准入，需要另行核对。

### 指定另一套研究身份

```sh
./dattool pack ./work --output ./other.DAT \
  --private-key /path/to/private.pem \
  --public-key /path/to/public.pem
```

仅支持 RSA-2048，公私钥必须匹配。POSIX 系统要求私钥为 `0600`。更换签名身份不会自动部署机身信任环境；附带密钥不能代替索尼官方签名。

## 5. 能力边界

- 支持当前包及同格式的本地 A7R5 原厂 4.00 派生包，不承诺支持所有索尼机型、版本和归档格式。
- 提供 **DAT 容器与已有组件的编辑往返**；没有提供任意重建 ext2／FAT、增加新归档文件、调整分区大小或重建更新器的功能。
- 使用当前 DAT 解包会保留其已实现功能；使用原厂 DAT 解包不会自动加入 FL2／FL3、六款外观或声音补丁，需要用户放入已经构建的候选组件。
- 修改后校验通过证明输出与所给组件／归档一致，不证明组件程序逻辑、完整 CP 启动、相机升级接纳、拍摄效果或可恢复性。
- 本工具不安装更新器信任环境，不处理机身账户、SSH、自启或任何实机操作。
- `.sum` 有效不是升级安全证明；完整 DAT 的物理刷写范围由更新器决定，不是按不同字节数写入。

## 6. 验收与来源

本次实际验收记录放在 `evidence/`：包括当前 DAT 无修改往返、从原厂合入当前组件、20 项失败边界测试及可迁移源码检查。当前 DAT 无修改往返的 SHA-256 完全一致。从原厂合入当前 70 个组件并修改 WBI／版本后，全部 `/usr` 路径、inode 和普通文件内容一致，但镜像中的间接块指针、数据落点等有 600 字节差异，故 DAT 摘要不同；不声称这条路径逐字节还原历史产物。源码来自现有研究中已使用的容器读取器、加密器和定向 FAT／ext2 工具，冻结来源摘要见 `SOURCE_FILES.json`，许可证说明见 `licenses/`。

测试命令（先在所选虚拟环境中安装 `requirements-dev.txt`）：

```sh
python -B -m pytest -q tests -p no:cacheprovider
```

真实 DAT、解包工作目录和约 720 MiB 的回归输出保存在原工程 `analysis/dat-tool-validation-20261022-01/`，不装入工具 ZIP。ZIP 包内包含敏感私钥，但不包含个人相机 Backup、SSH 密码、原厂／研究固件二进制或 SD 卡镜像。

交付 ZIP **未加密**，POSIX 文件权限设为 `0600`。传给其他人即同时传出了研究签名能力；`.gitignore` 只是避免误提交，不是加密措施。
