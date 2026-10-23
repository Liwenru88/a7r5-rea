# 原厂 AP／CP 传输：启动输入与 PCIe／DMA 阻塞

后续进展见 [PCIe 侧带与 DMA 子集](native-cp-pcie.md)：已定位 `0xf11e0274`，原厂 CP 实际注册跨域回调，当前停在 `0xf1388054`；AP请求及`0x2040`仍未完成。下文保留上一轮现场及证据边界。

2026-10-22。本轮修复了隔离 CP 启动缺少 TOMCO 输入的问题，原厂解析器实际选中配置组 2，并进入原厂 `PCIDMA_INIT`。**AP 请求尚未送入 CP，CP 未生成 `0x2040`，ISP 成像仍未完成。** 没有添加成功 ACK、合成参数通知、ready 字段写入或软件 ISP。

## 运行结果

| 输入／现场 | 可观察结果 | 边界 |
| --- | --- | --- |
| 无 TOMCO，同一新版实验 QEMU，对照日志 `control-boot.log` | 配置组 0；UIPC／PCIe 初始化被原厂配置掩码排除；跨域回调为零 | 空闲不能作为服务就绪 |
| 原厂 TOMCO，`runs/native-cp-boot-y55zthbw/` | 原厂解析器设组 2；首个异常 `DFAR=0xf1388344`，位于看门狗初始化 | 此次旧观察器直到日志预算才暂停，原始异常风暴保留 |
| TOMCO 仅 `wdt_on=0`，最终 `runs/native-cp-boot-22_0t4y1/` | 原厂执行至 `PCIDMA_INIT`，首个异常为读 `0xf11e0274`；约 244ms 暂停，QMP 正常退出 0 | 中断／异常后续产生的 `0xf102f048` 不能替代首个故障定位 |

停机由宿主轮询异常日志触发，不能保证在第一条异常指令时同步暂停；最终仍记录后续异常。结果保持 `CP_RTOS_booted=false`、`ISP_pixels_verified=false`，不是完整启动或正常应用关机验收。

## 1. 原厂启动输入此前缺失

固定归档中的 `cp/tomco.txt`：686 字节，SHA-256：

`524bb8c841f29e609e7606d56e6d393023afa8e0d3f61acbce7f957572323115`

包含 `usrrtn_cfggrp=2`、`wdt_on=1`，以及中断、内存区域等配置。原始 CP `0x5e3740` 从 `0x100000` 比较 `[TOMCO]`，随后解析名称和值，经函数表调用配置处理器。`0x60b1c0` 处理 `usrrtn_cfggrp`，存入 `0x195e9dc`。

此前实验只加载 `cpapp-b.bin`，`0x100000` 为零，解析器直接返回，配置组保持 0。此次将原 TOMCO 加载到该地址，由原厂解析器处理，没有直接写组变量。

原厂初始化表在 `0xe7a948`，14 项，每项 20 字节。`0x60b3e8` 选择 `+0xc` 配置组掩码，`+0x10` 选择执行核，`0x60b7a4` 加载参数及函数并间接调用。部分条目：

| 名称 | 原函数 | 配置组掩码 |
| --- | --- | --- |
| TOPPERS_KERNEL | `0x5d85fc` | `0xffffffff` |
| PCIDMA_INIT | `0x5443ad`（Thumb） | `0xfffffffe` |
| OSAL_UIPC_INIT | `0x53a52d` | `0xfffffffe` |
| PCIEIF_INIT | `0x54193d` | `0xfffffffe` |
| USER_TSK_INIT2 | `0x151425` | `0xfffffffc` |

因此组 0 的“运行到空闲”恰好跳过了通信初始化。组 2 是否适合本实验无需猜测：它来自原始 TOMCO，运行时读回也是 2。

## 2. 看门狗和 PCI DMA 分别记录

原配置在 `0x609e18` 写 `0xf1388344` 时触发真实 Data Abort。为了继续分离通信依赖，另建模拟配置，只替换一个字节：`wdt_on=1` → `wdt_on=0`。原件同时留存；候选摘要为：

`662b6d82bff9a36d0b0c23ec56add6d009882bbf64a9163a8f57333e9e502fda`

这表示虚拟板明确不启用看门狗，不能声称看门狗建模完成，也不能据此证明真实机身启动等价。

随后原程序执行 `PCIDMA_INIT`，`0x544488` 从基址加 `0x20274` 读取，实际地址 `0xf11e0274`；紧接着原程序将低 16 位置一并写回。该 Sony 寄存器语义及复位值尚未确定，本轮保留未映射异常，未改成寄存器全零／全一占位。

