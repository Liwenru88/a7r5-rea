# A7R5 独立功能实施与复现

每项使用一份独立实施文档和一组锁定的归档增量。复现只需要指定基线 DAT、项目 DAT 工具、对应研究签名身份和本目录资源。增量源自已有实现或已经验证的组件组合，完整前像、目标、校验表和最终 DAT 摘要由各功能清单绑定。

## 功能目录

| 功能 | 构建输入 | 产物或边界 |
| --- | --- | --- |
| [FL2／FL3](profiles/fl2-fl3/README.md) | 原厂 4.00 | 单项启用和色彩路径 |
| [关闭指定 NTSC 提示](profiles/ntsc/README.md) | 原厂 4.00 | 单项 AP 提示控制 |
| [电子快门声音](profiles/electronic-shutter/README.md) | 原厂 4.00 | 单项 CP 声音模式 |
| [照片 2.35:1 构图标记](profiles/photo-markers/README.md) | 原厂 4.00 | 单项 AP 菜单、属性与标记路径 |
| [C1–C6 历史单项版](profiles/factory-six-stock/README.md) | 原厂 4.00 | 六款内置，使用历史照片链 |
| [R6 ST 参数模板](profiles/r6-st/README.md) | 原厂 4.00 | 十二地区通用模板，只改对应 ST 字段 |
| [AWB 优先参数模板](profiles/awb-priority/README.md) | 原厂 4.00 | 十二地区通用模板，只改白色／氛围字段 |
| [24 槽自定义滤镜独立版](profiles/native24-stock/README.md) | 原厂 4.00 | 4.19 单功能包，含冷启动导入、切组预览、八项调参与保存恢复 |
| [24 槽创意外观 4.17 整合版](profiles/native24/README.md) | 原厂 4.00 | 精确复现发布过的 4.17，供历史复现和其他模块构建 |
| [镜头 AF 能力过滤](profiles/lens-af/README.md) | 精确 4.17 | 相对基线只更新 CP 能力过滤 |
| [十档照片纵横比](profiles/photo-aspect/README.md) | 精确 4.17 | 相对基线加入取景范围和 JPEG／HEIF 裁切 |
| [C1–C6 当前链路版](profiles/factory-six-native24/README.md) | 本目录的十档比例候选 | 相对基线只加入六款，与 SD 的 24 槽并存 |
| [WBI 标记 2→3](profiles/wbi/README.md) | 指定旧 4.18 | 保留原厂快照，只把头标记由 `WBI2` 改为 `WBI3` 并重算校验和；旧的“首扇区清零”候选仅留作历史对照 |
| [旧 4.18 基线](profiles/baseline418/README.md) | 精确 4.17 | 历史启动故障对照，也是 WBI 修复的可重建输入 |

表中的构建输入是离线 DAT。构建顺序无需在相机上逐版安装。24 槽 4.17 包含同版的 FL2／FL3、NTSC、声音、照片标记及参数模板。4.19 独立版从原厂 AP／CP 构建，并单独记录包内 WBI 失效处理。旧独立滤镜菜单和 Fn 分配属于 [4.10／4.11 历史路线](../native24-combined/dependencies/native12-combined/README.md)。[32 槽与机内 CUBE](../custom-filters/README.md)属于另一研究路线。

## 公共准备

1. 在仓库根目录操作，使用 `a7r5-dat-tool/.venv/bin/python` 和支持 `pkeyutl` 的 OpenSSL。Python 环境依赖见 [DAT 工具依赖](../../a7r5-dat-tool/requirements.txt)。如需从源码重建组件，另按对应文档准备 ARM／AArch64 LLVM 工具链及根目录 `.venv`。
2. 原厂文件默认位于 `a7r5-firmware-images/官方升级包/BODYDATA.DAT`。精确 4.00 的 SHA-256 为 `51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2`，长度为 754,525,608 字节。已发布 4.17、4.18 的文件名相同，必须按各功能清单中的摘要区分。
3. 封包使用项目已有研究签名身份。对应研究公钥 SHA-256 为 `7f65b296987df665da217de514e785f75238e686ddd18952fa425fc47e8c858a`。将合法持有的配对密钥按 [DAT 工具说明](../../a7r5-dat-tool/README.md)配置。本目录资源只包含增量、校验和配方。生成的 DAT 使用研究签名。
4. 预留至少 10 GiB，准备新的工作目录。以下变量供各单项文档复用。每次重跑使用新的 `out`，程序会拒绝覆盖同名结果。

```sh
set -e
tool="$PWD/a7r5-firmware-features/independent/build.py"
python="$PWD/a7r5-dat-tool/.venv/bin/python"
stock="$PWD/a7r5-firmware-images/官方升级包/BODYDATA.DAT"
mkdir -p "$PWD/.local"
out=$(mktemp -d "$PWD/.local/a7r5-single.XXXXXX")
```

## 输出与验收

`build.py` 先验证输入 SHA-256 和签名，再校验每份增量的摘要与完整前像。归档增量采用已有的 4 KiB 索引块格式。DAT 工具按成员变化自动重建 `part_image.sum`、`backup.sum` 等对应记录。封包后逐帧解密，再由独立解包核对全部成员的顺序、长度、目标摘要和变化集合，并使用 OpenSSL 验签。只有校验通过才发布到指定的新目录。

输出为 `BODYDATA.DAT`、`verification.json`、研究公钥，以及声明过的配套配方。各目录下的 `resources.json` 锁定重建输入和期望变化，`verification.json` 记录本轮实际复现。部分候选沿用同样的头版本，完整 SHA-256 才是包身份。

历史整理生成了十二个功能候选和一个历史对照包，每个均完成 736,841 帧校验、独立解包与 OpenSSL 验签。对应候选另执行了十档裁切 19 项、六款与 24 槽共存 8 项、镜头 AF 1 项，以及 FL2／FL3 选择、NTSC 跳转、标记范围和声音选择各 1 项指令回放。4.19 的证据在其[独立实施文档](profiles/native24-stock/README.md#离线验收)记录。资源完整性可在本目录执行 `shasum -a 256 -c SHA256SUMS` 核对。

这些是升级包复现和离线验收记录。实际机身升级准入、冷启动、功能行为和成片结果按各项文档单独记录。旧 4.18 基线曾在实机更新后无法启动，WBI 单项修正尚无实机启动结论。 [故障分析](../native24-combined/4.18启动故障离线分析.md)
