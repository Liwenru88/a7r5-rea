# 03 A7R5关闭目标NTSC提示：实施细节

日期：2026-10-23。适用精确原厂4.00 AP或经审查的本项目派生前像。当前4.06保留两处分支修改。**它只跳过特定NTSC提示，不改变PAL／NTSC制式，不解锁制式或语言，也不跳过全部警告。**

## 1. 修改位置和原理

AP为`nflasha15`中的`/lib/appFw.so`，机身路径`/usr/lib/appFw.so`，AArch64小端。原厂长度97368304字节，SHA-256：`41bd8f4cda1f44c7038912837737e1ce6a650065f2108061ada30e5c7f9ce7c7`。

| 文件偏移／本窗口VA | 原指令字节 | 原指令 | 新目标 | 新指令字节 |
|---|---|---|---|---|
| `0x20c99a4` | `22 6f 80 52` | `mov w2,#0x379` | `0x20c99c0` | `07 00 00 14` |
| `0x20c9ea4` | `22 6f 80 52` | `mov w2,#0x379` | `0x20c9ecc` | `0a 00 00 14` |

原逻辑已经根据地区、制式、复位／启动状态等条件选到消息0x379；在这个选中点直接跳到原生后续分支，所以不会进入该提示提交路径。PAL提示0x381和其他条件分支保持。

AArch64无条件B的计算为：

```python
distance = target - at
assert distance % 4 == 0
assert -(1 << 27) <= distance < (1 << 27)
word = 0x14000000 | ((distance // 4) & 0x03ffffff)
new_bytes = struct.pack('<I', word)
```

注意AArch64这里使用当前指令地址作为PC，不套用Thumb跳转的`PC+4`。实际8字节窗口不代表八个字节都与前像不同；只统计不同字节没有4字节指令完整性意义。

## 2. 单独修改AP的最小代码

下例只允许原厂AP，输出新文件，不覆盖输入。**执行前必须先解包到普通文件，绝不能把`/dev/...`或机身路径传给主机Python。**

```python
from pathlib import Path
import hashlib, struct

source = Path('appFw.official.so')
target = Path('appFw.ntsc-only.so')
assert source.is_file() and not source.is_symlink()
raw = source.read_bytes()
assert len(raw) == 97368304
assert hashlib.sha256(raw).hexdigest() == '41bd8f4cda1f44c7038912837737e1ce6a650065f2108061ada30e5c7f9ce7c7'
out = bytearray(raw)
for at, dest in ((0x20c99a4,0x20c99c0),(0x20c9ea4,0x20c9ecc)):
    assert raw[at:at+4] == bytes.fromhex('226f8052')
    struct.pack_into('<I',out,at,0x14000000 | (((dest-at)//4)&0x03ffffff))
assert hashlib.sha256(out).hexdigest() == '16e754dc386231654090f01e45a3d0240a1f6159a446d7510a67cd0def3678c3'
with target.open('xb') as stream:
    stream.write(out)
```

若不是该完整摘要，停止；不能删除完整摘要检查，只保留8字节前像检查来宣称适配了另一版本。若要给本项目4.06 AP叠加，该两处已经修改，应拒绝重复修改，而不是再寻找“相似指令”。

## 3. 独立NTSC候选与整合候选的区别

下面公共步骤的`--feature all`复现完整4.06。如果只要NTSC，在第三步将它改成：

```sh
"$PY" "$KIT/materials/reproduce.py" \
  --workspace "$RUN/work" --feature ntsc-only \
  --receipt "$RUN/components-applied.json" > "$RUN/components.log"
```

这个组合只替换工作AP的两条指令，并保留本研究WBI2→WBI3的一字节标记；CP和68份资源保持原厂。独立AP目标摘要为`16e754dc386231654090f01e45a3d0240a1f6159a446d7510a67cd0def3678c3`，不是整合版d159…摘要。它是另一个离线候选，不能拿它声称包含FL2／FL3、六滤镜或声音。

整合版AP同时有其他功能，只能比较这两个局部窗口是否保留，不能要求其完整摘要等于NTSC-only。代码参考[r5_ntsc.py](materials/source/analysis/custom-features-20261021-03/research-materials-v3/code/r5_ntsc.py)原`patch()`只接受历史4.04 AP前像；其输入门槛不适合直接调用原厂AP，本文最小代码和统一脚本另行绑定原厂前像。

## 4. 验证条件分支，而不是只看写入成功

