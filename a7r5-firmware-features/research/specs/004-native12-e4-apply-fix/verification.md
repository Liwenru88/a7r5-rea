# E4应用失败调查与验证记录

状态：`VERIFIED_CONTROL_ONLY_WITH_BLOCKERS`，任务整体仍为`IN_PROGRESS`。十二款及故障回退取得`PASS_MENU_ISOLATION`，完整启动／菜单生命周期仍未通过。没有连接相机、USB、SSH、真实SD卡或主机原始分区。固定4.10／4.11包、默认runtime及上游源码保持。

全部新证据和截图归档在[研究记录](../../native24-combined/dependencies/native12-combined/verification/2026-11-02-e4-control/README.md)。新AP是独立修复候选，未打包进现有4.11升级包。

## 已取得的证据

所有命令在`a7r5-qemu`目录使用该项目`.venv/bin/python -B`执行。

| 检查 | 实际结果 | 证据 |
|---|---|---|
| 原E4失败定位 | 队列0被C3触控任务占用；对象排队而没有原体执行 | `runs/native-native12-410-mwvmp81m`，`native-diagnostic.log`、`console.log` |
| 原E4首次执行 | 严格触控服务后原体入口／九分派／返回，生产done=1 | `runs/native-native12-410-z375875r` |
| 原UPM轮询阻塞 | FULL→SLOW、MMIO 0xf1388f50、中断关闭；串口失步后只QMP采样并退出 | `runs/native-native12-410-5xrcv888/serial-failure-registers.json` |
| 原厂固定频率约束 | LOCK_MODE DEBUG回执0，原驱动打印FULL状态及DEBUG锁 | `runs/native-native12-410-g3c3o_gn/setup-13.log` |
| 十二款控制链 | 1..12、11..0共24次提交；每次两CP确认、指定原E4九分派、原选择文件CRC与AP成功状态相符 | `runs/native-native12-410-uielh6z1/e4-audit.json` |
| 重复已提交选择 | 保持关闭，无额外CP消息或新E4序号 | 同上，动作38／39 |
| 真实配置加载 | 29552字节，12 PUT及SEAL mask=0xFFF；CP堆只分配一次 | 同运行`loading-audit.json`、`cp/messages.json` |
| 原帧与Qt | 41客体原帧及PNG逐像素一致，41次QTest点击含STOP，三侧退出0 | 同运行`control-frame-audit.json`；只授予有限控制链验证 |
| 错误第二次SELECT回执 | slot7的真实CP回执只在交付AP时损坏CRC；AP状态稳定失败3、CP／文件／AP恢复6；手动选择6成功，再选7成功 | `runs/native-native12-410-32tf4to3/e4-audit.json`、25原帧及Qt点击 |
| 固件菜单值刷新回归 | 修复前实际CPU回放2失败／3通过；新覆盖层和原UI相关回放9项通过，3.66秒 | `logs/native12-e4-event-20261102/firmware-regression.xml`；修复前原UI追踪见fcqop6ew |
| CP拒绝／复用 | 坏容量探测、坏PUT拒绝；十二项封存，相同BEGIN复用，堆保持1次 | `build/native12-e4-411-cp-regression-20261102-01/verification.json` |
| 定向合同 | 10项通过，1.635秒；包含新增覆盖层完整前像／所有权及转发、动态上下文、非法请求、交付失败、字体、身份、采样竞争 | `logs/native12-e4-event-20261102/qemu-contracts.log` |

最终清单为`build/native12-e4-411-event-fix-20261102-01/manifest.json`。新AP SHA256 `65e33ba2075bb59f65a97e6cec550bd8b1d54bac040fe28427cd3922924ffde0`，由4.11包内字体AP `a1e6a6472e200e5554426d54b73e1b031dfb2a75251a1854b124e223a08b68c5`独立派生；CP保持`bb8eeaaeb9d13a4687605de6e01ccbe4adc500f595d2f8dbfe886eedd8a643d0`。组件身份由实际运行输入与构建清单交叉核对，不以版本字符串代替摘要。旧AP的首次成功隔离运行okygjowt保持为中间证据，不冒称包含菜单事件修复。

## 根因与最小修复

E4不执行首先由公共队列0中缺失触控回复造成。补齐受限触控、成像锁和输出服务，并通过原UPM接口保持虚拟固定频率后，原E4九次分派与返回可执行。继续初始化则涉及尚未实现的完整成像状态，因此另以原厂MENU输入进入明确的菜单隔离场景验证滤镜控制链。

