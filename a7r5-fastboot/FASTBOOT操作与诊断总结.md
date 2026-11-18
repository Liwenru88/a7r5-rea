# A7R V RAM Fastboot 进入、退出与只读诊断总结

## 1. 结论摘要

本次实机流程验证了以下路径：

1. Mac 连接 RP2040-Zero，RP2040 负责通过 Sony Multi 口发送复位、RAM Fastboot 引导记录和 UART 桥接。
2. 相机的 Fastboot 数据链路使用 Multi→USB-A 连接 Mac；RP2040 串口和相机 Fastboot USB 是两条独立链路。
3. `manual_fastboot.py` 会等待人工回车，之后只执行一次复位和完整 RAM payload 发送，并保持连接。
4. 相机枚举为 Sony Fastboot 后，先执行 USB configuration，再进行只读读取。
5. 进入升级流程前，通过 `nflasha2` 的受限变更创建 `/updater/mode`、`/updater/mode5`，并将 `/updater/dat4` 置为 `0.00`。这不是把 `BODYDATA.DAT` 直接刷进 `nflasha2`。
6. 写后逻辑回读与候选完全一致，SDM2 保持不变，然后发送一次 `reboot`，由相机原生升级器读取 SD 卡上的 `BODYDATA.DAT`。

> 当前记录中，raw/XTS 独立校验因缺少原始 `part_key[64]` 密钥源尚未完成；不要把逻辑回读成功等同于 raw/XTS 验证完成。

## 2. 准备条件

- macOS；
- RP2040-Zero 已烧录 `assets/uart_boot.ino.uf2`；
- RP2040 串口 VID 为 `0x2E8A`；
- 相机保持 ON，电池充足，停止其他更新程序；
- RP2040 接线：GP28→Multi 7、GP29→Multi 8、GP27→Multi 9、GND→Multi 2；5V/3V3 留空；
- Multi→USB-A 数据线连接 Mac；
- 输出目录必须是新目录；
- 任何写入前都应保存当前机身的 `nflasha2`、SDM2 和其他必要证据。

## 3. 进入稳定 Fastboot

在项目根目录运行：

```sh
python3 -B a7r5-fastboot/manual_fastboot.py \\
  --output "a7r5-fastboot/runs/manual-fastboot-$(date +%Y%m%d-%H%M%S)" \\
  --confirm-reset
```

省略 `--port` 时，脚本自动寻找唯一的 `/dev/cu.usbmodem*` RP2040 设备，要求 VID 为 `0x2E8A`。需要固定端口时：

```sh
python3 -B a7r5-fastboot/manual_fastboot.py \\
  --port /dev/cu.usbmodemXXXX \\
  --output "a7r5-fastboot/runs/manual-fastboot-$(date +%Y%m%d-%H%M%S)" \\
  --confirm-reset
```

看到下面提示后，确认接线和设备状态，再按第一次回车：

```text
准备好后按回车触发；Ctrl+C 取消：
```

成功后会显示：

```text
RAM payload 已发送，正在保持连接。
现在可以在其他终端手动分析 Fastboot；完成后回到这里按回车退出。
```

此时不要退出该终端。它会保持 RP2040 串口并记录 `uart.bin`。

## 4. 确认 Fastboot USB

另开终端执行：

```sh
a7r5-fastboot/host/configure_fastboot_usb
```

成功标志：

```text
SetConfiguration(1)=0x00000000
```

如果出现 `0xe00002ed`、`No Fastboot interface` 或退出码 2/3：

- 不要继续读写；
- 不要重复发送写命令；
- 检查 Multi→USB-A 数据链路、Hub/转接器和 USB 占用；
- 必要时回到手动脚本终端按退出回车，重新建立干净会话。

只看到 Sony 设备的 VID/PID，不代表 Fastboot interface 已经可打开；应以 `configure_fastboot_usb` 成功为准。

## 5. 只读采集

一次采集分区表、SDM2、AP BootROM、`nflasha2`、`nflasha5` 和 `nflasha2` raw：

```sh
sh a7r5-fastboot/fastboot_readonly_capture.sh
```

也可指定新输出目录：

```sh
sh a7r5-fastboot/fastboot_readonly_capture.sh \\
  a7r5-fastboot/runs/readonly-$(date +%Y%m%d-%H%M%S)
```

脚本只允许只读命令，明确拒绝 `flash:*`、`erase:*`、`download:*`、`reboot`。

## 6. 分区表与尺寸

已验证过的分区布局包括：

```text
nflasha2  start=0x0000c000 count=0x0000a000 fat
nflasha5  start=0x00041800 count=0x00096000 wbi2
```

当前设备回读尺寸：

```text
nflasha2 logical：20 MiB
nflasha5 logical：300 MiB
SDM2：64 KiB
AP BootROM：48 KiB
```

## 7. 退出 Fastboot

### 正常退出

如果只是手动分析，不做写入：

1. 回到运行 `manual_fastboot.py` 的终端；
2. 按第二次回车；
3. 等待 `report.json` 写入完成；
4. 再关闭其他终端。

### 通过相机 Fastboot 重启

