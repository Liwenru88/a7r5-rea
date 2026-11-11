# 用 SpektraLab 生成 Color Lab 目标图

脚本在 Mac 上通过 SpektraLab 的 C ABI 渲染，输出 **16 位 RGB TIFF、内嵌 sRGB ICC**。每次使用一套胶片与相纸配方，生成 v4.5 训练色卡和任意数量的 A7R V 同源实拍目标。全程使用独立进程和目录，不需要启用 SpektraLab 的 Agents 设置。 [SpektraLab 源码](https://github.com/JamesQiu2005/SpektraLab/tree/spektralab-v2.3.1)

## 首次准备

在 `R5ColorLab` 目录运行。已检出的源码目录可直接传给构建脚本。

```bash
git clone --branch spektralab-v2.3.1 https://github.com/JamesQiu2005/SpektraLab.git ../../../SpektraLab
bash scripts/build_spektralab_renderer.sh ../../../SpektraLab
```

当前验证组合为 SpektraLab `2.3.1` 源码 `0b5acfc4e45b7a946ed33a3c4b4e60429d208b66`、macOS Command Line Tools 和 Apple Metal。脚本默认借用同版本 `/Applications/SpektraLab.app` 内的 Metal 库、胶片／相纸数据和 ICC，可用 `--resources` 指定对应的 `EngineResources`。引擎的 C++ 和 RAW 渲染入口由源码编译，构建产物位于外部源码的 `engine/build/colorlab/`。使用 `.venv` 内已安装 Color Lab 依赖的 Python。

## 生成一套配对目标

```bash
.venv/bin/python scripts/generate_spektralab_targets.py "$PWD/ektar100-targets" \
  --film kodak_ektar_100 --paper kodak_portra_endura \
  --photo "/path/to/DSC01234.ARW" \
  --photo "/path/to/DSC01235.ARW"
```

输出目录必须是新目录。胶片 ID 对应 `EngineResources/profiles/` 下 `info.stage` 为 `filming` 的文件名，相纸对应 `printing`。彩色负片可指定相纸或用其默认相纸。Velvia 等反转片只传 `--film`，脚本按直扫处理。需要只生成验证照时加 `--no-chart`。

| 参数 | 作用 |
|---|---|
| `--raw-ev` | RAW 解码曝光，默认 `0` |
| `--baseline-ev` | 可显式为整批设置同一个解码基准。默认保留每个 RAW 文件的基准 |
| `--film-ev` | 显影前胶片曝光，默认 `0` |
| `--print-ev` | 放大机印相亮度，默认 `0`，正值提亮 |
| `--yellow`／`--magenta` | 在固定胶片和相纸的滤色基准上加偏移，默认 `0` |
| `--settings` | 可选 JSON，允许设置密度曲线、固定预曝光、放大机光源、显影前曲线和扫描黑白点校正。其余键会被拒绝 |

脚本对整批使用拍摄白平衡，关闭自动测光、逐张配光、场景置位、颗粒、光晕、耀光和镜头几何校正。默认值保留上游引擎的基础扫描处理。`--raw-ev 0` 以文件的解码基准为起点，和 SpektraLab 2.3.1 新图默认额外加一档的行为有差别。脚本直接在渲染引擎输出 sRGB，桌面应用还可进行后续调色和输出色域映射，因此两者的 TIFF 有可能不同。 [上游 RAW 解码默认值](https://github.com/JamesQiu2005/SpektraLab/blob/spektralab-v2.3.1/app/SpektraLab/Sources/Model/FrameEdit.swift#L24-L74)

## 导入和复验

- `ColorLab-v4.5-target.tif` 导入「训练与色卡 → 软件处理后的测试色卡」。脚本使用官方 v4.5 DNG，按清单核验原始字节，再通过 Color Lab 自己的导入器读回全部 99,372 个色块。Core Image 在本机把同版合成 ARW 色卡解码成常规 A7R V 尺寸，DNG 可保留完整的 `11648 × 8736`。
- `原片名_SpektraLab.tif` 与该张原始 `.ARW` 配对，用于实拍预览验证。脚本按 Color Lab 的有效画幅和方向检查原尺寸，原片保留在原目录。DNG 色卡和实拍 ARW 的解码矩阵及基准曝光可能不同，应分别查看实拍差异。
- `manifest.json` 记录源码提交、引擎与资源散列、胶片和相纸、原片与 TIFF 散列、实际解码曝光和渲染参数。重新生成时使用同一版本、资源和命令。源文件只读，每次发布到新目录。