故障注入进一步发现实际菜单缺陷：`fcqop6ew/native-ui-trace.log`记录导航失败后命令为3，随后原厂值刷新事件`0x20f0001`使其变成1并重发目标。独立104字节AP覆盖层只在私有D9所有权匹配时消费该通知，其他页面／事件及原dispatch原体保持。实际AArch64回放先复现原问题，新AP回放及真实Qt故障场景均通过。没有修改生产CP/E4成功门禁、超时或选择保存条件。

每次E4保留原函数执行；只在独立客体RAM中安装严格16字节前像校验的观察跳板。九个原生参数消息的提交不等于CP/ISP消费完成。CP侧车执行真实私有协议、配置校验、封存和SELECT，OSAL／堆及SD／内部vfat为明确虚拟服务；没有ISP像素、完整CP/RTOS、实际色彩或实机安装验收。

## 仍未通过

1. 完整拍摄初始化：最终新AP复测`runs/native-native12-410-v7paf2xa`仍在开启0x4073通知时触发原厂断言。当前仅支持关闭通知，尚未提供原消费者需要的0x2040状态。客体已正常QMP退出，失败现场保留；没有在异常客体继续按键。
2. 菜单生命周期：隔离场景退出滤镜页会进入未确认的原厂触控引导；MENU不构成四轮顶层往返。不能复用旧候选的四轮证据冒称当前通过。严格完整审计门禁保持，有限原帧审计另写`control-frame-audit.json`并明确`menu_lifecycle_verified=false`。
3. 仍未验证CP/ISP完整参数消费、EVF/JPG色彩、声音与照片标记叠加、真实持久化／掉电、机身准入及安装。Portra400左简称裁切沿用已知问题。

## 保留的失败现场

- 原故障运行1mv2jh83：旧AP的故障页显示失败，但值刷新引发额外请求；不计作回退通过。追踪运行fcqop6ew进一步定位事件根因，修复后32tf4to3取得完整终态。
- 首次隔离全切换gbugqeq8：十二项已提交，但只读采样落在观察器写入窗口，worker退出1。修复为有界重采样后新正例正常退出。
- UI观察候选0zedr9l2：高频串口观察插入帧导出，严格Base64校验拒绝，QMP正常退出；改为过滤周期事件并仅写客体日志，后续追踪成功。没有降低原帧校验。

## 复现

QEMU项目目录中的实际入口：

```sh
.venv/bin/python -B experiments/native12-410-menu/build_loading.py --source build/native12-410-menu-20261102-01/manifest.json --output build/新的候选目录 --release411 --menu-event-fix
.venv/bin/python -B experiments/native12-410-menu/qt_research.py --manifest build/新的候选目录/manifest.json --menu-isolation
.venv/bin/python -B experiments/native12-410-menu/qt_research.py --manifest build/新的候选目录/manifest.json --menu-isolation --scenario bad-select-ack
```

导航及审计命令见归档README；原始research-actions.json为实际Qt操作依据。独立CP拒绝回归未改CP字节，可复用本批证据；旧101项封包证据不自动授予新AP。新AP本轮实际执行9项固件CPU／UI回归和10项QEMU合同，没有重跑封包、签名或全量安装验证。

旧4.11升级包没有重新打包或改签。此次证据只能证明菜单隔离下的应用控制链，不能将本轮报告标为“E4完整修复”或“固件可刷／稳定”。

## 2026-11-03 快速切换反馈回归

用户确认故障发生在现有4.11包，慢速切换正常。本轮完整核对DAT摘要，确认包内仍为字体AP、不含独立E4事件修复。新增真实AArch64回放覆盖忙态连续导航、迟到值通知和下一次输入：旧AP按预期进入页面状态3，修复AP继续下一项请求、保持等待状态4。原版1项预期失败，修复候选6项E4回归及相关13项回归通过。

该时序测试使用真实页面／setter／请求序列代码，通知路由与worker完成快照是显式夹具；不代表真实CP/E4/持久化成功或本次实机复现。没有启动新QEMU，没有新DAT，没有连接设备。既有修复已覆盖新增用例，本轮未新增固件补丁；当前4.11包仍未修复。详细证据与限制见[快速切换调查](../../native24-combined/dependencies/native12-combined/verification/2026-11-03-rapid-switch/README.md)。