1. 用AArch64反汇编确认两条新B指向上表目标。
2. 分别覆盖两个启动窗口，枚举地区、当前制式、默认制式、复位、启动、显示状态及其他条件。
3. 旧逻辑确实选到0x379时，新逻辑必须收敛到原生后续分支。
4. 旧逻辑没有选到0x379时，比较结果、走过的指令和现场寄存器，不应发生额外变化；非法枚举诊断也应保留。
5. 校验无预期外内存写入；不能拿“没有运行崩溃”代替路径正确。

历史`validate()`遍历明确的768组输入组合，锁、getter和解锁是显式外部边界；没有启动整台相机或渲染提示。实现见上述源码的`replay()`／`validate()`。本材料的独立二进制组合另行检查完整前／后摘要和不覆盖原文件。

## 可直接执行的离线复现步骤

以下命令面向macOS／Linux的bash或zsh。材料中的Python组件工具没有硬编码本机路径，但本轮只在macOS arm64验证；Windows命令行没有验收。

**此入口复现当前整合4.06，包含四项功能，不是仅修改本文一项。** 四份文档按研究主题拆分，共享CP包装器、Gamma、加载和AP代码，不能把四份不同CP二进制相互覆盖。只有NTSC文档另提供经过校验的独立AP组合。

### 第一步：准备输入和运行环境

需要Python3.12及以上、`uv`，以及有合法使用权的原厂A7R5 4.00 DAT。把路径替换成自己的真实路径；保留引号。

```sh
KIT="/path/to/a7r5-firmware-features文档-20261023"
OFFICIAL="/path/to/official-4.00/BODYDATA.DAT"
RUN="$KIT/work-$(date +%Y%m%d-%H%M%S)"
mkdir "$RUN"
uv venv "$RUN/venv" --python 3.14
uv pip install --python "$RUN/venv/bin/python" -r "$KIT/materials/dattool/requirements.txt"
PY="$RUN/venv/bin/python"
```

依赖版本已固定：numpy2.5.4、pycryptodomex3.24.1、cryptography50.0.2。不要修改系统Python或拿其他机型固件尝试这些偏移。

原厂DAT必须满足：

```text
长度：754525608字节
SHA-256：51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2
机型：ILCE-7RM5，明文机型字段0x11030080
版本：原厂4.00
```

### 第二步：完整验证原厂包，解包到全新工作副本

```sh
"$PY" "$KIT/materials/dattool/dattool.py" verify "$OFFICIAL" > "$RUN/original-verify.json"
"$PY" "$KIT/materials/dattool/dattool.py" unpack "$OFFICIAL" --output "$RUN/work" > "$RUN/unpack.json"
```

`verify`验证全部帧；不能用只读首帧的`inspect`代替。新工作目录需要约1GiB，打包还需要至少3GiB空闲临时空间。解包器不在主机展开归档中的符号链接，只在清单保存链接信息。

### 第三步：修改工作副本中的组件

```sh
"$PY" "$KIT/materials/reproduce.py" \
  --workspace "$RUN/work" --feature all \
  --receipt "$RUN/components-applied.json" > "$RUN/components.log"
```

执行前会检查原厂DAT来源、所有AP／CP／UXC／WBI文件的完整SHA-256和补丁前像；先生成全部目标，再替换工作副本。原始DAT不会被打开写入。

本步骤修改：

- `components/usr/lib/appFw.so`：最终AP，97368304字节。
- `components/cpapp-b.bin`：最终CP，17617008字节。
- `components/usr/share/app/string_*_horizontal.uxc`及`_vertical.uxc`：68份资源，各增长132字节。
- `archive/0700_part_image/dev/nflasha5`：只改偏移3，WBI2→WBI3。此标记不证明实际冷启动、NOR或CP已重新加载。

回执必须为`WORKSPACE_COMPONENTS_VERIFIED`。新AP／CP必须分别为：

```text
AP d15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9
CP 18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97
```

脚本拒绝已经修改过的前像，不能在同一个work目录重复执行。若替换工作文件中途失败，目录可能部分修改；不要继续打包，也不要修改摘要门槛“强行通过”，应从原厂DAT另建全新work重做。没有自动机身恢复或自动刷写动作。

### 第四步：用与机身信任相配对的研究身份打包

```sh
KEY="/private/path/research-signing-private.pem"
PUBLIC="$KIT/materials/dattool/keys/research-public.pem"
"$PY" "$KIT/materials/dattool/dattool.py" pack "$RUN/work" \
  --output "$RUN/BODYDATA.DAT" --version 4.06 \
  --private-key "$KEY" --public-key "$PUBLIC" > "$RUN/pack.json"
"$PY" "$KIT/materials/dattool/dattool.py" verify "$RUN/BODYDATA.DAT" \
  --public-key "$PUBLIC" > "$RUN/final-verify.json"
```

