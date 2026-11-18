# A7R5 原厂 4.00 基底的 24 槽自定义滤镜

本包使用 ILCE-7RM5 原厂 4.00 作为唯一 DAT 输入，移植 4.17 整合版的 24 槽运行时。包头版本采用 4.19，用于区分已发布的 4.17 整合包和 4.18 故障对照包。

| 能力 | 行为 |
| --- | --- |
| 冷启动导入 | 从 SD 卡根目录读取 R5NATIVE.BIN，兼容 v4 十二槽和 v5 二十四槽。双卡优先卡槽 1，首选卡无有效文件时尝试另一张。相同库跳过重写，缺卡、空文件或读取失败时使用已提交的机内库。暖恢复沿用机内状态。 |
| 创意外观切组 | 左键按当前横竖方向在原厂组和自定义组间切换，优先预览目标组上次应用成功的外观，失效时取第一项可用外观。空槽不可应用，空库保持原厂外观。两组各自记忆在本次开机内有效。 |
| 预览、确认与恢复 | 预览成功后自动保存，开机恢复最后一次成功选择。配方库变更后校验选择身份。快拨只保留最后待处理目标，原生空闲事件推进事务与重绘，失败在后台回退。 |
| 八项调参 | 右键进入，中键确认返回。对比度、高光、阴影、饱和度、褪色、锐度、精细度、清晰度显示相对原生值的偏移，初始与重置均显示 0。偏移按配方色彩身份保存，改名、换槽或重新导入同一配方仍有效，原始 BIN 保留。 |

独立包保留原厂 4.00 的其余功能行为和地区色彩／白平衡模板。包内只有三个分区及对应校验表变化。

| 分区 | 变更 |
| --- | --- |
| nflasha15 | /lib/appFw.so 和 /share/app/image_00_{23,32}_IPSX.uxc |
| nflasha8 | FAT 内的 /cpapp-b.bin |
| nflasha5 | 保留原厂快照，只把 WBI 头标记由 `WBI2` 改为 `WBI3`（偏移 `0x3` 的 1 字节），重算校验和 |
| part_image.sum | 重新生成上述分区的 CRC 行 |

`WBI2`／`WBI3` 是首扇区头标记。原厂更新器先清理快照头，随后写回包内分区，最后按清单校验。正确策略是保留原厂快照、只把标记 2→3，让包内镜像写回有效的 `WBI3` 头；改标记后镜像 CRC32 由 `0ff04cda` 变为 `76ce0feb`，需重算 `part_image.sum`。此前本独立包采用的“首扇区保持清理态”已废弃（2026-11-16）：清零后包内与设备都不再带有效头标记。注意该 profile 的脚本目前仍走零清分支，重新出包前需先同步代码。更新器、内核及 AVCAM 与原厂 4.00 字节相同。此处理仍需实机启动验收。 [写入顺序及历史故障分析](../../../native24-combined/4.18启动故障离线分析.md)

## 从锁定资源复现升级包

