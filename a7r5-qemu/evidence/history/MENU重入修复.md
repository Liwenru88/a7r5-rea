# macOS 原生环境的 MENU 重入修复

本修复仅用于离线原生模拟环境。原始镜像、Docker 客体与 Linux QEMU 保持原状；相机和 SD 卡没有接入。

## 原因与证据

旧启动入口在启动页面绘制返回后主动打开一次原厂菜单，但没有完成整个启动模式。实际日志中的顶层关闭路径是 `scr7001_1003 → rep_shooting → rep_boot`，当前页面落在 `0x355`。该状态没有正常的 MENU 重新进入行为。旧的 `0x316` 是 `scr0039_shutdown_presenter`，不能一概当作普通关闭态。

原生未修复会话 `runs/native-app-pqshfx16/` 已记录：初始菜单、第一次 MENU 后黑帧、第二次 MENU 仍为相同黑帧，QMP 正常退出。独立回归检查在“MENU 未重新打开同一真实菜单”处失败，见 `logs/native-menu-cycle-regression-before.log`。

在关闭态直接调用完整切换会先退出 `rep_boot_controller`。其 vtable 槽 `AppFw+0x58d3050` 指向 `+0x20c7bac`；RTTI 为 `19rep_boot_controller`。此退出路径会访问没有硬件后端的对象，失败调用链包括 `+0x20c8078 → +0x2549d44 → +0x2549ce4 → +0x34dae24`，最终对空对象偏移 `0x2a0` 加锁。失败候选 `native-app-e2l9r3cw`、`native-app-hobkdikr` 均保留，并已正常退出虚拟器。

## 修复范围

原生环境使用独立的 `native-macos/assets/active-guest.json` 选择客体；新的 initramfs 仅替换模拟观察库 `simulation/menu-observe-a7r5-baseline.so`。共享 Docker initramfs 与其库不改动。

新增桥接只在以下条件同时成立时工作：已成功创建过菜单、队列/来源/20 字节消息精确匹配、MENU 是新的按下、当前页面为已验证的 `0x355`。按下与释放由桥接消费一次，随后在原 UI 线程、绘制返回、没有进行页面构造或其他切换时，调用原厂菜单生命周期。

对于这一受控转换，只省略 `rep_boot_controller` 的未建模硬件清理。其他 boot 退出调用仍透传；构造、析构、菜单初始化、控件和绘制仍走原厂实现。未知页面、错误所有者或状态变化均拒绝额外调用，不覆盖模型全局状态，不跳过模型断言。

首次关闭后的正常原厂流程还包含触控操作说明 `scr7240_0001`（`0x1e9`）。原生启动阶段通过固定按键完成如下路径，并在每一步核对实际页面编号：

`菜单 0x2d6 → MENU → boot 0x355 → MENU → 菜单 0x2d6 → MENU → 触控说明 0x1e9 → ENTER → 拍摄信息页 0 → MENU → 菜单 0x2d6`

只有确认为该触控说明页面才发送 ENTER。页面不符、固件异常或超时即停止，不能自动确认未知弹窗。确认结果只在该次虚拟机 RAM 中；每次初始化记录在对应运行目录的 `native-initialization.json`。

完成该初始化后，反复 MENU 切换由原厂正常逻辑处理：`scr0132_0001 ↔ rep_menu / scr7001_1003`。界面可显示原厂拍摄信息与 NO CARD 标记，但没有 CMOS 视频或实际拍摄功能。

## 空闲暂停与恢复

后续窗口测试还发现独立路径：没有新按键时，固件在客体时间约 4,039 秒请求 shutdown，因硬件关机未模拟而异常。记录在 `native-app-pwolku2h`；它不作为成功验收会话。

原生后端现在在每次帧导出完成后使用 QMP `stop`，并核对 `query-status.running=false`；收到下一次固定命令时 `cont` 后再发送串口输入。定制 Sony 定时器使用 `QEMU_CLOCK_VIRTUAL`，空闲暂停不推进该时钟，避免窗口等待时间触发未模拟的自动关机。没有修改固件电源设置或压制 shutdown 请求。QMP 正常退出可以在暂停态完成。

`native-qmp-events.jsonl` 记录每次暂停和恢复；`native-runtime-state.json` 是最近一次状态快照。空闲等待与恢复证据见 `logs/native-reentry-idle-check.json`。这仍是按键后取帧的菜单研究环境，不是持续实时运行、带传感器视频的整机模拟。

## 使用与重建

继续使用 `启动A7R5原厂菜单-macOS原生.command`。启动页在受限初始化完成后才启用按钮。顶层 MENU 关闭菜单并显示原厂拍摄信息页，再次 MENU 打开菜单；子页 MENU 仍遵守原厂返回逻辑。

独立载荷构建入口为 `native-macos/tools/build-menu-reentry.py`。构建时复用已有 Linux 容器中的交叉编译器，只把产物写入原生目录；若容器原先停止，结束后恢复停止。运行时仍为 Mac 原生 QEMU，无需 Docker。

主要实现：`native-macos/guest-source/native-menu-reentry.inc`、`tools/native_vm.py`。状态与失败路径测试：`native-macos/tools/test-reentry-policy.c`、`native-macos/tools/test-native-initialization.py`。逐帧循环验收：`native-macos/tools/check-menu-cycles.py`。最终证据以 `logs/native-reentry-acceptance.json` 为准。

本修复不等于完整相机启动、关机或硬件模拟。省略的 boot 硬件清理不能用于真实相机；也不提供刷写、恢复分区、拍摄、录像或传感器支持。