`KEY`必须是RSA-2048配对私钥，在macOS／Linux上权限为0600。**材料未附私钥；没有配对私钥则不能完成这条打包路径。** 原项目已有本机私钥或先前独立工具包中的私钥，需要所有者单独保管和交付。不要将私钥写进Markdown、命令参数字符串或公开仓库。

本材料配套研究公钥PEM SHA-256为：`7f65b296987df665da217de514e785f75238e686ddd18952fa425fc47e8c858a`。不是索尼官方公钥，也不是索尼私钥。若使用自己的身份，需要使用匹配公钥，并另行解决机身信任；这四份功能文档不提供信任环境写入方案。

打包器合并组件到分区，更新对应归档`.sum`中的CRC32，更新BCD版本头与头CRC，再加密、签名和完整回读。不手改`manifest.json`、`.sum`、文件系统分配或签名字段；不要同时修改同一分区的原始镜像与其内部组件。

`4.06`是本次研究版本示例，不是官方4.06。相同／更高版本机身是否接纳未由此证明；不要自行加入同版本绕过。打包器选择的空闲块分配次序可能不同于历史构建，因此**目标组件摘要应完全一致，整份DAT摘要不强求等于历史文件**；最终以本次完整回读回执绑定输出。

### 第五步：完成验收后才讨论上机

`final-verify.json`必须有签名通过、`full_frame_validation=true`、正确机型和研究版本。该校验不等于机身更新器接纳、完整启动或实拍成功。

本手册的自动步骤到此结束，不操作USB／SSH／SD卡。若后续决定实机试验，必须另行核对当前机型、固件、更新器信任、版本准入、供电及恢复条件，再由操作者通过原厂菜单完成。完整DAT可能重写分区，不能把“改了几个字节”理解为机身只写几个字节；旧DAT也不自动等同可用救援包。

## 随附材料如何使用

- [固定输入与二进制修改清单](materials/recipes.json)：记录每个组件完整前／后摘要、AP／CP每段前后字节及68份名称资源摘要。
- [可运行重建入口](materials/reproduce.py)：Python标准库实现；只改解包工作副本。
- `materials/dattool/`：可迁移的DAT工具源码、固定依赖、原厂与研究公钥及许可说明，不含私钥或虚拟环境。
- `materials/source/`：对应原研究源码快照，供阅读实现。原源码有工作区路径和其他依赖，**不要把快照当成可独立执行的构建入口**；直接复现使用上面的统一入口。
- [来源记录](materials/source-provenance.json)：固定源码摘要；[材料验收](materials/validation.json)记录本轮实际运行结果。

本材料直接复现的是固定算法与表的既定版本，不是任意滤镜编辑器。改变曲线、矩阵、枚举或代码以后，旧目标SHA-256不再有效，需根据本文引用的源码重建、重新审查并产生新证据，不能只修改预期摘要绕过检查。


## 实机验收与失败处理

实机只可按正常菜单设置触发相关NTSC启动场景，确认目标提示消失，同时确认制式仍由原菜单设置、PAL／其他提示不被一起吞掉。文档本轮未在机身执行这些动作，不能直接标记“关闭成功”。

若仍有提示，记录实际提示内容、AP文件身份、启动场景及是否恢复旧暖启动快照；不要在未知位置继续搜索并删除相同消息ID。若启动异常，保留日志和供电状态，不自动断电或刷回另一包；“保留原文件”不是已证明的救援方式。

### 材料自身的检查

解压后先进入本材料目录，运行文件清单核对与临时合成测试：

```sh
cd "$KIT"
shasum -a 256 -c SHA256SUMS
"$PY" "$KIT/materials/selftest.py"
```

`selftest.py`不需要额外依赖，覆盖9项测试方法（含多个子场景），只生成并清理系统临时目录中的合成文件。完整复现的实际验收见`materials/validation.json`：原厂解包、71项目标工作文件、重新打包及全部736841帧的独立校验已通过；NTSC局部原厂窗口768组对照通过。另一次AP／声音历史回归为38通过、1失败，失败项因旧路径`Desktop/123/FL2.ARW`已不存在，不能声称旧原片完整性重验通过。当前材料不包含原片。

独立`ntsc-only`已验证AP目标和局部路径，但本轮没有另建并完整验收它的DAT；不能借整合DAT通过替代该独立组合的整包证据。
