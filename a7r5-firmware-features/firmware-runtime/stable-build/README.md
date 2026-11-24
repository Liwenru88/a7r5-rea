# 稳定版构建资源

仓库统一从官方 4.00 `BODYDATA.DAT` 构建当前稳定版。稳定版的版本号来自 [KNOWN-ISSUES.json](KNOWN-ISSUES.json)，用于构建输出、DAT 容器和验证回执。

```sh
./scripts/build_from_400.sh /path/to/4.00/BODYDATA.DAT -o /new/output/directory
```

| 路径 | 用途 |
|---|---|
| `build.py`、`container_package.py` | 编译编排、封包和独立回读 |
| `source-tree/` | 当前稳定版的直接编译输入，包含运行时、画幅源码及配套编译依赖 |
| `filters/` | 24 槽配方源码和导出审计，构建时生成并核对 `R5NATIVE.BIN` |
| `PACKAGE-README.md`、`KNOWN-ISSUES.json` | 随包说明和版本状态 |

后续更新沿用此目录和 `scripts/build_from_400.sh`。调整稳定版版本号时更新 `KNOWN-ISSUES.json`，并按实际验收更新随包说明。公共 DAT 工具、原厂输入与本机研究签名材料沿用现有位置。[构建输入说明](../../../docs/build-inputs.md)
