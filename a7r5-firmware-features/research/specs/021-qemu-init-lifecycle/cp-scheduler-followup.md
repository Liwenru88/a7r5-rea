# E4 原生 CP 调度续查

本轮以 020 固定 AP、CP 和正式十二款 BIN 做离线验证。CP 镜像 SHA-256 为 `35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300`。补丁仅进入独立四核 QEMU 实验板。AP、CP、配方文件和默认清单均未更换。

最初使用既有 PLL0 模型从 CP 原入口启动，首异常为 `0xf1388078`。原 `0xb3cb46` 通过 CLR 别名写位14，之后 `0xb3ceee` 通过 SET 别名访问其他位。实验板补齐原指令中确认的门控位及读改写配置。CP 已越过 PLL、`0xf54005d4` 命令组和多段 `0xf541` 处理配置。模型只保存已核对的字段和返回相应读回值，未知位或偏移继续返回总线错误。保留固定 TOMCO、同客体的模拟备份，以及既有仅用于虚拟板的 `wdt_on=0` 配置。

四核客体读回原生配置组 2、四个每核调度上下文，以及跨域回调 `0x1164434`。AP 对端仍未连通，参数根 `0x165d758` 首字仍为零。启动轨迹未见原厂 CP 收包、成像端收包或 `0x2040` 生成入口。原厂文件内容以及 AP 的 E4 完成判断均保留。

最新四核现场运行至 `0xb59f1e`，读取 `0xf54101bc` 时触发数据异常。此前本次客体未执行这一组寄存器的写入路径。原 `0xb59f14` 同时读取 `0xf54101b8`，随后 `0xb584e8` 使用选择字段决定是否进入频率计算和后继服务请求。已查到 CP 内的运行时配置表，也扫描了固定客体里的 `mini_ldr.bin` 与 `loader_spi.bin` 的直接地址引用，尚无证据能把运行时表中的某个档位当作当前启动条件下的初始值。实验板因此保留拒绝。QMP 退出码为 0。[四核运行收据](../../../a7r5-qemu/runs/native-native24-cp-boot-4x7rno7l/result.json) · [原始启动轨迹](../../../a7r5-qemu/runs/native-native24-cp-boot-4x7rno7l/instruction-trace.log)

将真实 QEMU 的只读调度内存用于隔离 CPU 回放。按原 `0xafcb70` 所在初始化路径核对参数根 `0x164eef0`，通过原函数绑定上下文，并用实际捕获的 2400 字节 `0x4063` 请求执行原 CP 指令。原 `0x5bd744` 接收任务号 10，在原调用返回点 `0xadf9e8` 观察到返回值 0。后续也执行了原队列写入点 `0x5c3820`。补入 TOMCO 中原日志和调度监控的只读快照后，回放继续到原 `0x5e5f08` 读取 GIC CPU 接口 `0xf13a2004`。此隔离探针使用显式 OSAL 消息夹具，尚未完成原请求处理或产生参数通知。未替换原生调度返回或写入 AP/CP 就绪位。[任务激活和后续 GIC 访问记录](cp-native-rtos-final-snapshot.log)

独立 Qt 对照保持当前菜单客体。浏览至 CLASSIC CHROME 后连续 5 秒没有输入，后台状态从 1 变为 5，标题自动重绘为「切换未完成」，已应用编号始终为 0。27 组原帧与 PNG 逐字节转换匹配，Qt 工作进程、AP QMP、CP 侧车均退出 0。此结果验证了失败提示的自动刷新。十二款切换应用、实际预览与八项调参生效尚无通过证据。[Qt 对照记录](../../../a7r5-qemu/runs/native-native12-410-hoj1geay/e4-blocker.json) · [客体截图](../../../a7r5-qemu/runs/native-native12-410-hoj1geay/research-025-IDLE_LONG.png)

在 `a7r5-qemu` 中可复查四核原入口。

```sh
PYTHONPATH=tools .venv/bin/python -B experiments/native24-init-lifecycle/cp_boot.py \
  --manifest build/native24-init-lifecycle-guard-20261104-01/manifest.json \
  --cp-qemu build/cp-qemu-y2ysz5n1 --dump-task-ram
```

收据中的 `boot_observation_only` 表示完成了采样。完整验收仍需实际 AP 对端、原 CP 的 `0x2040` 原始包、原 AP 消费后的 `0x32` 返回，以及十二款应用和调参回读。全程没有连接相机。

## 续查 0xf54101bc 的初态与 AP／CP 地址