完成[公共准备](../../README.md#公共准备)后，在仓库根目录执行。

~~~sh
"$python" -B "$tool" native24-stock --base "$stock" --output "$out/native24-stock"
~~~

输出目录包含 BODYDATA.DAT、R5NATIVE.BIN、研究公钥和验证回执。随包 BIN 为十二款正式配方，属于 v4。二十四槽容量与空槽行为使用独立 v5 夹具验证。正式配方与升级包是两个文件，R5FILTER.BIN 是固件生成的机内选择记录。 [配套配方](R5NATIVE.BIN) · [归档及最终 DAT 摘要](resources.json) · [组件摘要](components.json)

## 从源码实施和封包

1. 解包原厂 DAT，校验 manifest.json、AP、CP 和分区摘要。运行时从冻结的十二槽代码派生，保留 24 槽布局、AP／CP 配对协议和现有稳定性逻辑。`--stock` 选择原厂输入并跳过整合版的本地 AP／CP 补丁。 [构建入口](../../../native24-combined/build.py) · [派生入口](../../../native24-combined/derive.py) · [24 槽布局](../../../native24-combined/layout.json)
2. AP 在原厂创意外观枚举、预览、确认和调参处接入运行时。原厂可见性和原有选择器保留，独立滤镜菜单和 Fn 项不注册。原生空闲事件调用后台选择服务和界面刷新，CP 确认、E4 更新与机内事务按序提交。 [菜单逻辑](../../../native24-combined/runtime/unified-look.c) · [选择服务](../../../native24-combined/runtime/r5_filter_runtime423.c)
3. CP 以原厂 Gamma 指针表 0x110cfa8、普通路由 0xdcc514 和外观路由 0xdcc67c 为基准。保留原厂 47 行，堆内保留 4 个空位，使自定义仍占 51～74。各槽的 CC1、矩阵、129 点 Gamma 和色度网格沿用配方解析。自定义释放后恢复原厂路由，同时为仍在处理的旧 ID 提供原厂曲线。原厂启动映射器继续执行，另映射运行时代码所在两页。 [原厂适配](../../../native24-combined/stock400.py) · [CP 对照测试](../../../native24-combined/tests/test_stock400.py)
4. 冷启动读取并校验库，机内以同目录临时文件发布。选择记录与配方库绑定，微调以 CC1、矩阵、Gamma 和网格的身份绑定。调参只在原生 E4 消息上应用有符号偏移，再限幅到原厂范围。 [冷启动读取](../../../native24-combined/runtime/r5_stage413_thread.c) · [事务保存](../../../native24-combined/runtime/r5_stable_io425.c) · [参数实施](../../../native24-combined/相对偏移调参说明.md)
5. 生成两份图标资源，沿用原厂 4 KiB 分块边界。将 AP 和图标写入原 ext2 文件，CP 写入原 FAT 文件，独立回读 WBI 范围。三个新分区生成后只写入新解包工作区，由 DAT 工具重算分区校验表。 [分区准备脚本](prepare.py)

在公共准备得到的全新 `out` 中执行以下命令。根目录 `.venv` 负责 ARM／AArch64 编译与回放，DAT 环境负责解包、封包和验签。编译使用仓库现有 clang／LLVM／lld 路径，ext2 检查使用 Homebrew 的 e2fsck。 [编译依赖](../../../native24-combined/实施与复现手册.md)

~~~sh
native="$PWD/a7r5-firmware-features/native24-combined"
profile="$PWD/a7r5-firmware-features/independent/profiles/native24-stock"
dat="$PWD/a7r5-dat-tool/dattool.py"
key="$PWD/a7r5-dat-tool/keys/sony-original-public.pem"
export PYTHONDONTWRITEBYTECODE=1

"$python" -B "$dat" unpack "$stock" --public-key "$key" --output "$out/stock"
.venv/bin/python -B "$native/build.py" --stock "$out/stock" --output "$out/runtime"
"$python" -B "$profile/prepare.py" --stock-workspace "$out/stock" \
  --runtime "$out/runtime" --output "$out/partitions"

# 在为本次构建新建的原厂解包副本中组装三个分区。
for part in nflasha15 nflasha5 nflasha8; do
  cp "$out/partitions/$part" "$out/stock/archive/0700_part_image/dev/$part"
done
"$python" -B "$dat" pack "$out/stock" --output "$out/from-source.DAT" --version 4.19
"$python" -B "$tool" native24-stock --base "$stock" --output "$out/native24-stock"
cmp "$out/from-source.DAT" "$out/native24-stock/BODYDATA.DAT"
~~~

## 离线验收

定向用例使用当前 AP／CP 机器码，文件、消息、界面及原生 E4 服务由夹具提供。

~~~sh
PYTHONPATH="$PWD/a7r5-dat-tool" "$python" -B - "$out" <<'PY'
import hashlib
from pathlib import Path
import sys
from a7r5dat.ext2_patch import reader

out = Path(sys.argv[1])
fs = reader((out / 'stock/archive/0700_part_image/dev/nflasha15').read_bytes())
raw = fs.read_inode(fs.walk('/lib/libstdc++.so.6.0.22'))
assert hashlib.sha256(raw).hexdigest() == '28f2d082aea5206c42ba15664f39e2eaf7febed8f6264305e7e16aa44c878389'
(out / 'libstdc++.so.6.0.22').write_bytes(raw)
PY
A7R5_NATIVE12_STD="$out/libstdc++.so.6.0.22" \
A7R5_NATIVE24_BUILD="$out/runtime" A7R5_NATIVE24_EVIDENCE="$out/cpu-evidence" \
  .venv/bin/python -B -m pytest -q "$native/tests" \
  --ignore="$native/tests/test_legacy_six.py" \
  --ignore="$native/tests/test_lens_af.py" \
  -k 'not test_qemu_page_gate_rejects_both_released_long_blocks and not test_baseline_rejects_new_capability_before_allocating and not test_current_components_preserve_local_patches'
~~~

应核对冷启动双卡与缺卡、24 槽逐项应用、横竖屏切组、最后成功项恢复、连续拨动、自动刷新和失败回退、八项偏移及重启后恢复。分区验收包括 ext2 一致性、FAT 无关字节和 WBI 首扇区外字节、研究签名、逐帧解密和全成员回读。回放覆盖应用与参数数据链，机身升级准入、完整启动、实体卡 I/O 和 EVF／JPEG／HEIF 的画面结果仍待实机验收。

本次 119 项运行时用例及 9 项封包相关回归通过。源码构建与归档增量复现所得 DAT 逐字节一致，独立解包覆盖 736,841 帧和 147 个归档成员，OpenSSL 研究签名校验通过。USR 核对了 1,043 个路径，三个目标文件之外的文件内容和映射一致。 [运行时回执](runtime-verification.json) · [封包回执](verification.json)
