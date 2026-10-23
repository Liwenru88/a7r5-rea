# 原厂 CP：串行时钟、启动备份与 AP 对端边界

2026-10-22，接续 [PCIe 侧带与 DMA 子集](native-cp-pcie.md)。本轮已越过 `0xf1388054`，原厂代码完成五个 I2C 控制器的初始化访问，并继续执行到 `USER_TSK_INIT2` 后续路径。最新首异常是读取 `0xf1388100`（PLL0 配置）。

**AP 地址窗口和通知连线尚未接通；原厂 CP 尚未处理 AP 的 `0x4063`／`0x4073`，尚未生成 `0x2040`，ISP 未完成。** 下文区分已经运行的模型、静态推导和未知项。

## 时钟与后继驱动

| 地址／表 | 原厂证据 | 此次实现与边界 |
| --- | --- | --- |
| `0xf1388054` | `0xbb6966 → 0xbb6410 → 0xbade7c`；表 `0xe67fa4` 给出时钟 ID 13～17，`0xe65d98` 给出偏移 `0x50`、位18～22 | SCU 的 DATA／SET／CLR，仅支持五路 I2C 位；未知位和偏移拒绝 |
| `0xf1388358` | 复位表 `0xe67fb8`、`0xe661b8`；ID 14～18，对应偏移 `0x350`、位24～28 | 原厂清复位后配合时钟控制实际 I2C MMIO 可达性；虚拟初态为关时钟、保持复位，不声称等于实机上电值 |
| `0xf1012000`～`0xf1016000` | 基址表 `0x1164f90`；访问 `IC_COMP_PARAM_1 +0xf4`、`IC_ENABLE +0x6c`、`IC_ENABLE_STATUS +0x9c`，符合 DesignWare I2C | 使用固定 QEMU 11.1.2 归档中的上游模型，每路 16 字节 FIFO；容量是虚拟硬件参数，未测得 Sony 实机 FIFO 深度 |
| INTID429～433 | 原厂表 `0x1164fa4` | 五路真实模型 IRQ 接入 GIC；无从设备时发生地址 NACK／TX_ABRT，不合成从设备 ACK |
| `0xf1388f48/4c/50` | 原厂 `0xbcabb4`／`0xbcac2e`／`0x56cbec` 的控制读写序列；SET 写 `0x101` | 仅保留控制请求位的 DATA／SET／CLR 子集，不自动清 busy，不提供 `+0xf54/+0xf58` 的未知状态或调频完成 |
| `0xf1388200`～`0xf1388248` | Sony `CLKSEL_PLL/UART/MEDIA/SPI/DDR` 定义及原厂 `0xb3a054` 的写后别名读取 | 五个控制银行保存软件选择；别名读供写入排空，不能证明 PLL 锁定或外设就绪 |
| `0xf1388100` | Sony `PLL(ch)=SCU+0x100+4*ch`；最新现场原厂 `0xb39f96` 在此首异常 | **仍未建模**；未填固定频率、全零 MMIO 或锁定状态 |