原厂初始化 `0x6a1a42` 先经 `0xb59f14` 读取 `0xf54101bc` 和 `0xf54101b8`，再使用模式对应的 `0x10abff8` 表项，经 `0xb59e8a` 写回这组寄存器。写回表无法解释此前第一次读取的初值。另一路 `0x1a05fa` 使用 `0xcd3930` 的运行时表。表项 4、0、6、2 对应模式 0、1、2、3，第二字段都为 `0x34bc0`。对候选归档中 AArch64 的 `mini_ldr.bin`、`loader_spi.bin` 检查了字面量及构造地址的立即数，对 `cpImg.dat` 检查了字面量，未发现这两个寄存器或其 `0xf5410000` 基址的直接引用。间接地址、前级配置和芯片复位值仍未确定。

独立实验板按原指令建模两寄存器的可写掩码，并补齐后继配置函数 `0xb5e28c`、`0xb5e3a2`、`0xb59512` 的读改写字段。新增 `--clock-mode` 仅用于选取运行时表中的实验输入，由 QEMU loader 在四核执行前显式写入两寄存器。没有指定档位时，未初始化读仍会拒绝。模式 3 会进入 `0x510b2c`，在 `0x510b94` 读取 `0xf5411480`，其后还要读取 `0xf5411484/88`。该分支依赖采样寄存器，尚无可支持的值，首异常发生在后继消息提交之前。

| 四核 QEMU 输入 | 首个数据异常 | 运行收据 |
| --- | --- | --- |
| 无档位 | `0xf54101bc`，保持拒绝未知初态 | [默认](../../../a7r5-qemu/runs/native-native24-cp-boot-myfqn08s/result.json) |
| 模式 0 | `0xf5410910`，原 `0xb5d4de` 读改写 | [模式 0](../../../a7r5-qemu/runs/native-native24-cp-boot-c8i1nyk_/result.json) |
| 模式 1 | `0xf5410910` | [模式 1](../../../a7r5-qemu/runs/native-native24-cp-boot-lp0qd038/result.json) |
| 模式 2 | `0xf5410910` | [模式 2](../../../a7r5-qemu/runs/native-native24-cp-boot-tuez2c5i/result.json) |
| 模式 3 | `0xf5411480`，原频率采样分支 | [模式 3](../../../a7r5-qemu/runs/native-native24-cp-boot-b804e6iv/result.json) |

五次 QMP 退出码均为 0，原厂跨域回调均为 `0x1164434`，`ap_peer_ready` 和成像参数根首字均为 0。隔离板 SHA-256 为 `fea8fb5f968f6a504cb0ac08d439952d11f941fb134dbc77d61a1e338519c528`。固定候选清单的五份文件校验通过。宿主时钟契约通过 ASan／UBSan，eDMA、请求捕获、启动探针共 9 项通过。快照和矩阵页表另有 5 项通过，另两项因默认输入文件及历史现场缺失而无法执行。

传输侧补充核对了三个不同的地址域。

- 原 AP `pcie-if.ko` 在 `.text+0x7b0` 将 `0x403f80000` 起的四槽经 `arch_phys_to_va` 转为本地地址，并在槽内 `+0x3ce0/3ce4` 初始化状态。固定原厂设备树把该地址置于 `/memory@400000000`。CP `0xbad6fe` 在本地 `0x03f80000` 起的四槽初始化 `+0x1ce0/1ce4`，同时构造高字为 8 的独立 DMA 地址。
- 两个 AArch64 加载器的 CPU 页表配置都把 `0x400000000`、`0x800000000` 开头的区域列为独立地址范围。该表由 `mini_ldr.bin+0x1a8` 的 CPU 页表构造程序消费，未提供 PCIe 入站或出站地址转换。另从 `mini_ldr.bin+0x3d28` 找到端点 BAR 配置调用，可沿 `+0x14fc` 追踪 DBI 写入，仍需确认调用参数和 AP 入站窗口。
- 归档中的原 `pci_ep_cp.ko` 调用原厂 `pcie_root_ctrl`，并在 PCI 设备使能后调用 `pcidma_connect`。本次 AP 客体设备树为 `pci-host-ecam-generic`。现有 CP 模型只接受本地 DMA，仍拒绝高字为 8 的地址。两端尚未接线。

复验时可在上述命令追加 `--clock-mode 0` 到 `--clock-mode 3`。十二款切换、预览和八项调参的验收仍以原生 CP 生成 `0x2040` 且原 AP 消费并结束 E4 为前提，本次未产生成功截图。改动仅进入隔离 QEMU 启动研究环境，未连接相机。
