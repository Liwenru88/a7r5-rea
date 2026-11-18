# 验证记录

- Feature ID: `002-native12-combined-firmware`
- Updated: `2026-11-02`
- Overall status: `NOT_VERIFIED`
- Offline scope: `VERIFIED`

| Evidence | 命令／步骤 | 结果 | 范围 |
|---|---|---|---|
| E-001 | GitHub main 与本地新克隆 `git rev-parse HEAD` | PASS：47f8f022628aef8de382a613ea4d11cd51d0a965 | 源码身份，不是构建或设备验收 |
| E-002 | `build.py --phase baseline --upstream .local/native12-combined-upstream --output .local/native12-combined-baseline-01` | exit0；188源码锁，AP／CP／三个分区精确匹配；包阶段另验证原版完整TAR为`0c026f0269b4dbc9257ac26c1c15702ceb5ed3754b61af4095a2112bebcf17de` | 原厂输入逐项核对并实际编译，不使用远端私钥、不声称复现其完整DAT签名 |
| E-003 | 初期`pytest .../tests/test_integration.py -q` | 首两次5通过／9前置错误，分别为AP布局不符和CP预留区非零；修正后13通过／1失败，复现旧基底0发送ST；后续新选择器的地址／表定位问题亦由该回归检出 | 保留失败事实，不当作通过；均在临时输出／新模块内，没有发布DAT |
| E-004 | 同一集成测试修正后与包阶段集中回归 | 最终17 passed，0 failures／errors／skipped，1.71秒，exit0；详见`.local/native12-combined-437-01/evidence/regression.{log,xml}` | 三条AP选择、四CP矩阵档／越界sector、非目标保持、声音条件、三组标记校验、搬迁曲线、重复／损坏引导、原版BIN解码；外部设备／ISP未模拟 |
| E-005 | `build.py --phase package --upstream .local/native12-combined-upstream --baseline .local/native12-combined-baseline-01 --output .local/native12-combined-437-01` | exit0；完整4.37 DAT为754525608字节，SHA256 `c50e49b7817af0b9c5618de7aaa942d501038da6754b89a728ba6d4476851474`；RSA及OpenSSL、736841帧、全量预期明文、独立解包和17成员白名单通过；USR e2fsck退出0 | 正常研究签名、原updater不变，所有原始输入前后SHA保持；没有相机／写卡；各实机结果仍false |
| E-006 | 最终只读源指纹、AST、引用与交付结构检查 | exit0；6份实施源与封包回执SHA相同，3份Python AST、6处本地链接、6个交付文件及17项／736841帧回执字段一致；见`evidence/final-static-check.json` | 复用有效行为证据，不重复运行成功测试；无相机或介质操作 |
| E-007 | `build.py --phase package --upstream .local/native12-combined-upstream --baseline .local/native12-combined-baseline-01 --output .local/native12-combined-410-01` | exit0；4.10 DAT为754525608字节，SHA256 `1cc7ec6644c3a86a959341ff95b8904c633f12e8c9e4c6c58a0828568dcd4eb5`；17项回归、完整签名及OpenSSL、736841帧、独立解包和e2fsck通过 | 按用户要求重封版本；原4.37保留，未操作设备 |
| E-008 | 新旧解包、源指纹、AST和当前文档链接比对 | exit0；新头版本字节`10 04`，与旧头仅偏移8～11的CRC和32的版本不同；全部TAR成员／组件、AP／CP／分区、BIN、公钥与updater一致；6份实施源指纹一致；见`.local/native12-combined-410-01/evidence/version-only-comparison.json` | README在封包后更新为新交付入口，文档差异单独记录，不变更历史回执或冒充实施源变化 |
| E-009 | 固定上游和4.10交付复制到模块内 | exit0；331个上游已跟踪文件、20份原交付／证据／精简基线文件复制前后SHA一致；快照清单SHA为`c81e5b4681479eccf99224aae820adabaf139df3fb758a1e1927d81787e0ad95` | 原`.local`来源保留；不复制Git元数据、私钥、原始镜像或解包工作区 |
| E-010 | `pytest -p no:cacheprovider a7r5-firmware-features/native24-combined/dependencies/native12-combined/tests -q --tb=short --junitxml=a7r5-firmware-features/native24-combined/dependencies/native12-combined/releases/4.10/evidence/archive-regression.xml` | 首次新增合同5失败，证实旧入口不能使用无Git快照；实现后集中22 passed，0失败／错误／跳过，4.62秒，exit0 | 环境指定原精确基线和模块内upstream；覆盖无Git源、源／清单篡改和额外源拒绝、来源清单排除归档／中间件及原17功能场景 |
| E-011 | 归档最终SHA、快照／旧Git兼容、AST、引用及私钥块检查 | exit0；188项源码锁、331源、24份归档清单文件、35处本地链接通过；四份固件补丁源与原包相同、DAT／BIN／公钥及冻结回执保持，私钥块0；见`native12-combined/releases/4.10/evidence/archive-audit.json`与`ARCHIVE.json` | 当前实施源7份独立绑定；复用原签名／逐帧证据，不重封或操作相机 |
| E-012 | 新增C来源回归，修复前执行定向用例 | 预期失败：1 failed，清单期望7项但实际6项；最小修复`implementation_sources`后纳入C及Python服务 | 工具来源可追踪问题，不是固件功能缺陷；详见runtime-fix.md |
| E-013 | `tests/verify_release.py --baseline .local/native12-combined-baseline-01 --output a7r5-firmware-features/native24-combined/dependencies/native12-combined/verification/2026-11-02-runtime` | exit0；100项通过；重新正常签名／OpenSSL、736841帧、751577088字节明文、完整独立解包、被测AP／CP完全对应、12份模板重建比较与e2fsck通过 | 当前DAT未变化，未读取私钥；原始解包证据与该时刻源码快照保留 |
| E-014 | 补查11个真实Gamma取表入口后，运行当前`tests/`全部回归 | exit0；101 passed in 52.00s，0失败／错误／跳过；`final-regression.log/.xml`与`final-verification.json` | 生产C＋真实合并AP／CP指令＋双CPU消息回放，范围和服务替身详见offline-runtime.md；封包内容相同，复用E-013的有效签名／帧／解包结果 |

