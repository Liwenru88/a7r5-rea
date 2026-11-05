# 快速切换修复验证

Feature ID: 006-unified-look-rapid-switch
Status: NOT_VERIFIED
Updated: 2026-11-03

快速切换的调度与状态处理已实现，T001～T003的定向回归和有限QEMU观察已执行。**完整的实际应用成功闭环仍受既有成像初始化缺口阻塞**，所以整体保持NOT_VERIFIED；没有新DAT或实机操作。本状态不否定下表中有明确边界的CPU／有限UI证据，也不将它们升级为完整固件通过。

后续范围澄清：上述初始化阻塞属于当前QEMU模型限制；用户报告实机没有同类问题，但未提供本候选e833…及最终新包的逐项实机验收记录，已有证据状态保持。用户现已选择维持冷启动导入，007热导入方案搁置，不将其内存复用／热替换门禁加入本候选范围。

## 实现与代码身份

新AP SHA256：`e833e0290fe60207cc5d9d2b7a0a66b253f7ab0db99ed12afb2a0c47ca6f72f1`，严格派生自E4修复AP `65e33ba2075bb59f65a97e6cec550bd8b1d54bac040fe28427cd3922924ffde0`。修复前统一入口为`5cd0f22949fc8134c59855ca91a5225722638bf9098fe3e1c74b61fdad603c43`，旧组件和归档保留。

改动落点：`native12-combined/unified-look.c`的单笔在途／最后目标调度、按目标标题、原厂延迟委派、参数保护及D9生命周期；`unified_look.py`增加严格前像的原D9 dispatch跳板。没有修改CP、BIN、原E4／持久化门禁、超时和成功位。QEMU实验仅加入新候选的固定身份，同时继续验证已冻结的旧候选。

当前行为：输入不循环等待；忙态保留最后目标、同项合并。原厂目标等slot0成功后，按仍有效的当前MID重新解析原生预览上下文，不保存临时指针。Enter在等待时保留页面，完成后可再次确认；MENU或离页退休未提交目标，已接收事务继续按原后台规则结束。新增十二项标题区分“等待应用”与“应用中”，原厂项保留原标题并在退出覆盖期间禁止调参。

## 实际证据

所有固件CPU命令在仓库根目录使用`.venv/bin/python`，设置`A7R5_NATIVE12_BASELINE="$PWD/.local/native12-combined-baseline-01"`；QEMU命令在`a7r5-qemu`使用其自身`.venv/bin/python`。

| Evidence | Code State | Command / Step | Result | Scope |
|---|---|---|---|---|
| E-001 | 冻结旧AP 5cd0…＋最终回归 | `A7R5_UNIFIED_TEST_ORIGINAL=1 ... pytest -q .../test_unified_look.py -k 'rapid_latest or owned_failure or native_latest or menu_cancels'` | 7项预期FAIL，exit 1，3.16秒 | 忙态误判、合并缺失、失败归属／去重和生命周期保护缺口；不是测试通过 |
| E-002 | 新AP e833… | `... pytest -q .../test_unified_look.py .../test_unified_icons.py` | 27项PASS，exit 0，5.27秒 | 真实AP提交器／序列、最后目标合并、无UI睡眠、忙态争用、外部序列、失败回退快照、配置失效、原厂委派／取消、标题／图标、非零基址、注册树和新AP上的本地四项 |
| E-003 | 既有后台及E4修复AP | `... pytest -q .../test_runtime_selection.py .../test_e4_menu_compat.py` | 15项PASS，exit 0，4.86秒 | 既有CP选择／回退及私有页事件；不冒称当前统一页的完整E4验证 |
| E-004 | 新旧两份固定QEMU清单 | `... unittest discover -s experiments/native12-410-menu -p 'test_*.py' -v` | 13项PASS，exit 0，1.647秒 | 清单身份／收据拒绝、既有模拟服务及采样边界；旧清单继续可验，新未知摘要不放行 |
| E-005 | 新AP e833…，运行8r54hei5 | 真实Qt前台设置、M档、原创意外观、连续UP与等待／退出 | 有限观察PASS，完整应用NOT_VERIFIED | F12→F11→F10仅CP提交12、10，中间11跳过；Enter保持等待页；原E4真实超时回退；四轮MENU和ST重入／退出正常 |
| E-006 | 本次归档及冻结材料 | 独立AP构建、逆还原、87原帧与PNG逐像素、旧DAT／上游逐项SHA | PASS | 两旧DAT与上游331文件未变，CP／BIN固定，源码与被测AP一致；不涉及设备安装 |