同一初始化函数随后会写 DMA 基址的 `+0xc/+0x2c` 引擎使能、`+0x54/+0xa8` 中断屏蔽、`+0x58/+0xac` 中断清除、`+0x90/+0xc4` 链表错误设置。这组偏移与 [Linux v6.12 的 Synopsys DesignWare eDMA 原始寄存器定义](https://github.com/torvalds/linux/blob/v6.12/drivers/dma/dw-edma/dw-edma-v0-regs.h) 吻合。**这是对 DMA 寄存器家族的推断，不证明 Sony 扩展 `+0x20274` 或整条 PCIe 拓扑已还原。**

GIC 容量从实验 288 扩为 480，覆盖 CP `ARM_GICD` 配置值 `0x1d2` 和 TOMCO 中 IRQ 296／307；480 是按 32 对齐的容量选择，全部中断接线仍未验证。默认交付 QEMU 没有替换。

## 3. 两端传输路径与“返回 0”的陷阱

CP 原厂发送函数 `0x53bb54` 对跨域目标读取 `0x193eb08` 的回调表，并取表中第一个函数。`0xbaa6dc` 注册该表；原厂 `PCIEIF_INIT` `0x54193c` → `0xbacbd0`，传入表 `0x1164434`，再调用注册函数。当前运行时指针仍为零，初始化也未到达此路径。

缺少回调时，CP 会打印 `No snd_msg registered. Skip snd`，随后走返回 0 分支。原厂 AP `osal_uipc.ko` 的 `osal_snd_msg +0x180..0x204` 也存在缺少跨域回调后打印并返回 0 的路径。**函数返回成功不等于消息进入 CP，更不等于 CP 已处理。**

已从固定模拟归档只读提取 AP 模块到 `build/cp-transport-nt2duc98/`，各文件摘要见收据：

- `pcie-if.ko`：`pcieif_reg_public` → `osal_reg_public`；`pcieif_send_request` 排队，发送线程使用 DMA；`pcieif_dma_execute` 等待完成回调。
- `pcieif_set_interrupt` 通过 `gpio_get_data_bit`／`gpio_set_data_bit` 翻转通知位。因此不能仅接一个消息字节流就宣称唤醒及所有权已实现。
- `pci_ep_cp.ko` 导入 `pcidma_connect`、`pcie_root_ctrl`；端点／主端的完整角色和地址转换仍需结合连接函数与驱动继续核实。
- AP 内核发送代码和 CP 发送代码均减去 `0x18` 访问本地 OSAL 头，但 PCIe 发送对象另有结构及缓存维护，不能把本地链表头、用户态缓冲区和线协议直接混用。

当前没有把此前捕获的 2400 字节 `0x4063` 请求复制到未初始化队列，没有手写 CP ACK，没有直接调用通知处理器并将其当作完整 RTOS 传输。

## 工具、验证与保留边界

新增 `tools/cp_boot_state.py`：暂停后导出三段固定 RAM、四个独立核寄存器和定时器状态；只允许读操作，长度／核号不符拒绝生成验收收据，不覆盖已有现场。

新增 `tools/cp_transport_state.py`：固定 CP 摘要，解析真实初始化表和配置组，单列首个故障及未注册回调；即便回调非零也不宣称 AP 初始化处理或通知生成成功。

扩展 `tools/cp_native_probe.py`：TOMCO 固定身份、显式单字节模拟变体、完整但有界指令观察、遇 Data Abort 停止，原始日志及快照留存。观察模式的 CLI 退出 0 只表示观察和宿主收尾完成，应阅读结果中的阻塞状态。

`tests/test-cp-boot-state.py` 7 项，以及原生 CP 指令、请求捕获、媒体与失败收尾的 16 项，共 **23 项通过**。新增回归覆盖独立 CPU 选择、暂停门槛、短导出、身份损坏、配置掩码差异、首个异常保留，以及“回调非零仍不证明处理完成”。测试命令与输出在 `logs/native-cp-transport-20261022/`。

早期诊断的 QMP 物理读取 GIC 导致宿主模型 `gic_get_current_cpu` 崩溃；根因是主线程没有模型要求的 `current_cpu`，已移除该读取。随后发现每次 QMP 的 HMP 上下文独立，单独 `cpu n` 不会影响下一次连接；已改成每条寄存器请求明确带 `cpu-index` 并检查返回核号。旧失败现场和错误核号现场保留，不用于四核寄存器验收。

默认 `runtime/manifest.json` 对 QEMU、内核、归档、设备树、图形库及依赖的验证通过；原厂 CP 文件未改，默认 Qt 未替换。没有操作相机、USB 或 SD 卡。

## 后续完成条件

1. 结合 CP `PCIDMA_INIT`、AP PCIe／DMA 驱动，确定 `0xf11e0274` 的复位、掩码、地址转换和通知语义；保留未知访问失败，不批量映射占位外设。
2. 实现有实际字节搬运、范围检查及失败反馈的 DMA／传输模型；以原厂驱动注册回调、队列获取和唤醒为验收，不能用返回 0 放行。
3. 连接两端原厂消息生产者／消费者，保留来源、目标、长度、序号和释放规则，依次提交已捕获初始化与通知开启请求。
4. 必须从 CP 原厂处理与生产路径取得 ACK 和 `0x2040` 原始字节，再交给 AP 原厂解析器；只有入口轨迹或上下文变化不算完成。
5. 在此基础上推进原厂 DMM／stream／ISP。当前尚不能用 QEMU 验证实机滤镜画质。
