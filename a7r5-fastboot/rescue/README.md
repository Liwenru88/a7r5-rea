# nflasha1 写入失败救援包（离线构建，未实机验证）

用途：如果对 `nflasha1`（更新器分区，25,100,288 字节）的信任写入中途失败，
用 fastboot 把这 258 个被写入的扇区恢复成写前内容。分区其余 24.9 MB 从未被本事务触碰，
所以"只恢复这 258 个扇区"在数学上等价于整分区恢复。

## 内容与位置

| 文件 | 作用 | 校验 |
|---|---|---|
| `assets/rescue-to-original.sparse` | 132,256 字节 sparse（Android sparse，49024 块 × 512 B），把候选镜像的 258 个扇区覆盖回写前原像 | sha256 `5968c55afd3a2fba12157867b987925cb2b2beff13db7e15d30e034970d8b628` |
| `host/rescue_writer` | 只接受 `download:<sparse>` + `flash:nflasha1`，内置 sparse 摘要白名单 | 由 `build_rescue_writer.py` 生成 |
| `host/read_nflasha1` | 只读工具，允许 `oem partition dump nflasha 0x80 0xbf80`（整分区） | 由 `build_read_nflasha1.py` 生成 |
| `host/configure_fastboot_usb` | 配置一次 Fastboot USB 接口 | 见 `../ASSETS-PROVENANCE.md` |

源码与生成脚本都在本目录；二进制在 `host/`、稀疏镜像在 `assets/`（模块 `.gitignore` 约定不入库）。

重建：

```sh
cd a7r5-fastboot
.venv/bin/python -B rescue/build_read_nflasha1.py
# 先用本次写前/写入后镜像重新生成 sparse，再编入 writer
.venv/bin/python -B rescue/build_rescue_sparse.py \
  --before <写前镜像> --after <写入后候选镜像>
.venv/bin/python -B rescue/build_rescue_writer.py
```

`build_rescue_sparse.py` 会自检“候选 + sparse == 写前镜像”，并拒绝超过 512 KiB 的 sparse。
换方案（258↔233 扇区）或换机身时，必须先重新生成 sparse，再重编 writer。

> `rescue-to-original.sparse` 绑定本机写前镜像 `1c97db64…208e1441`。换机身或写前状态变化后必须重新生成。

## 已验证（离线）

- sparse 对候选镜像、以及 1/50/100/200/258 个扇区的任意"半写"状态应用后，都精确等于写前原像 `1c97db64…208e1441`；
- `rescue_writer` 参数门：无参数、`flash:nflasha2` 都在打开 USB 前返回 2；正确参数在无设备时返回 5，不写任何东西；
- `read_nflasha1` 编译通过，整分区 dump 命令在二进制中确认，且不含 `download:`/`flash:`/`erase:`。

## 未验证

- 从未在真实相机上执行过 `flash:nflasha1`（仓库历史只在 2026-10-14 用另一份 233 扇区 sparse 做过一次；2026-11-08 的回退记录用 raw/XTS 路径写回 258 扇区）；
- 缺少 `assets/fastboot.bin`、RP2040 硬件与 Multi 接线；
- 设备端是否接受 `49024` 块的 sparse 头、`flash:nflasha1` 的写保护行为，未在本机复验。

## 救援流程（材料齐备后）

在 `a7r5-fastboot/` 目录下：

```sh
# 0) 进入 RAM Fastboot（RP2040 + 接线；会复位一次相机）
.venv/bin/python -B manual_fastboot.py --output <新目录> --confirm-reset

# 1) 配置 USB（期望 SetConfiguration(1)=0x00000000）
host/configure_fastboot_usb

# 2) 先记录当前状态：整分区回读
host/read_nflasha1 "oem partition dump nflasha 0x80 0xbf80" "upload:<新目录>/nflasha1.before.bin"

# 3) 写前判定：写前/写完/任一顺序半写状态都接受；其他状态必须停
.venv/bin/python -B rescue/verify_nflasha1.py \
  --image <新目录>/nflasha1.before.bin --known-partial \
  --source <写前镜像> --candidate <候选镜像> --plan <write-plan.json>
#    退出码 0 才继续

host/rescue_writer "download:$(pwd)/assets/rescue-to-original.sparse" "flash:nflasha1"
#    期望：APPROVED_SPARSE … / REPLY OKAY

# 4) 整分区回读核对
host/read_nflasha1 "oem partition dump nflasha 0x80 0xbf80" "upload:<新目录>/nflasha1.after.bin"
.venv/bin/python -B rescue/verify_nflasha1.py \
  --image <新目录>/nflasha1.after.bin \
  --expect 1c97db64e77eb7e2caa90ffa1c78a7fa48c6ac0bb9b10774c115bf0a208e1441
#    退出码 0 = 已回到写前原像

# 5) 只有第 4 步一致才 reboot
host/read_nflasha1 reboot
```

任何一步失败：停止，不重发 `flash`，保留 UART/USB 日志与回读文件。

## 边界

- 只能恢复"本事务可能改动的 258 个扇区"；不能修复其它原因造成的损坏。
- 若当前分区不是 `1c97db…`、候选，或写前/候选之间的顺序半写状态，救援目标不再匹配，必须停并重新生成 sparse。
- `reboot` 之后仍应检查版本、拍摄、重启保持；Fastboot 接受命令不等于相机已恢复正常。

## 方案变体（必须成对使用）

| 方案 | 稀疏镜像 | 写入器 | 适用 |
|---|---|---|---|
| replace-key（258 扇区） | `assets/rescue-to-original.sparse`（`5968c55a…`） | `host/rescue_writer`（`73afb04d…`） | 本仓库原有 258 候选（写入时替换 PEM） |
| skip-key（233 扇区） | `assets/rescue-to-original-233.sparse`（`97665dea…`） | `host/rescue_writer_233`（`e49decbf…`） | verifyKey-only 候选（不替换 PEM） |

- 稀疏镜像和写入器必须由**同一份写前/候选镜像**生成；混用会把分区恢复成错误内容。
- 生成命令（以 233 为例）：

```sh
cd a7r5-fastboot
.venv/bin/python -B rescue/build_rescue_sparse.py \
  --before <写前镜像> --after <233 候选镜像> \
  --output assets/rescue-to-original-233.sparse
.venv/bin/python -B rescue/build_rescue_writer.py \
  --sparse assets/rescue-to-original-233.sparse --output host/rescue_writer_233
```

- 写入器内置的稀疏摘要白名单在生成时钉死；换镜像后必须重编。