E-002中的worker成功／失败终态是CPU测试内显式放置的快照；失败快照保留原worker的desired回退及handled／dirty未完成语义。部分原厂UI边界为替身，**不等于CP/E4/文件成功**。原厂延迟委派证明当前MID和调用顺序，未证明实机调参效果。

## QEMU实际观察

构建入口：`build/native12-unified-rapid-20261103-01/manifest.json`，启用明确的单请求待处理通知模型，仍不产生0x2040成像就绪。运行入口为`qt_research.py --manifest build/native12-unified-rapid-20261103-01/manifest.json`，未使用menu-isolation，也未写生产完成字段。

完成原前台设置并切到M档后进入ST。`research-021-UP.png`为F12应用中；`022-UP.png`为F11等待；`023-UP.png`为F10等待。三帧CP消息数均18，`024-ENTER.png`仍在同一页面且像素与023一致。继续正常SNAPSHOT循环，保持CP服务泵运行，没有用无人服务的QMP时钟推进制造额外传输超时。

实际CP选择序列为`0、0、12、0、10、0`，后四项对应F12尝试、回退0、最后F10尝试、回退0。**没有提交11**。F10随后显示“应用中”，最终原E4未完成，后台状态为3，AP／CP／选择文件保持0。该失败按真实门禁显示，本轮没有误报成功，也没有在终态自动重试同项。`research-073-SNAPSHOT.png`保留F10列表与失败标题；这是本次场景结果，不能据此认定所有历史列表消失原因已经修复。

`research-076`至`083`为四轮顶层MENU开关，打开帧和关闭帧分别逐像素相同；`085-ENTER.png`重入ST与首次`020-ENTER.png`一致。共87客体原帧／PNG逐像素核对，87次Qt点击含STOP，worker、AP QMP及CP退出0。仍不证明完整成像初始化、冷启动及实机行为。

## 验收覆盖

| Acceptance | 有限证据状态 | 限制 |
|---|---|---|
| AC-001 | PASS（CPU、在途期间实际Qt／CP观察） | 未做真实相机高速拨轮压测 |
| AC-002 | PASS（CPU及QEMU真实失败） | 成功终态仅CPU快照，QEMU原E4成功仍阻塞 |
| AC-003 | PASS（CPU）；有限MENU／重入PASS | 实际成功退出覆盖后的原厂调参仍未验证 |
| AC-004 | PASS（CPU、等待／在途／失败实帧） | 本轮无统一页实际成功画面；原厂项仍用原标题 |
| AC-005 | PASS（离线构建与相关回归） | 未封包、未验新DAT、未连接相机 |

源码、组件、XML、清单、原帧与校验清单见[本轮归档](../../native24-combined/dependencies/native12-combined/verification/2026-11-03-unified-rapid/README.md)。005整合版仍保持未通过；本轮没有扩展到补全成像模型或发布升级包。

## 冷启动版补验（同一固件身份）

用户随后指定五类收尾场景。当前e833…／固定CP新增9项双CPU跨层回放通过（89.32秒），没有修改固件。不同于E-002的worker终态快照，新测试执行真实后台、CP回执和选择文件编解码／发布；但原E4外部执行、目录锚定及原厂UI仍是明确替身，不能升级成实际E4成功。新增真实Qt全十二项／ST／FL2／FL3、四轮MENU及重入复验，72原帧与PNG逐像素一致，三侧退出0；QEMU原E4仍未完成。

新证据、源码身份复用、逐项状态和机身待验步骤见[冷启动版补验归档](../../native24-combined/dependencies/native12-combined/verification/2026-11-03-unified-cold/README.md)。它补充AC-001～AC-003的跨层证据，保持本页整体NOT_VERIFIED及原实验边界。
