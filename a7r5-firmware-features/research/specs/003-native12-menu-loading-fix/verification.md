# 4.10 自定义滤镜中文显示及QEMU加载复验

结论：`VERIFIED_WITH_FINDINGS`。中文方框已修复；冻结BIN中的十二款配置经过生产AP读取、持久化、真实CP参数验证与封存后发布名称，十二项右栏全名均能逐项完整显示。仍存在左列长简称裁切，且原生E4刷新未完成；本结果不能作为滤镜成功应用或完整固件可安装的证明。全程没有相机、USB、SSH、真实存储卡或主机原始分区操作。

[全部截图及证据](../../native24-combined/dependencies/native12-combined/verification/2026-11-02-qemu-native12-loading/README.md)包含689个文件，保留92张原始PNG及同名客体帧、AP只读状态、真实CP消息、两项加载拒绝、组件与源码快照、摘要清单。历史方框及失败候选现场保持。

## 中文方框根因与修复

发现两层问题：QEMU启动将空tmpfs挂到`/tmp`，遮住原厂中文字体；恢复字体后，私有动态UTF-8文本仍继承英语模板的Univers字体。字符串接口本身接受UTF-8，不应将文本改成UTF-16或用英文替换中文。

QEMU启动现在先保存并恢复原字体字节。原厂`MYingHeiC-GB18030-SJ_wIcon.ltt`为2054740字节，SHA256 `e25ccca0ea0c4c0837b04e5008496c342f53c98c2a868541ba89eaead9798205`。固件独立覆盖层通过原厂FontAttributeWriter及属性合并器克隆当前字体全部属性，含非ASCII的私有文本选`FONT_S_CHINESE`（`0x02066003`），纯ASCII恢复`FONT_UNIVERS`（`0x02066000`）。字号、颜色、排版及原No12控制器保持。

`native12-combined/menu-font.c`和`menu_font.py`实际编译816字节代码，只修改私有字符串路径的尾跳转、原RX零填充窗及活动PHDR长度三处，映射页数不增加；精确逆还原通过。完整AP前像、原厂`libObj.so`和输入路径均严格校验。`build.py`的新封包流程已经接入该覆盖层，但本轮没有执行新DAT封包或签名。

## 加载链与模拟边界

软件SD只提供本次`A:/R5NATIVE.BIN`只读接口。生产AP冷启动工作线程实际读取29552字节、30次read，执行原v4校验及内部文件暂存、读回、rename、fsync。内部存储是真实客体vfat，位于本次RAM块设备`/dev/nflasha30`，不是主机分区或真实卡；原挂载检查保持。回读长度29552、MD5 `a767836c31dc77f1288c8206680c0f3e`与输入匹配，暂存文件不存在。客体没有sha256sum，故内部回读明确使用MD5及长度；宿主输入另以完整SHA256固定。

AP发出一次容量探测及BEGIN、12次PUT、SEAL，共14次配置传输；真实CP回执确认封存mask为`0xFFF`。每份2392字节CP参数均与独立从BIN展开的投影逐字节一致。生产AP只读采样得到十二项名称及`available_mask=0xFFF`；没有直接写名称、mask或成功位。

CP为独立ARM QEMU执行当前CP的原生接收、校验、封存及选择代码；OSAL和1MiB堆是明确服务替身，不运行完整CP/RTOS、不模拟ISP。原CP启动复制器实际执行；普通RAM页表支持其原生非对齐访问。AP/CP之间仅使用本次保留RAM、QMP只读导出和客体tmpfs回执。处理CP期间暂停AP虚拟时钟，以保留原协议预算。两侧均禁用网络及设备直通。

## 实际验证证据

以下QEMU命令在`a7r5-qemu`目录使用该项目`.venv/bin/python -B`执行，原始输出及来源收据已归档。

| 验证 | 实际结果 | 主要证据 |
|---|---|---|
| 现有固件回归 | 101 passed，57.80秒 | `regression-101.xml`；根项目pytest执行，未用QEMU项目环境 |
| 新字体及严格输入合同 | 2项通过 | `contracts-2.log`；完整前像、三处改动、同页RX、精确逆还原、No12原字节及身份/路径/篡改拒绝 |
| 完整有效配置 | 12名称、12 PUT及SEAL、逐字节参数投影、内部回读通过 | `runs/valid/loading-audit.json`及`internal-storage.log` |
| 损坏BIN | 第160字节变为1，保持29552字节并核对损坏摘要；AP拒绝、名称空、mask为0 | `runs/invalid-bin/invalid-bin-injection.log`及`loading-audit.json` |
| 错误容量ACK | 真实CP先产生回执，交付AP时破坏CRC；AP不发送E7参数传输，名称空、mask为0 | `runs/bad-ack/fault-delivery.jsonl`及`loading-audit.json` |
| 独立真实CP拒绝/复用 | 坏探测拒绝、坏PUT不发布槽位、完整封存后相同BEGIN复用；堆分配保持1次 | `cp-regression/verification.json`及原始CP消息 |
| 原厂页面截图 | 92张原始帧与PNG逐像素一致，92次真实Qt点击含STOP | `runs/valid/frame-audit.json`、`qt-research.json` |
| 菜单生命周期 | 最后8次MENU构成4轮往返，两组像素严格交替 | `research-actions.json`及`frame-audit.json` |
| 正常退出 | AP QMP quit、CP SYS_EXIT_EXTENDED、Qt工作进程均退出0 | 三个场景各自`exit.json`、`cp/close.json`及正例`qt-research.json` |