同族公开定义固定在 Sony 内核提交 `fa5c6f6aba58f675691e5adf291b155b76e6e93e`，见 [platform.h](https://github.com/DavidBuchanan314/Sony-ILCE-7M4-Linux/blob/fa5c6f6aba58f675691e5adf291b155b76e6e93e/linux-kernel/drivers/udif/mach-cxd900xx/include/mach/platform.h)、[regs-clk.h](https://github.com/DavidBuchanan314/Sony-ILCE-7M4-Linux/blob/fa5c6f6aba58f675691e5adf291b155b76e6e93e/linux-kernel/drivers/udif/mach-cxd900xx/include/mach/regs-clk.h)。它们用于定位，A7R5 自身指令和表值用于交叉核对；不等于完整芯片手册。

PLL0 后续依赖已经在原厂代码中定位：`0xb3d422` 读取 `0xf1388100`，结合 ROM 表更新配置，随后在 `0xb3d49e` 置 bit27，在 `0xb3d4a6` 轮询 bit24。可以确认请求／等待的代码关系，但尚不能仅据此确定全部 PLL 字段、参考时钟、复位配置和锁定条件。不能直接把 bit24 置1放行。

## 补齐原厂启动输入，未改运行时指针

五路 I2C 后出现过 `DFSR=7, DFAR=0x10`。这是页转换异常，不是新的低地址外设。

原厂 `0xba8486` 从 `0x193ea00` 读取备份表指针，再访问表内 `+0x10`。该指针为零，是因为此前启动只提供 TOMCO，没有提供 `BACKUP_INIT` 预期位于 `0x04000000` 的输入。

固定模拟归档已有 `seed-backup.bin`：2372469 字节，SHA-256：

`92697b50f6e3e25f5560a8c3eee357ea30b54e4e15cf29cd13bc30295759e3ce`

新增显式 `--with-backup`：先核对长度、摘要和两份 `BK4\0` 表头，再原样加载。第二表偏移由第一表 `+0x18/+0x1c` 两值之和按4096字节对齐得到 `0xef000`。由原厂解析器建立 `0x193e9f4/0x193ea00` 等索引，没有直接改指针或 ready 字段。此种子是既有模拟输入，**不能作为当前实机校准数据**。

异常报告同时修复 DFSR 分类：转换异常／权限异常／外部数据异常分开，避免把所有 Data Abort 都称为未实现 MMIO。对应失败前复现保存在 `fault-classification-before.log`。

## AP 地址窗口与通知：已定位，尚未接线

固定归档内原厂 `pcie-if.ko` 的两个初始化函数提供以下地址契约：

- `.text+0x7b0` 计算 `((0x201fc + slot) << 17)`，四槽依次为 `0x403f80000`、`0x403fa0000`、`0x403fc0000`、`0x403fe0000`，每槽跨度 `0x20000`，再调用 `arch_phys_to_va`。
- `.text+0x1f90` 使用同一基址，建立 `+0x2004`、`+0x2020`、`+0x3ce8` 等队列地址。
- 原厂 CP `0xbad6fe` 使用低地址 `0x03f80000` 开始的槽位，并在64位 DMA 地址高字中加入 `8`。

**尚未证明带高位8的地址与两端物理地址之间的完整 iATU／PCIe 转换。不能把它直接映射为 CP 本地 RAM 别名，也不能因为槽位低位相同就宣称 AP 已连接。** 本轮没有开放这一高地址白名单，未知／未连接的 DMA 地址继续 abort。

通知的两端软件证据：

| 通道 | 原厂 AP | 原厂 CP | 判定 |
| --- | --- | --- | --- |
| 0 | `pcieif_set_interrupt` 翻转 GPIO18 bit9；恢复初始化读取 GPIO17 bit4；注册 IRQ92 | 输出 GPIO18 bit3；启动读取 GPIO17 bit2；注册 INTID290，进入 `bad20d` | 可推导一组候选对应关系，尚缺完整控制器和真实对端运行核验 |
| 1 | 翻转 GPIO18 bit8，注册 IRQ91 | 输出 GPIO18 bit2；注册 INTID289，进入 `bad225` | 输入位与边沿配置仍须继续核实，未自动生成通知 |

CP `0x5436e0` 在收到实际条件后才设置 `0x193ec10` 并唤醒等待者。最新快照该值仍为0。没有直接设置它，也没有宿主自动回翻 GPIO。

另从固定模拟归档的 `mini_ldr.bin` 参数取得 CP 控制器基址 `0xf6400000`、PHY 基址 `0xf11c0000`；AP 设备树的控制器是 `0xf7000000`。不能把 AP 同族驱动的控制器地址照搬到 CP。提取材料及摘要在 `build/cp-bridge-h52ped55/receipt.json`；其加载器本身未执行，BAR／iATU 初始化仍未完整复现。

## 实际验证及复现

本轮最终隔离 QEMU：

`0bb6a76974b71900aa404cd57ca3e7544495678fe9f5fe54c99832a6c79ec075`

| 验证 | 现场 | 结果 |
| --- | --- | --- |
| 原厂 CP 四核原入口 | `runs/native-cp-boot-dannvruc/` | 备份索引由原程序建立，首异常读 PLL0 `0xf1388100`；QMP退出0；未提交 AP 请求 |
| 独立 ARM 客体 | `runs/native-cp-edma-contract-9eur1ah5/` | 五路空总线 NACK／TX_ABRT及IRQ通过；16次直接搬运＋2段链表，共1088字节逐字节一致，17次IRQ403核对；高地址仍abort；QMP退出0 |
| 宿主同模型、ASan／UBSan与启动／媒体收尾回归 | `logs/native-cp-scu-20261022/regression.json` | 6组共27项通过；包括时钟复位控制状态、未知偏移拒绝、DFS请求位保持、备份身份拒绝、异常分类和源码身份门槛 |
| 默认运行输入及依赖 | `logs/native-cp-scu-20261022/input-verification.json` | 按默认清单再次校验；默认交付 QEMU、内核、归档、设备树、库未替换 |

独立 ARM 客体明确记录 `CP_loaded=false`、`AP_connected=false`，不能把其外设验收当作原厂 CP 已消费消息。时钟关闭／保持复位的负向门槛由宿主同模型测试核对；ARM 客体验证的是原厂式解锁后 MMIO、NACK 和 IRQ，不包含一次受控的关时钟总线异常验收。观察到初始化入口首次翻译，也不等于函数已返回或所有任务已就绪。

```sh
.venv/bin/python -B tools/cp_native_probe.py \
  --candidate build/cp-native-xdlzcywd --boot-trace --boot-detail \
  --with-tomco --with-backup --without-watchdog \
  --cp-qemu build/cp-qemu-dknqffld --observe-ms 2000
.venv/bin/python -B tools/cp_edma_probe.py --cp-qemu build/cp-qemu-dknqffld
```

接续顺序：取得有来源的 PLL0 初始配置与锁定条件；复现 CP 加载器的地址窗口设置；连接 AP 实际内存和输出驱动的 GPIO 通知；随后提交已捕获的原厂初始化及通知开启请求。只有 CP 原消费路径和原生产路径生成完整字节，并经 AP 原接收器解析，才计入 `0x2040` 完成。

本轮只修改隔离模拟源码、测试和研究入口，未接触相机、USB、SD卡或原始分区镜像；原厂 CP 字节保持原摘要，默认模拟器未切换。
