# 4.28 稳定版本源码归档与构建说明

本目录包含从 Sony ILCE-7RM5 原厂 `4.00` 官方升级包（`BODYDATA.DAT`）完整重建 `4.28` 稳定版本的自包含源码与一键脚本。

## 1. 归档目录结构

| 路径 | 说明 |
| --- | --- |
| `source-tree/build-tree/` | 4.28 完整独立的编译输入树（5.2MB，含 `native24-combined`、`lens-af-compat`、`look-fl2-fl3`、`dependencies/native12-combined` 等全部编译源码） |
| `source-tree/patch-428.json` | 4.28 对 `unified-look.c` 与 `build.py` 的补丁指纹回执 |
| `build_428_from_400.py` | 一键端到端构建脚本（从原厂 `4.00` `BODYDATA.DAT` 到 `4.28` 交付物） |
| `build.py` / `container_package.py` / `evidence_gate.py` | 4.28 离线容器封包、双次构建校验、RSA 签名与独立解包回读 |
| `test_patch_428.py` / `test_release.py` | 4.28 补丁不变式与发布配置单元测试 |
| `../../scripts/build_428_from_400.sh` | 仓库根目录快捷 Shell 入口 |

## 2. 宿主机工具链依赖

- Python 环境：仓库根目录 `.venv/bin/python`（含 `pyelftools`、`pytest`、`cryptography`）
- 交叉编译与链接：`/opt/homebrew/opt/llvm/bin/clang`、`/opt/homebrew/opt/lld/bin/ld.lld`
- 宿主机工具：`clang`、`/opt/homebrew/opt/e2fsprogs/sbin/e2fsck`、`/usr/bin/openssl`
- 原厂 `4.00` 输入：`a7r5-firmware-images/官方升级包/BODYDATA.DAT`（SHA256：`51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2`）

## 3. 一键快速构建（支持对外指定原厂 4.00 包）

在仓库根目录执行（直接传入原厂 `4.00` `BODYDATA.DAT` 路径）：

```sh
./scripts/build_428_from_400.sh /path/to/4.00/BODYDATA.DAT
```

指定自定义输出目录（支持任意路径，例如桌面；默认仅导出最终 `delivery` 文件并清理 `.local/` 中间目录）：

```sh
./scripts/build_428_from_400.sh /path/to/4.00/BODYDATA.DAT -o ~/Desktop/a7r5-4.28
```

若本机已存在默认原厂包（`a7r5-firmware-images/官方升级包/BODYDATA.DAT`），也可直接无参运行，或使用 `-i/--original`、`--keep-work`：

```sh
./scripts/build_428_from_400.sh
./scripts/build_428_from_400.sh -i /path/to/4.00/BODYDATA.DAT -o .local/build-428-custom
```

如需指定 Python 解释器，可通过环境变量 `PYTHON_BIN=/path/to/python ./scripts/build_428_from_400.sh ...` 覆盖。

## 4. 内部四阶段流水线

1. **原厂 4.00 基线解包与校验**：调用 `dependencies/native12-combined/build.py --phase baseline` 解包原厂 `BODYDATA.DAT`，校验 `inputs.lock.json` 与 12 份原厂模板。
2. **FL2/FL3 基底与 `nflasha15` 提取**：使用 `a7r5dat.tool.unpack` 与 `dependencies/baseline_recipes.json` 从原厂 `4.00` 提取 `nflasha15`（`197fc934...`）并派生 `ap_baseline.so`（`a8d5cd44...`）、`cp_baseline.bin`（`8e9e26bf...`）。
3. **4.28 双次确定性编译（`runtime` + `rebuild`）**：调用归档 `source-tree/build-tree/a7r5-firmware-features/native24-combined/build.py` 编译 `appFw.so`、`cpapp-b.bin`、`image_00_23_IPSX.uxc`、`image_00_32_IPSX.uxc`。
4. **容器封包、验签与 SHA256 核对**：调用 `release428/build.py` 打包签名、执行 736841 帧回读与 `e2fsck -fn`，最终校验 `BODYDATA.DAT`（`ed98e87a...`）与 `R5NATIVE.BIN`（`19e020fa...`）摘要完全一致。
