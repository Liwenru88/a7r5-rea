# R5 fastboot 恢复入口

这个目录整理 R5 临时进入 fastboot、读取当前状态并按受限范围恢复设置分区的入口。它不包含原机镜像、原始采集资料、签名材料、DAT 或预编译 USB 程序。

本目录包含恢复入口及其 Python 依赖源码。`r5_sd_recovery.py` 是启动包装，实际流程在同目录 `r5_sd_recovery_impl.py`；其余分区、BK4、稀疏镜像和签名辅助模块也在本目录。原 `tools/` 入口继续保留供历史调用，不能把两份源码混用；独立目录的实现以本目录文件为准，并继续引用受保护的首次输入和当前 USB host 工具。

## 纯离线 MODE5 候选生成（新增）

`sd_trigger_offline.py` 仅生成和校验候选，不打开串口、不访问 USB、不刷写、不重启；也不会导入旧恢复执行入口。需要当前机身新读取的完整 20 MiB logical `nflasha2` 镜像，不能使用 raw 加密镜像或历史备份代替。本工具无法证明输入的新鲜度、机身身份或固件兼容性。

从仓库根目录执行，下列 `--settings` 必须替换成实际新回读路径：

```sh
.venv/bin/python -B a7r5-fastboot/r5-fastboot-recovery/sd_trigger_offline.py \
  --settings /absolute/path/to/fresh-settings.logical.img \
  --package a7r5-firmware-features/releases/4.19-full-repaired-20261111/BODYDATA.DAT \
  --output "a7r5-fastboot/runs/sd-trigger-offline-$(date +%Y%m%d-%H%M%S)"
```

输出 `OFFLINE_ONLY.settings.logical.img`、`OFFLINE_ONLY.trigger.sparse.img` 和 `report.json`，拒绝覆盖已有输出目录。候选仅将 `/updater/dat4` 置为 0.00，并在缺失时创建空 `mode`/`mode5`；检查冲突标志、独立 FAT 解析、其他文件和元数据保持、最多 66 字节/3 扇区变化、稀疏重建及幂等性。升级包只记录大小和 SHA-256，不检查包格式、签名、机型或机内更新器兼容性。所有候选均禁止直接作为实机刷入授权。

测试使用仓库历史镜像，仅验证算法，不代表故障机当前状态：

```sh
.venv/bin/python -B -m pytest -q -p no:cacheprovider a7r5-fastboot/r5-fastboot-recovery/test_sd_trigger_offline.py
```

## 功能范围

入口使用 RP2040 串行引导把临时 RAM fastboot 载荷送入相机，再通过 USB fastboot 完成受限操作。恢复流程的写入目标只有 `nflasha2`，写入内容是基于本次新读设置镜像生成的稀疏差异；写前会重新读取并核对分区表、BootROM、更新器和完整设置分区，写后会完成 20 MiB logical 回读、40960 个 raw 扇区 XTS 核验和正常 reboot。

`prepare` 默认只做离线准备和模拟检查；`execute` 会连接设备并执行真实写入，必须在同一连续会话中完成新备份、核对、写入、回读和重启。接口消失、几何不符、散列不符或写后回读异常时停止，不跳过核对，不自动回滚。

## 入口

```sh
python3 -B tools/r5-fastboot-recovery/r5_sd_recovery.py --prepare
python3 -B tools/r5-fastboot-recovery/r5_sd_recovery.py --execute --port /dev/cu.usbmodemXXXX
```

包装入口保留原脚本的参数和校验。执行前必须具备本机原始依赖：`~/Downloads/bootloader脚本.zip`、受保护的首次 R5 4.00 备份、固定的 `analysis/r5_live_system_20261014/host_tools`，以及仓库内当前工具模块。不要把这些私有输入复制进本目录或提交到 Git。

## 结果边界

脚本能证明 fastboot 进入、分区几何、限定写入和设备回读；正常 reboot 应答不等于相机已经完成启动、菜单或成像恢复。恢复后仍需单独检查版本、拍摄、重启后保持和 FL/FL2/FL3 实际照片。

入口实现散列由执行目录的 `manifest.json` 记录。历史 `analysis/` 目录只作证据保存，不能替代当前入口或直接作为恢复输入。