最终有效运行：`a7r5-qemu/runs/native-native12-410-6kkhw89r`；损坏BIN：`native-native12-410-hkjitidm`；错误ACK：`native-native12-410-czi6z25n`。构建清单为`build/native12-410-loading-20261102-13/manifest.json`，独立CP回归目录为`build/native12-410-cp-regression-final-01`。

执行入口：

```sh
.venv/bin/python -B experiments/native12-410-menu/qt_research.py --manifest build/native12-410-loading-20261102-13/manifest.json
.venv/bin/python -B experiments/native12-410-menu/probe_menu.py --manifest build/native12-410-loading-20261102-13/manifest.json --scenario invalid-bin
.venv/bin/python -B experiments/native12-410-menu/probe_menu.py --manifest build/native12-410-loading-20261102-13/manifest.json --scenario bad-ack
.venv/bin/python -B experiments/native12-410-menu/verify_loading.py --run runs/本次新目录 --manifest build/native12-410-loading-20261102-13/manifest.json
.venv/bin/python -B experiments/native12-410-menu/verify_run.py --run runs/本次新Qt目录
```

审计输出采用排他创建；复跑使用新运行目录。Qt导航动作完整保留于归档`research-actions.json`。不得向既有成功证据目录覆写输出。

## 截图复核与未解决项

十二项依次为ASTIA、CLASSIC CHROME、ETERNA BLEACH BYPASS、ETERNA、CLASSIC Neg.、PRO Neg. Hi、PROVIA、REALA ACE、Velvia、理光正片、理光负片、Portra400NB。对应`research-028-DOWN.png`至`research-039-DOWN.png`；中文标题、关闭项、中文名称及状态不再为方框。FL2／FL3为050／051，照片2.35:1选项为076，均在最终同一派生AP下复验。

1. `Portra400`左列简称仍被原生窄列裁切，右栏`Portra400NB`全名完整可见。字号、clip及原生省略试验均未解决，已撤出。独立宽列候选触发客体异常，已停止并保留`native-native12-410-0dep96x7`，没有进入最终补丁。T003中“十二简称均可读”部分未满足，不能无保留勾为完成。
2. 原生E4对象已构造，但`native_refresh.done=0`、`selected=0`，页面实际显示“应用失败，请重试”。根因尚未判定为模拟边界缺口或固件问题，没有伪造完成回执。本次仅验证配置加载、名称显示及菜单操作，不能证明成功应用、选择保存、EVF/JPG颜色或兼容性全部通过。
3. FL2／FL3和照片2.35:1是实际菜单证据；未验证照片画面标记叠加、电子快门声音及真实成像。没有全CP/RTOS或实机验收。
4. 首次损坏BIN注入因客体dd不支持`conv=notrunc`中止，正常QMP退出，现场保留`native-native12-410-z1mfphv8`。验证脚本改为分段复制并核对摘要/长度后，完整负例已复验通过；不把首次失败算作通过。

## 身份与验收边界

| 材料 | SHA256 |
|---|---|
| 原整合AP | `25d79cffe07c44b094020d162e07ea2ac995cf929f1886dc5dbac6be78ba6520` |
| 本次字体AP | `a1e6a6472e200e5554426d54b73e1b031dfb2a75251a1854b124e223a08b68c5` |
| CP保持 | `bb8eeaaeb9d13a4687605de6e01ccbe4adc500f595d2f8dbfe886eedd8a643d0` |
| BIN保持 | `19e020fa48c79643aaf9526e9c720d38ec5a92c3df11d0852b0a93a25ee880b6` |
| 旧DAT保持 | `1cc7ec6644c3a86a959341ff95b8904c633f12e8c9e4c6c58a0828568dcd4eb5` |

AC-001中文显示、AC-002真实加载、AC-003失败保护、AC-004十二项导航/中文全名/帧与退出、AC-005来源与隔离均取得上述证据；任务附加的长简称完整显示仍有缺口。默认`runtime/manifest.json`、QEMU源码和通用tools没有本轮改动，上游冻结快照不修改。旧`releases/4.10/BODYDATA.DAT`没有字体修复，不能作为本轮修订包安装；新增AP与源码已归档，未重封固件、未更换签名。
