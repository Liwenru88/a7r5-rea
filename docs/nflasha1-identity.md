# nflasha1 备份摘要差异（研究笔记）

结论先行：**观察到的每一台机身的 nflasha1 备份摘要都不同，而且差异不只是 FAT 元数据——里面的
initrd / vmlinux 本身就是不同构建。** 整分区 SHA-256 绑定的是"某一次更新产物"，不是"4.00 版本"。

## 样本

| 样本 | 来源 | nflasha1 SHA-256 | initrd.img MD5 | vmlinux.bin MD5 |
|---|---|---|---|---|
| `acf32…` | `标准固件_19项/明文分区_17项`（reference-v1 计划源） | `acf32d30…` | `eeab3100…` | `8012c2a0…` |
| `ba3933…` | stock-v1（另一台原厂 4.00 机身采集） | `ba393345…` | `0560e1e2…` | `e2aaf14c…` |
| `1c97db…` | 本机 2026-11-22 采集 | `1c97db64…` | `adfa013b…` | `b58b6795…` |
| `8babccbb…` | 官方 4.00 回退记录（2026-11-08） | `8babccbb…` | 未公开 | 未公开 |

前三个样本的 initrd/vmlinux MD5 直接来自各自分区内的 `/p1chksum`（该文件就是这两个文件的
MD5 清单），不是外部推算。

## 关键观察

1. **四个摘要互不相同**，且横跨"官方明文前像 / 另一台机身 / 本机 / 回退记录"四类来源。
2. **差异在内容层**：三份 `/p1chksum` 的 initrd 与 vmlinux MD5 全部不同，说明不是时间戳级别的差异。
3. **计划也不通用**：`acf32` 与 `ba3933` 的 258 个目标扇区 **258/258 不同**，合计
   130,656 / 132,096 字节（98.9%）不同；只有末尾校验扇区差 58 字节。
4. **偏移也不是全同**：本机计划与 `acf32` 计划都是 258 行，但只有 160 个偏移重合，首尾偏移
   分别为 497,152 / 15,843,840 与 423,936 / 15,843,840。
5. **FAT 元数据再叠一层**：本机镜像由 `mkfs.fat` 生成，卷序列号 `b6a225b8`、卷标 `NO NAME`；
   目录项创建/访问时间 2022-09-13，修改时间固定为 2026-05-19。卷序列号是格式化时生成的，
   即使文件内容完全相同，整分区 SHA 也会不同。

## 为什么会这样

- 官方 4.00 DAT **不带 nflasha1**：TAR 里只有 3 个程序分区（5/8/15）、2 个系统分区（3/7）、
  12 份地区模板和校验清单；`0300_partconf` 只描述分区几何（nflasha1 起始 `0x80`、长度 `0xbf80`）。
- nflasha1 是机内更新器在升级时**现场组装**的：`mkfs.fat` + `vmlinux.bin` + `initrd.img` +
  `/p1chksum`。它的内容取决于"最后一次写它的更新包/更新器"（FDAT 里的 updater 段），
  与当前 `/version.txt` 的版本号没有一一对应关系。
- 所以同一台机身的"4.00"可以对应不同 updater 构建；不同机身更是如此。

## 对方案的含义

- 把某个整分区摘要当作"原厂身份"（如 `acf32…` / `ba3933…`）只对产生它的那次更新成立；
  换机身/换更新历史就必须重新生成计划（本机已按 `1c97db…` 生成过 258 扇区计划）。
- 想快速判断两台机身是否同构：先比 `/p1chksum` 里的 initrd/vmlinux MD5，再比 258 个目标扇区，
  最后才需要整分区逐字节比对。
- 救援镜像必须绑定本机写前摘要；换机身后必须重新生成，不能复用。

## 复现

```sh
# 读取分区内 /p1chksum（initrd/vmlinux 的 MD5）与 FAT 元数据
.venv/bin/python -B - <<'PY'
import sys, struct, pathlib
sys.path.insert(0, 'a7r5-updater-trust/src')
from filesystems import FatImage
raw = pathlib.Path('.local/verify-20261122/partition1.logical.bin').read_bytes()
fat = FatImage(raw)
print('serial', raw[39:43].hex(), 'label', raw[43:54])
print(fat.read('/p1chksum').decode())
PY

# 与随包计划逐扇区比较
A=.local/research/a7rv-workbench/unpacked/a7rv-workbench/build-assets
.venv/bin/python -B .local/verify-20261122/check_preimage_vs_plan.py \
  --image .local/verify-20261122/partition1.logical.bin --plan "$A/reference-v1.json"
```

## 边界

- 样本量小（四台/四次），不能据此断言"所有机身必然不同"；但已足以说明"同一版本不等于同一摘要"。
- 回退记录的 `8babccbb…` 只有摘要，没有镜像与 `/p1chksum`，无法做内容级比较。
