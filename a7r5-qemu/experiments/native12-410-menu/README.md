# 4.10 私有菜单及十二配置离线验证

使用当前整合AP/CP和冻结的`R5NATIVE.BIN`。不连接相机、USB、SSH或真实存储卡，不启用设备直通或TCP。

## 运行

在`a7r5-qemu`目录使用本项目`.venv/bin/python`。全部输出使用新目录，默认`runtime/manifest.json`保持。

```sh
.venv/bin/python -B experiments/native12-410-menu/environment.py --output build/native12-410-base-new
.venv/bin/python -B experiments/native12-410-menu/build_loading.py --source build/native12-410-base-new/manifest.json --output build/native12-410-loading-new
.venv/bin/python -B experiments/native12-410-menu/qt_research.py --manifest build/native12-410-loading-new/manifest.json
```

Qt研究入口接受标准输入的固定按键名，每行一项，实际执行`QTest.mouseClick → QPushButton.clicked → worker`。最后使用`STOP`正常退出。终端必须保持打开；批量控制须分配TTY。

拒绝路径在新客体中执行，不与正在运行的AP菜单客体并行：

```sh
.venv/bin/python -B experiments/native12-410-menu/probe_menu.py --manifest build/native12-410-loading-new/manifest.json --scenario invalid-bin
.venv/bin/python -B experiments/native12-410-menu/probe_menu.py --manifest build/native12-410-loading-new/manifest.json --scenario bad-ack
```

`invalid-bin`仅在本次客体中改变SD文件的一个字节；`bad-ack`记录真实CP回执后，仅对交付AP的容量回执CRC注入错误。固定宿主材料与原固件不改写。

```sh
.venv/bin/python -B -m unittest discover -s experiments/native12-410-menu -p 'test_*.py' -v
.venv/bin/python -B experiments/native12-410-menu/verify_loading.py --run runs/本次目录 --manifest build/native12-410-loading-new/manifest.json
.venv/bin/python -B experiments/native12-410-menu/verify_run.py --run runs/本次Qt目录
```

有效主流程的`verify_loading.py`可追加`--receiver-regression build/新的CP检查目录`，检查损坏探测、损坏PUT和已封存配置复用。

## 模拟边界与证据

- AP文件中的字体修复来自`native12-combined/menu-font.c`及`menu_font.py`，以完整前像和原厂`libObj.so`摘要限定；上游源码、旧DAT保持。客体启动保留`/tmp/images`原始字体字节。
- 软件SD只提供`A:/R5NATIVE.BIN`只读接口；原AP冷启动线程执行扫描通知、读取、解码、暂存、读回、重命名及名称发布。SD诊断日志写接口不在本适配范围。
- 内部存储为客体RAM块设备上的真实vfat，挂载名为`/dev/nflasha30`；生产代码的`mountinfo`、`fdinfo`和持久化门禁保留。内部文件使用客体MD5及长度回读，宿主材料使用SHA256固定。
- 独立ARM QEMU执行当前CP的原生接收器、参数验证、Gamma/网格封存和SELECT代码。OSAL消息及1MiB堆为明确服务替身；不启动完整CP/RTOS，不仿真ISP。
- AP请求经新增的64KiB客体保留内存送出，宿主仅用QMP `pmemsave`读取；真实CP回执经有界客体tmpfs文件回送，再进入原AP接收函数。没有直接写入可用位、名称表或成功状态。
- 状态文件来自只读生产状态采样。截图来自原厂应用的冻结帧；串口导出只剥离固定格式的观察日志，保留整帧FNV校验，并另逐像素比较RGBA4444与PNG。
- 名称及参数封存通过，不能替代原生E4刷新、持久化选择、实际颜色和成像验收。运行中发现E4没有完成时保留失败提示和状态，不提供虚假的完成回执。

最终来源、运行目录、截图和结论见`a7r5-firmware-features/specs/003-native12-menu-loading-fix/verification.md`。历史失败运行不改写。

## E4后续修复候选

现有目录名保留4.10历史名称。新候选明确以4.11为来源，使用独立AP菜单事件覆盖层；新AP未封入4.11 DAT。完整启动仍缺`0x4073 ON → 0x2040`成像状态通知，不能将菜单隔离验证作为完整启动通过。

```sh
.venv/bin/python -B experiments/native12-410-menu/build_loading.py --source build/native12-410-menu-20261102-01/manifest.json --output build/新的E4候选 --release411 --menu-event-fix
.venv/bin/python -B experiments/native12-410-menu/qt_research.py --manifest build/新的E4候选/manifest.json --menu-isolation
```

`--menu-isolation`只通过原厂MENU进入菜单，不确认触控引导或启动拍摄初始化；不写首次设置／E4完成字段。UPM通过原厂OSAL接口持有本次虚拟DEBUG频率锁，不伪造DFS硬件完成。

实际正例`runs/native-native12-410-uielh6z1`使用`build/native12-e4-411-event-fix-20261102-01/manifest.json`。Qt操作为：`LEFT LEFT DOWN DOWN DOWN RIGHT DOWN DOWN DOWN DOWN DOWN RIGHT DOWN DOWN ENTER`进入私有页，`DOWN`十二次、`UP`十二次、`ENTER STOP`。每行一项，末尾必须STOP。原操作回执和41客体帧保持。

独立故障运行增加`--scenario bad-select-ack`：同导航后`DOWN`七次，第二次slot7 SELECT回执只在交付时破坏CRC，随后`UP DOWN STOP`验证回退与重试。真实CP原回执与被破坏交付分别保留。

```sh
.venv/bin/python -B experiments/native12-410-menu/verify_loading.py --run runs/本次目录 --manifest build/新的E4候选/manifest.json
.venv/bin/python -B experiments/native12-410-menu/verify_e4.py --run runs/本次目录 --manifest build/新的E4候选/manifest.json
.venv/bin/python -B experiments/native12-410-menu/verify_e4.py --run runs/故障目录 --manifest build/新的E4候选/manifest.json --mode rollback
.venv/bin/python -B experiments/native12-410-menu/verify_run.py --run runs/本次目录 --isolated-control-only
```

有限审计只写`control-frame-audit.json`，明确`menu_lifecycle_verified=false`。默认完整`verify_run.py`继续要求四轮MENU往返；不能用有限审计替代。最终报告为`specs/004-native12-e4-apply-fix/verification.md`。
