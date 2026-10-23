# 原厂 CP：PCIe 侧带、中断和 DMA 子集

后续进展见 [串行时钟、启动备份与 AP 对端边界](native-cp-clock-and-peer.md)：已越过 `0xf1388054`，当前首异常为 PLL0 配置读取 `0xf1388100`；AP窗口、通知及 `0x2040` 尚未完成。下文保留前批现场。

2026-10-22。`0xf11e0274` 的用途已从 Sony 公开驱动定位为 PCIe 侧带中断使能，已补入隔离实验板。原厂 CP 已越过原阻塞，实际注册跨域回调 `0x1164434`，随后在驱动初始化写 `0xf1388054` 时停止。

**AP 对端尚未连接，原厂 CP 尚未处理 `0x4063`／`0x4073`，尚未取得 CP 生成 `0x2040` 的证据。** 本轮完成的是寄存器定位和可执行 DMA 子集，不是完整 PCIe／CP／ISP。

## 已确认的地址和语义

| 地址 | 来源与结论 | 仍未证明 |
| --- | --- | --- |
| `0xf11c0000` | A7R5 固定设备树的 `phy_reg`，长度 `0x40000`；原厂 CP DMA 上下文 `0x11645f8` 也保存该值 | CP 板完整 PCIe 角色、训练与电源时序 |
| `0xf11e0274` | `phy_reg + 0x20000 + 0x274`，Sony 定义 `INTERRUPT0_ENABLE_OFF`；低16位为 `EDMA_INT` | 实机上电复位值、16位内部的方向/通道对应 |
| `0xf6780000` | CP 原入口运行时 `0x11645f4` 的值，作为 DMA 本体基址 | AP 对端地址转换窗口 |
| INTID403 | CP 原入口运行时 `0x11645f0 = 0x193`，原厂初始化启用该中断 | 完整侧带/MSI中断拓扑 |
| `0x0ca21e00` | `OSAL_UIPC_INIT` 原代码检查/初始化1 MiB消息日志；位于 TOMCO 的 `0x09000000..0x1fffffff` RAM 内 | 全部 TOMCO 内存范围与物理机一致性 |
| `0xf102e000`／`0xf102f000` | CP GPIO17/18；原通知代码读取方向和引脚、翻转输出 | AP 端 GPIO连线、边沿中断控制器 |
| `0xf1388054` | 原 `USER_TSK_DRV_INIT` 下调用 `0xbade7c`，按原时钟表向 SCU SET 别名写使能位；公开 `SCU_SET=4`、`CLKEN_SERIAL=5` 与偏移吻合 | 此后的外设及其真实时钟、复位和完成条件 |

