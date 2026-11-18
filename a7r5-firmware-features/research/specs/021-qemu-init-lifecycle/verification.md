# QEMU 长空闲与 E4 初始化验证

候选状态为 **部分通过**。QEMU 中长空闲进入原厂关机时的空指针崩溃已修复。正常启动后的 E4 初始化仍阻塞。AP、CP、两份图标资源及正式十二款 BIN 与 020 的文件摘要一致。客体 CPIO 逐项比对只发现 `simulation/menu-observe-a7r5-baseline.so` 变化。

## 长空闲崩溃

修复前在原厂 ST 页持续空闲。原厂收到关机因子 `0x11`，查找拍摄任务 `0x4d8` 得到空指针，随后在 `AP+0x34e620c` 读取对象偏移 `0x3cc` 时崩溃。现场未切入自定义 Tab。已确认空指针触发条件，关机因子的产生条件仍待查证。

修复限定于 QEMU 的观察库。启用选项后，观察库先核对固定 AP 的调用指令与函数头。仅当返回地址为原厂关机关联的 `AP+0x2771884` 且任务指针为空时结束该次释放。任务存在或其他调用点继续执行原函数。

| 运行 | 结果 |
| --- | --- |
| `native-native12-410-jyl5_ru6` | 原厂 ST 空闲，查找返回空，原厂进程发生 SIGSEGV。 |
| `native-native12-410-9b_p3p8n` | 90 秒无按键。相同关机因子和空任务均出现，原厂关机页 `0x316` 绘制并返回，客体输出黑帧。Qt、AP 和 CP 侧车退出码均为 0。 |
| `native-native12-410-uom3h0yv` | Qt 107 次操作及 107 组原帧与 PNG 通过。遍历十二款，验证八项工作值、重进保留、重置及四轮原厂菜单往返。 |

修复后的运行由 QMP 正常结束。本轮证据覆盖原关机崩溃位置和关机页，完整虚拟断电与重启仍待验证。四次短空闲观察期间无按键。首款切换请求由状态 1 变为状态 5，标题自动重绘为「切换未完成」，实际选择仍为 0。八项调节证据属于菜单工作值。

## E4 初始化

1. 实际 AP 串口与只读内存均确认原生任务 `0x32` 进入后未返回。该任务占用 E4 所在串行队列。两轮长空闲运行捕获的 `0x4063` 初始化请求均为 2400 字节，原字节 SHA-256 为 `b3a5829f8751d224b49b64c3fa3ee7efce1aa1683d6877c0682144e0ce4702b2`。
2. 用原 CP 的收包窗口 `0x496018..0x49606e` 回放 AP 的 `0x4073 ON`。原代码产生 12 字节短回执 `010073400400008000f00000`，并向 `0x90040193` 发送内部 `0xd018`。重放同一 `0xd018` 到成像端原始收包窗口后，原代码设置待处理状态。此时成像上下文 `+0x2d4` 为零，未产生后续消息。静态核对显示 `0x4406dc` 需要它等于 1，`0x440f1c` 在收到另一条内部 `0xd013` 时建立此条件。
3. 原 CP 的 `0x33cd7c` 是通知生产函数，`0xaef330` 根据通知模式调用它。函数遍历原生参数表，整体通知路径向 `0x80020002` 发送 `0x6c8` 字节的 `0x2040`。隔离执行时，准备子上下文的一处原生 getter 在 `0x88e454` 读取未初始化的对象；真实成像端状态及调度仍需建立。
4. 回放实际 `0x4063` 时，执行原生上下文绑定 `0xafd2da` 可越过早期空指针。原 CP 随后发送内部 `0xd003` 和 `0xd006`。之后 `0xadf9e4` 以任务编号 10 进入原生调度函数，因隔离环境未建立每核调度上下文，在 `0x5bd770` 读取地址 `0x40` 停止。后续仍需通过真正的原生任务和消息传输补足前置条件。

CP 指令探针使用隔离 CPU 执行环境及显式 OSAL 消息、信号量接口，仅用于定位依赖。短回执和内部消息由原 CP 指令生成。没有把探针接入 AP 的通知队列。旧版菜单隔离入口在当前整合版打开创意外观时也会触发 `0x32`，复验见 `native-native12-410-_pq813m6/console.log`。

完整 E4 验收需要原 CP 产生 `0x2040`、原 AP 消费它并从 `0x32` 返回，再复验十二款的 E4 应用与状态。QEMU 当前证据停在这一步之前，成像未验收。

## 复验证据

- [摘要、客体差异和原帧摘要](proof.json)
- [原 CP 收包及延迟路径](cp-native-notify.log)
- [原 CP 初始化请求回放](cp-native-init.log)
- [原 CP 通知所需子上下文](cp-native-producer.log)
- [测试前原厂 ST](../../../a7r5-qemu/runs/native-native12-410-9b_p3p8n/research-020-ENTER.png)
- [原厂关机黑帧](../../../a7r5-qemu/runs/native-native12-410-9b_p3p8n/research-021-IDLE_SOAK.png)
- [十二款列表中的 ASTIA](../../../a7r5-qemu/runs/native-native12-410-uom3h0yv/research-023-DOWN.png)
- [无按键自动刷新的失败提示](../../../a7r5-qemu/runs/native-native12-410-uom3h0yv/research-055-IDLE_LONG.png)
- [八项工作值的客体截图](../../../a7r5-qemu/runs/native-native12-410-uom3h0yv/research-083-UP.png)

运行入口为 `a7r5-qemu/experiments/native24-init-lifecycle/run_validation.py` 的 `soak` 和 `menu`。在 `a7r5-qemu` 内使用 `PYTHONPATH=tools QT_QPA_PLATFORM=offscreen .venv/bin/python -B`，传入 `build/native24-init-lifecycle-guard-20261104-01/manifest.json` 和新日志路径。对照构建为 `build/native24-init-lifecycle-observe-20261104-01/manifest.json`。两份清单的固定身份测试通过。本轮未连接相机、未操作实物介质、未生成升级包。