上述命令均在根目录使用现有`.venv/bin/python -B`，并设置`PYTHONPATH=$PWD/a7r5-dat-tool/.venv/lib/python3.14/site-packages`；未安装或修改现有依赖。当前交付入口为`a7r5-firmware-features/native24-combined/dependencies/native12-combined/releases/4.10/`，原4.10／4.37回执仍在各自历史`.local`目录保留。E-010另设置`A7R5_NATIVE12_BASELINE=$PWD/.local/native12-combined-baseline-01`与`A7R5_NATIVE12_UPSTREAM=$PWD/a7r5-firmware-features/native24-combined/dependencies/native12-combined/upstream`。

| Acceptance | 离线状态 | Evidence | 限制 |
|---|---|---|---|
| AC-001 | PASS | E-002、E-004、E-005 | 固定远端基线和不变逻辑；真实机身效果未验收 |
| AC-002 | PASS | E-004、E-005及AP.json／CP.json | 本地四项代码与已有菜单能力；不声称照片叠加或出声通过 |
| AC-003 | PASS | E-004、精确逆还原及最终成员白名单 | 不放宽未知前像、重叠及映射检查 |
| AC-004 | PASS | E-007、E-008及最新delivery/verification.json | 4.10交付为未实机验收的研究候选 |
| AC-005 | PASS | E-007的公钥摘要、OpenSSL及原updater回读 | 当前机身信任和版本准入未读取 |
| AC-006 | PASS | E-002／E-007的输入SHA保持、独立输出及E-008／E-011源指纹 | 未修改旧32槽工程或故障现场，未执行设备动作 |
| AC-007 | PASS | E-009～E-011、ARCHIVE.json／CONTENTS.sha256 | 归档、快照和构建入口集中完成；不把复制或路径适配当作新的固件／实机验收 |
| AC-008 | PASS（离线范围） | E-012～E-014、offline-runtime.md | 实际原厂服务、硬件消费、完整启动／掉电／恢复仍需实机验收；本次未连接或探测设备 |

设备升级、真实启动／LCD／EVF／JPG、声音、照片标记叠加和掉电恢复：MANUAL_REQUIRED，本次未授权。整体NOT_VERIFIED反映此边界，不否定T001～T008离线交付完成。本轮没有固件逻辑修复或重封；源码、包摘要和全部范围见最新运行时报告及最终回执。

## 当前4.10的QEMU菜单补验

E-015：在`a7r5-qemu`目录使用其`.venv/bin/python -B`运行独立`experiments/native12-410-menu/qt_research.py --manifest build/native12-410-menu-20261102-01/manifest.json`（TTY宿主控制通道）。当前包AP／CP文件、参数模板、版本及相应文字资源进入独立CPIO，其余条目保持。有效运行`runs/native-native12-410-tc2enw_f`完成103次真实Qt操作及103帧，四轮MENU往返，worker／QMP退出0。

E-016：`experiments/native12-410-menu/verify_run.py --run runs/native-native12-410-tc2enw_f`退出0，所有PNG与客体RGBA4444原始帧逐像素一致，未使用预制或补画菜单。独立清单拒绝测试1项、实际macOS沙箱边界测试1项均通过。当前包内容、默认模拟器及旧回执不改写。

AC-009截图来源和交付：PASS（有发现项）。FL2／FL3和照片标记选项／2.35:1读回菜单通过；自定义页面可打开，但当前英语界面中文文字为方框（FAIL，原因未定位），自然启动只显示关闭，十二配置导入／CP激活NOT_RUN。照片M信息页开启前后像素相同，叠加仍NOT_VERIFIED。详见`qemu-menu.md`及`native12-combined/verification/2026-11-02-qemu-menu/README.md`。本轮没有固件修改、名称注入或设备操作；这些发现不能由此前101项离线状态机测试的通过抵消。