Sony 公开内核版本固定到提交 `fa5c6f6aba58f675691e5adf291b155b76e6e93e`。其中 [pcie-designware.h](https://github.com/DavidBuchanan314/Sony-ILCE-7M4-Linux/blob/fa5c6f6aba58f675691e5adf291b155b76e6e93e/linux-kernel/drivers/pci/dwc/pcie-designware.h) 明确定义侧带偏移和 `EDMA_INT=0xffff`；[pcie-designware.c](https://github.com/DavidBuchanan314/Sony-ILCE-7M4-Linux/blob/fa5c6f6aba58f675691e5adf291b155b76e6e93e/linux-kernel/drivers/pci/dwc/pcie-designware.c) 的使能函数执行读改写，状态清除函数读状态后写回。

这是 ILCE-7M4 公开源中的同族控制器证据，不能单独替代 A7R5 身份验证。A7R5 自身 CP `0x544478..0x5444ba` 的地址、低16位读改写和两组 DMA 寄存器写入与之对应，才支持此次局部实现。DMA 通道与描述符布局另对照 [Linux v6.12 eDMA寄存器](https://github.com/torvalds/linux/blob/v6.12/drivers/dma/dw-edma/dw-edma-v0-regs.h) 及 [原驱动实现](https://github.com/torvalds/linux/blob/v6.12/drivers/dma/dw-edma/dw-edma-v0-core.c)，同时核对 CP 自身 `0xbade3e` 的直接模式/链表配置。

已下载23份公开来源文件并校验，来源与摘要见 `build/pcie-source-3vc0tnu4/receipt.json`。最初 GitHub 目录 API 返回403；随后通过只读 `git ls-remote` 固定提交，并从该提交重新比对先前3份文件；不是把浮动 main 当成固定版本。

## 实现内容与限制

`source/qemu/a7r5-cp-edma.h` 与 `a7r5-cp-boot.c` 只用于独立候选：

- 侧带使能 RW；只支持全部 EDMA 位开放/关闭，部分位写入拒绝，不猜测位序。不映射 LINK_UP、PHY ready 或其他未知寄存器。
- 双向八通道 unroll 寄存器，直接搬运的长度、64位源/目的地址、控制值，以及中断状态、屏蔽、写1清除。
- 本地链表的24字节数据项、链接项、CB/TCB生产/消费位和本地中断。生产位不匹配时等待，不能凭 doorbell 产生完成。
- 搬运实际读取并写入客体 RAM；未知/未连接 AP 地址、非法模式、空长度、过大长度及损坏链表产生 abort。失败状态为 halted，不伪装为 DMA_COMPLETE。
- 单次最多16 MiB、最多256项，防止错误固件或循环链表占用宿主。链表可能在后续项失败前已写入前面的有效片段，不回滚；已产生的完成位和 abort 位分别按 W1C 保留。
- 经 IRQ403 连接 GIC；仅在真实搬运完成或报告错误、且相应中断未屏蔽时置位。未连接 AP 的 GPIO 输入明确保持低，没有自动应答翻转。

当前 DMA 地址白名单仅为低128 MiB CP RAM；没有实现 AP peer、iATU、远端 MSI、暂停/停止语义、异步生产者轮询、完整冷/热复位、迁移或周期准确时序。既有定时器仍使用实验接线，全部时钟和中断等价性未证。新增 TOMCO 工作 RAM 供原厂 CPU 访问，不表示已开放全部 DMA 地址。虚拟初态采用使能关闭、无任务、无中断；这不是实机 POR 测量值。

构建器和运行入口同时固定模型头文件摘要，不能只核对板级 `.c`。旧源码、二进制和收据按两者身份保存到历史目录。默认交付 QEMU 与清单未替换。

## 实际执行证据

最终实验 QEMU SHA-256：

`f46652dfe77cd451346bb67cdea9529e7e71e0cbb0da51781e1ec9d157d8e123`

| 验证 | 现场 | 结果及证明范围 |
| --- | --- | --- |
| 宿主同代码契约，ASan/UBSan | `logs/native-cp-pcie-20261022/edma-final-tests.log` | 2项测试通过；覆盖实际字节、双向八通道、CB/TCB、无新生产位、循环链表、部分完成后失败、未知地址/模式，以及模型摘要变化拒绝执行 |
| 独立 ARM 客体 | `runs/native-cp-edma-contract-tjevk7z3/` | 16次直接搬运＋2段链表，共1088字节逐字节一致；17次 IRQ403 pending 核对；屏蔽/W1C、无新生产位和高地址 abort 通过；QMP退出0 |
| 原厂 CP 原入口、四核 | `runs/native-cp-boot-rbmr5hqx/` | 原厂通信回调实际成为 `0x1164434`；执行至 USER_TSK_DRV_INIT；首异常写 `0xf1388054`，QMP退出0；AP请求数仍为0 |
| 启动快照、请求捕获、媒体与收尾回归 | `logs/native-cp-pcie-20261022/regression.log` | 23项通过，复用本批次同代码状态的定向证据；未运行无关全套测试 |
| 固定输入与公开源码身份 | `logs/native-cp-pcie-20261022/input-verification.json` | 默认 QEMU、内核、归档、设备树、库及23份下载文件校验通过 |

独立 ARM 客体使用 `source/guest/cp-edma-start.S`／`cp-edma-contract.c`，**没有加载 CP**，结果明确记录 `CP_loaded=false`。它证明的是外设模型和 QEMU 包装接线，不是原厂 CP 消息处理。原厂 CP 的运行记录单列，不能把二者合并为完整通信验收。

原厂 CP 使用的唯一模拟输入变化仍是上一轮明确的 TOMCO `wdt_on=0`；CP 文件原摘要不变。初始化表入口的首次指令翻译不单独作为完成证明；此次跨域回调实际值提供了注册旁证，也仍不代表应用已经可用。

保留的失败证据包括：`native-cp-boot-hsx7nq7t`（RAM注册所有者不符合 QEMU API，CP执行前宿主退出）、`native-cp-edma-contract-21xvtjf8`（测试入口未停驻辅助核，四核竞争）。修复后重新验证，不删除旧记录，也不把旧失败计作通过。

复现命令：

```sh
.venv/bin/python -B tests/test-cp-edma.py -v
.venv/bin/python -B tools/build-cp-qemu.py --resume build/cp-qemu-dknqffld
.venv/bin/python -B tools/cp_edma_probe.py --cp-qemu build/cp-qemu-dknqffld
.venv/bin/python -B tools/cp_native_probe.py \
  --candidate build/cp-native-xdlzcywd --boot-trace --boot-detail \
  --with-tomco --without-watchdog --cp-qemu build/cp-qemu-dknqffld --observe-ms 2000
```

## 尚未完成的主目标

当前实际链路是：原始 TOMCO解析 → PCIDMA初始化 → OSAL/UIPC初始化 → PCIe跨域回调注册 → 后续驱动初始化异常。AP／CP之间没有共享地址窗口和真实通知连线，原厂 CP 应用任务也尚未完整启动。

下一步须把 SCU 时钟/后继外设依赖与 PCIe peer、iATU、GPIO边沿和队列所有权逐项建立。只有原厂 AP 请求通过实际搬运进入原厂 CP 消费路径，并由 CP 原生产路径返回 ACK及`0x2040`原始字节，再经原厂 AP 解析，才算达到本次目标。不能通过全零 MMIO、固定 link-ready、手写成功回复、直接写回调/ready字段或直接调用处理器替代这条链路。

汇总：`logs/native-cp-pcie-20261022/summary.json`。本轮仅操作模拟环境，没有访问相机、USB、SD卡或原始分区镜像。