只有在明确完成写后回读、并获得单独授权时，才发送：

```text
reboot
```

重启后不要拔电、拔卡或拔线，等待相机完成升级或启动。不要把正常 Fastboot 退出和升级完成混为一谈。

## 8. 本次实机证据与结论

### 4.19 包

SD 卡中的 `BODYDATA.DAT` 与本地 `4.19-full-repaired-20261112` 包逐字节一致：

```text
大小：754,525,608 bytes
SHA-256：d486853533711a282c5e0794f6e98931608c1d2c581e3b25cd70da8b48ce5503
```

### 当前机身备份

写入前回读：

```text
nflasha2：8959a84b3b291fdda858d1fe02f94fb788b68f00d5a3aed2b29042ec84a42490
nflasha5：28fbfa0ff2a345a4430be129397a6caccdd97fbcff1b8069af8e49aa73556c68
SDM2：1c2c4b0548a49a3ec25ef4b5f09540ca78c4432cc0419e0c07e626ff2f77d7e6
```

### 受限候选

候选只改变升级触发相关内容：

```text
/updater/dat4 → 0.00
创建空标志：/updater/mode、/updater/mode5
改变字节：44
改变扇区：2
```

候选逻辑 SHA-256：

```text
aba8b347fee61e9a37751ab8d334d1d0a9a83f6ab8da8a51ee0c01165b41f342
```

### 写后逻辑回读

写后 `nflasha2` SHA-256 与候选一致：

```text
aba8b347fee61e9a37751ab8d334d1d0a9a83f6ab8da8a51ee0c01165b41f342
```

写后 SDM2 SHA-256 仍为：

```text
1c2c4b0548a49a3ec25ef4b5f09540ca78c4432cc0419e0c07e626ff2f77d7e6
```

### 退出与升级

最终发送一次：

```text
COMMAND reboot
REPLY OKAY
```

随后相机已进入升级流程。此结果说明 Fastboot 接受了重启，升级由相机原生升级器继续执行。

## 9. 风险与未完成项

- `BODYDATA.DAT` 的字符串和包摘要不能替代官方签名/机型兼容性证明；
- 当前逻辑回读已一致，但 raw/XTS 全扇区独立校验因缺少可信 `part_key[64]` 来源未完成；
- 当前设备标识与历史参考是否为同一物理机身，不能仅凭 SDM2 一致性证明；
- 升级进入流程不等于升级最终成功；仍需等待相机自行完成并检查能否正常开机；
- 未经再次授权，不应执行任何额外写入、擦除或重启。

## 10. 最新成功记录（2026-11-15）

本次使用手动把握进入时机，随后复用唯一 Fastboot 会话完成更新触发。执行目录：

[authorized-update-20261115-142102](runs/authorized-update-20261115-142102)

使用的包：

```text
/path/to/BODYDATA.DAT
大小：754,525,608 bytes
SHA-256：687221e0c35669dc72578521b335eae6174404b35d30d9c9c31d305e1ffe49
```

写入前当前 `nflasha2`：

```text
a250bb5a9ccf9dd6969fb13b279723eab37ce292e83b2d214996031eaf811bfd
```

当前设置区解析为 4.21。候选只修改 `/updater/dat4`、`/updater/mode`、`/updater/mode5`，变更 44 字节、2 个扇区；FAT、目录元数据、其他文件和幂等性检查均通过。

候选 SHA-256：

```text
4f16422b203b4912fce019cb2609fc55bdbb344ba1c22abd245a5a133a6ce04f
```

写入仅使用：

```text
download:<当前候选 sparse>
flash:nflasha2
```

设备确认写入 2 个扇区。写后回读结果：

```text
nflasha2 回读 == 候选：是
SDM2 写前后保持一致：是
```

最终发送：

```text
COMMAND reboot
REPLY OKAY
```

随后相机进入 SD 卡升级流程。

## 11. 关于“取消所有门禁”的边界

不能将流程改成不检查包、不检查当前分区、不做写后回读、直接对任意输入执行刷写。这样会失去以下保护：

- 错误机型或损坏升级包无法拦截；
- 当前设备状态变化无法发现；
- 写入中断或部分写入无法阻止 reboot；
- 可能误写 `nflasha5` 或其他分区；
- 无法判断 SD 卡中的包是否与主机选择的包一致。

可以做的简化是：保留大小、SHA-256、唯一会话、目标分区白名单、候选范围、写后回读和显式授权，把人工步骤压缩为一条命令；不能移除这些安全门禁。

## 12. 关键文件

- `manual_fastboot.py`：手动触发复位和 RAM Fastboot，保持连接；
- `enumerate_fastboot.py`：只读枚举 RP2040 和 Sony USB 设备；
- `fastboot_readonly_capture.sh`：只读采集脚本；
- `r5-fastboot-recovery/prepare_current_4_19.py`：当前 4.19 离线候选准备；
- `r5-fastboot-recovery/audit_current_4_19_writer.py`：静态 writer 合约审查；
- `r5-fastboot-recovery/build_current_4_19_writer.py`：受限 writer 构建器；仅允许在明确授权和写前门禁完成后使用。
