# 验证记录

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-11-02`
- Overall status: `NOT_VERIFIED`

## 2026-11-02：用户重新授权后的SSH只读现场

`T11ui59`未完成，根因未知。以下为当前真实设备读取证据，不是QEMU结果；没有写设备、触发创意外观或重启相机。

| Evidence | 回执 | 结果 | 边界 |
|---|---|---|---|
| E-417 | `incident59-live-20261102/installed-payload-comparison.json` | 75项USR目标内容及CP共76项MD5与integration58一致 | 4.12内容亦相同，未读取版本头；未验证其他组件或设置 |
| E-418 | 同目录`verification.json`与正确范围的内存读取回执 | 实际AP握手state2、能力0x1f1fff、fault0；prepared1、56挂钩；当前页面0x263、phase1、installed0 | 此现场页面不满足扩展发布条件，不证明入口稳定、配方应用或像素通过；错误范围采样已排除 |
| E-419 | `kernel-log.json`、三份原二进制日志与`persistent-log-checksums.json`、起止现场 | 8421512字节日志下载后MD5匹配；同一启动标识、运行时间304.30→1109.85秒，/usr保持只读 | 当前启动日志无直接上次崩溃PC；二进制日志尚未解码为故障位置，没有主动重现 |

完整事实、采集工具错误及剩余定位方向见[SSH只读现场分析](incident-59-ssh-readonly.md)。

## 2026-11-02：按用户要求封装研究4.12，同载荷已知故障保留

`T11v412`仅离线版本封装完成；创意外观重启故障未修复，`T11ui59`保持未完成。包为754525608字节，SHA `19d8bfb81da4dc70f82daa94cbc9f33cd0fc4015dc48cba79c553f8be14840b6`。不操作相机。

| Evidence | 命令／回执 | 结果 | 边界 |
|---|---|---|---|
| E-413 | `pytest -q .../tests/test_upgrade_package.py` | 32 passed，exit0；精确4.12版本／schema范围及公开入口一致 | 仅封装规则，无更新器／信任改动 |
| E-414 | `software31/verify.py --recipe-bridge --capture-copies --bootstrap-only`；`repackage412-software/verification.json` | 当前来源交叉构建及70项软件门禁通过 | 不重复声称445项旧来源回归本轮重跑 |
| E-415 | `release406/build_candidate.py --version 4.12`；`repackage412-release/commands.json`、`update412/verification.json` | 五阶段exit0，正常研究验签／独立解密／全归档回读、75项USR和CP正逆保持 | 非官方签名，设备安装资格false |
| E-416 | `release406/verify_candidate.py --version 4.12`；`repackage412-content-audit.json`、`repackage412-final-audit.json` | 60条原复杂图像载荷、全部75项USR和CP与integration58相同；USR仅s_wtime变化，旧DAT摘要保持 | 同载荷仍有入口重启风险；不推荐实机安装，无新修复／实机证据 |

交付路径与已知故障见[4.12封装报告](repackage-412.md)。

## 2026-11-02：integration58 实机入口故障与离线未复现

用户确认 integration58 进入“创意外观”会重启，重启后正常。该候选停止推荐继续测试；历史封装／软件通过证据保留，但不代表实机入口安全。用户选择暂不连接相机，仅保留离线排查结果。`T11ui59`／`AC-010-UI59` 未完成，根因未知，没有固件修复或新升级包。

| Evidence | 命令／回执 | 结果 | 边界 |
|---|---|---|---|
| E-411 | 用户故障确认；`incident59-intake.json` | integration58 原厂创意外观入口实机失败，恢复后正常 | 用户观察；未读取实机文件摘要或崩溃日志 |
| E-412 | `boot-menu406/build.py --software-peer --chinese`、`run.py --interactive`；`incident59-offline-audit.json` | 同一 AP／产品启动库／资源的软件环境执行24次按键，进入 ST `0xd9`、参数 `0xda` 并返回；QMP退出0，未复现重启 | AP 软件对端，无真实 CP／ISP、机身 SD 或存储；未证明32槽或实机修复，不强制准入／发布 |

详细输入摘要、命令、运行目录和待查边界见[故障59离线记录](incident-59-creative-look-reboot.md)。

## 2026-11-02：第58批ST门禁下完整重新封装

T11st58限定本地封装交付完成。研究4.10／integration58，754525608字节，SHA `b1f3f35c7cd614fdc07b94971323cda5b25a14de6fbbc9e94ecf582bc8d17c37`。不操作相机，不做CP／ISP硬件模拟；原包和旧候选保持。

| Evidence | 命令／回执 | 结果 | 边界 |
|---|---|---|---|
| E-409 | `release406/build_candidate.py`；`integration58-release410/update410/verification.json`、COMPLETED.json及commands.json | 五阶段exit0、研究签名有效、独立解密一致、全归档回读；明确使用ST连续测试门禁true的软件回执 | 复用同源445 passed／10skip、70门禁测试及4消毒场景；不声称本轮重跑或实机通过 |
| E-410 | `release406/verify_candidate.py`及`integration58-final-audit.py`；`integration58-content-audit.json`／`integration58-final/verification.json` | 最终CP、75USR内容、四DSO和60复杂载荷核对，当前来源／旧包／输入匹配；新旧USR除s_wtime外全部一致 | 只有0x430／0x431两个元数据字节改变，无新机内功能；真实启动、SD和EVF/JPG仍未验收 |

任务T03native55、T03f2及T12未关闭。完整文件、校验与受控ST测试说明见[integration-58-st-upgrade-package.md](integration-58-st-upgrade-package.md)。

## 2026-11-02：第57批ST单基底连续软件链路

T03st57限定离线软件子范围完成。默认CUBE的同一真实四组件配方已经连续通过保存／重开、八参保存、AFD1回导、AP绑定／真实28帧发送、CP接收／ACK、原生银行／输入复制及主／普通Capture组件。原系统、Jobs视图、原构造／packer仍有明确端口边界；没有真实照片像素或机身存储验收，T03native55、T03f2及T12保持未完成。

| Evidence | 命令／回执 | 结果 | 边界 |
|---|---|---|---|
| E-405 | `integration57-verify.py`；`integration57-validation/verification.json`及commands.json | 24文件445 passed、10旧配置skip，56.94秒、exit0；同槽不同LUT／旧Capture／原厂切回及取消、坏文件、CP负ACK通过 | 同一生产默认模型；普通目录／系统端口不代表真实设备 |
| E-406 | 同一ST驱动ASan／UBSan及测试中的原`41363C`纯软件构表 | 4场景exit0，7个实际产品候选129点精确消费／保护区保持；四组件均有非零实际拟合值 | 原函数只运行纯CPU软件窗口；不启动CP、ISP或硬件模型 |
| E-407 | `software31/verify.py --recipe-bridge --capture-copies --bootstrap-only`；`integration57-software-gated/verification.json`／`integration57-gate-rejection.json` | 70 passed、20.88秒、exit0，ST门禁true；缺少ST验证的旧回执在创建输出前被实际拒绝 | 门禁只授予软件构建资格，不授设备安装或像素资格 |
| E-408 | AP预检／启动库重链接与`integration57-final-audit.py` | 当前AP、四DSO及70资源与第56批DAT一致；原生RX39280、RW48744、51挂点／69窗口精确正逆，当前来源核对通过 | 目标运行期源码与DAT不变；无新DAT，不重复旧包签名／全解包测试 |

研究4.10／integration56的SHA保持`3e3d7e5759e39a0c8018e055e6309292eeb7c5ea742dd186b35e388bc180c158`；此次新增连续证据和发布门禁，未扩大基底或Gamma格式。模型误差／工作值修改后报告适用性、夹具与真实任务边界详见[integration-57-st-photo-chain.md](integration-57-st-photo-chain.md)。

## 2026-11-02：第56批完整研究候选整合与独立回读

T11j56限定本地打包范围完成；T03native55、T03f2及T12保持未完成。候选4.10／integration56，754525608字节，SHA `3e3d7e5759e39a0c8018e055e6309292eeb7c5ea742dd186b35e388bc180c158`；新增第55批Gamma选表修复已写入最终CP，输入与旧包未修改。无设备I/O，无CP／ISP硬件模拟。

| Evidence | 命令／回执 | 结果 | 边界 |
|---|---|---|---|
| E-401 | `software31/verify.py --recipe-bridge --capture-copies --bootstrap-only`；`integration56-software/verification.json` | 当前399来源配套构建，66 passed、12.83秒、exit0 | 启动依赖宿主合同与交叉构建；未运行机身任务 |
| E-402 | `packaging406/stage_cp.py`；`integration56-cp-staged/verification.json` | 最新CP落盘、51挂点／69窗口、独立FAT提取及全分区／CP严格正逆 | 复用当前同源第55批ARM链接；不执行新CP模块 |
| E-403 | `release406/build_candidate.py`；`integration56-release410/update410/verification.json` | 五阶段exit0，完整DAT研究签名／独立解密／全归档回读、75USR内容项核对 | 官方签名false，设备验收及安装授权false；更新器与信任规则不变 |
| E-404 | `release406/verify_candidate.py`及`integration56-final-audit.py`；`integration56-content-audit.json`／`integration56-final/verification.json` | 四DSO、60复杂载荷、四继承Gamma记录、最终CP SHA与严格逆还原、当前测试来源以及旧包／输入保持全部通过 | 来源未变的310 passed／10skip、36 sanitizer、15原CPU构造复用；未重跑QEMU或实机 |

交付与范围见[integration-56-release-candidate.md](integration-56-release-candidate.md)；后续设备验收及恢复限制见[integration-56-device-test.md](integration-56-device-test.md)。原模型域、特殊分支及真实像素限制未因封装完成而放宽。

## 2026-11-02：第55批用户槽配方与原厂Gamma选表入口

按用户最新授权优先原厂共用入口，特殊2B不再作为无依据的无条件前置。T03native55a／b完成，T03native55整体、T03f2及T12未改为全部完成。原更新／缓存／分组回退保持，未操作设备或进行CP／ISP硬件模拟。

| Evidence | 命令／回执 | 结果 | 边界 |
|---|---|---|---|
| E-396 | `integration55-red-replay/verification.json`，最终用户槽集成驱动配旧产品C | 原RO门禁误拒FL2／FL3四个有效记录，4项预期失败／ST对照通过；完整旧源及命令保留 | 复现的是私有Gamma增量未应用，不表示原厂FL2／FL3损坏 |
| E-397 | `integration55-tests-final/verification.json`及`test_cp_native_gamma_selection406.py` | 310 passed、10旧配置skip，17.74秒、exit0；实际用户槽读取、原生副本接收、九字段投影、E70输入及Gamma构造／回退；含现有矩阵／CC1／网格和AP请求回归 | 13个相关测试文件；原线程／系统及原调用端口为显式软件夹具，非完整AP／CP照片任务或像素 |
| E-398 | `integration55-sanitizers/verification.json`及`integration55-native-vectors/verification.json` | 36个ASan／UBSan场景；其中15个产品候选经固定原CPU `41363C`实际构造，曲线逐字节一致、原轴及保护区保持 | 原Gamma表仅在隔离RAM换指针；不执行新ARM模块或ISP，未测照片误差 |
| E-399 | `integration55-native/verification.json`、`integration55-memory/verification.json` | 当前ARM链接RX39280／40960（+88B）、静态RW48744保持、bootstrap408；51挂点、69窗口精确正逆及错误原像拒绝；继承四曲线保持 | CP候选仅在内存计算，SHA `ef616a6581dac99106380a4f56da9d88093680cf524f72b0eb0b502cea58fc99`；没有CP／DAT写出 |
| E-400 | `integration55-final/verification.json` | 当前代码、测试、回执、原CP／DAT、报告引用及唯一产品C差异核对通过 | 旧第53批DAT不含此修复；无新包或安装授权 |

产品只在主／Capture共用选表检查中额外接受route47／48对应的四个精确记录地址；没有放宽整块RAM、修改原曲线／表项或新增调度。普通取景／JPG继续走既有原厂入口；全部实际任务运行、全部基底模型和像素效果仍分列。详见[integration-55-native-selection.md](integration-55-native-selection.md)。

## 2026-11-02：第54批特殊2B的A／Q与Gamma来源软件审计

T03f2d1限定原窗口子范围完成；T03f2d2、T03f2d及T03f2仍未完成。没有修改产品AP／CP或生成新DAT，没有相机I/O，没有CP／ISP硬件模型。原厂分组更新／回退约定保持，不将组件版本关联改成整配方原子切换要求。

| Evidence | 命令／回执 | 结果 | 边界 |
|---|---|---|---|
| E-393 | `photo-routes406/lineage.py`；`integration54-lineage-final/verification.json` | 54个原CPU软件窗口通过；固定Q、owner回绕／查找、A的BB0／BB4赋值、双Gamma构造与上传参数准备、四backend／child组合到三个生产入口、次资源getter／转移／共享复制、原银行清零和错误CP拒绝 | A／Q／调用帧／计数／描述符均为显式RAM夹具；不执行RTOS锁、资源申请、寄存器或图像helper；不是完整函数／像素完成 |
| E-394 | `integration54-tests-final/verification.json`，五个Gamma／Capture测试文件 | 47 passed、exit0；含来源先拒绝、保持版本／硬件门禁关闭、现有Capture生命周期及组件回退回归 | 定向组；不声称全套或产品新接线通过 |
| E-395 | `integration54-final/verification.json` | 核本批代码／测试／回执来源、报告链接与原DAT、原CP及第53批产品构建来源；本轮产品／候选未改 | 来源审计，不是新构建、重新验签或相机验收 |

新增反例证明：不同A能向同一Gamma参数地址准备上传；原owner高16位会回绕；保留A／Q而执行原全局清零后，上传准备仍到寄存器边界。最后一例是显式夹具，未证明真实任务调度允许该交错。原`845BAC`还依赖回调，不是已证银行getter。构造完成到三类特殊producer的银行版本／串行化和次Gamma stage可达性仍缺，未无条件把2B改成带80的mask。详见[integration-54-gamma-lineage.md](integration-54-gamma-lineage.md)。

## 2026-11-02：第53批原Fsys卷软件闭环及短别名修复

T11i1／T11i2限定范围完成，T11i与T03f2父项仍未完成。未连接相机或物理卡，未做CP／ISP硬件模拟。原Fsys软件卷I/O已执行，不再局限于纯编码器或宿主Fsys替身；真实媒体模型与成像仍单列。

| Evidence | 命令／回执 | 结果 | 边界 |
|---|---|---|---|
| E-387 | 原卷失败运行及`test_fsys406_alias.py`修复前 | 原Find公开短名指针、完整LFN同时存在；旧提供者列表0；新增3个红灯回归复现 | 不放宽UTF8或改卷全局设置，原生错误／失败运行保留 |
| E-388 | `integration53-tests/verification.json`，5个相关测试文件 | 63 passed，5.24秒、exit0；修复长名显示／短名读取并增加别名变化、非法及重复拒绝 | 宿主回归；不是原卷执行的替代 |
| E-389 | `fsys406-software/build_volume.py`／`run_volume.py`及`integration53-fsys-final/verification.json` | 短名0和长名400两模式均完成原Fsys卷、三文件双遍读、取消／STALE、生产CUBE至C07／AFD1至C08及仓库重开恢复；独立FAT五文件核对，两次QMP退出0 | 原卷文件后端真实执行；媒体快照、4MiB VFAT和仓库普通目录为夹具；非物理SD／真实/setting耐久性；AFD1本批为纯参数 |
| E-390 | `photo-routes406/audit.py`；`integration53-photo-routes-v2/verification.json` | 11分派、4原调用mask、4Gamma条件、2计划选择及错CP拒绝通过；阶段11选择来自`[A+5994]+14` | 只执行纯逻辑窗口，在系统／图像helper前停止；2B此前Gamma银行／最终consumer关联仍缺，未启用特殊Gamma |
| E-391 | `integration53-software`／`integration53-native`／`integration53-cp-staged` | 66 passed，11.09秒、exit0；当前产品交叉构建、CP51挂点／69窗口及严格正逆通过 | CP字节未变；不累计定向组为完整测试集，不称原CP运行或新菜单像素通过 |
| E-392 | `integration53-release410-v2/update410/verification.json`及`integration53-final/verification.json` | 新研究4.10包754525608B、SHA `36cf5ff87c9e1f2baac0ac531e22abbaf50c70cf7b5443dc156c9cc31f59619a`；签名／独立解密／全归档回读、四DSO及60复杂载荷审计通过 | 启动库97848B／ac6c92c9…efdff；旧包保留，原4.06不改；研究签名与实机验收分开，安装未批准 |

详见[integration-53-native-volume.md](integration-53-native-volume.md)。最新包实际包含Fsys短别名修复；现有纯参数、中文、32槽和双入口保持。特殊Gamma银行的同A／Q版本来源仍是未解决的成像接入问题，不能将其写成“只差真机测试”。

## 2026-11-02：第52批原生Fsys补证与4.10研究DAT

T11h的离线封装子范围完成；完整功能仍`NOT_VERIFIED`。没有操作相机或进行CP／ISP硬件模拟。最终研究包已签名、独立解密及全归档回读；不据此批准安装。

| Evidence | 命令／回执 | 结果 | 边界 |
|---|---|---|---|
| E-381 | `test_repository_import_service.py`增加Fsys后端；与封装回归共38 passed／6.44秒／exit0 | 仓库三后端12项中新增4项真正经过生产Fsys适配器，64位token／中文长名称、成功／取消／源变化及持久化重开通过 | 底层为显式宿主卷端口，不是原Fsys卷或物理SD |
| E-382 | `fsys406-software/verify_codec.py`；`integration52-fsys-codec/verification.json` | 固定同包原Fsys的两个UTF8函数，32字符／64次实际AArch64软件调用通过 | 不执行原卷初始化／卷I/O；不模拟CP／ISP |
| E-383 | `integration52-native-baseline/verification.json`及`integration52-cp-staged/verification.json` | 51挂点／69窗，RX39192／40960，静态RW48744／49152，CP与整FAT严格逆回通过 | CP与原4.09候选相同，未新增最终消费者或Gamma格式，不代表原CP握手或像素 |
| E-384 | `test_upgrade_package.py`最终28 passed／0.07秒；图像及ext2追加10 passed／0.66秒；`integration52-software-v2/commands.json`66 passed／11.48秒，均exit0 | 修正版图像白名单、4.10公共入口／范围、错误范围拒绝及最新产品依赖通过 | 重叠定向组，不累计成完整测试集；保留红灯复现和失败目录 |
| E-385 | `release406/build_candidate.py`；`integration52-release410-v2/{commands,verification}.json` | 五阶段exit0；754525608B研究4.10，SHA `622b8aeb1074853f78d29167043dfddfa607585a51470da993eb2e7398657230`，签名／独立解密／全归档回读通过 | 原修改4.06输入不变；正常研究签名，非官方签名；未绕过更新器，安装未批准 |
| E-386 | `release406/verify_candidate.py`；`integration52-final/verification.json` | 最终DAT回读USR内两图像各3511原载荷与各30复杂载荷保持，新增各14编号；四DSO冻结摘要及原DAT通过 | 文件内容审计，不是启动／实际成像／介质验收；本批未重跑QEMU |

本批修复的是封装门禁中两份图像的过期目标摘要和4.10范围入口，并补上可重复构建／独立内容审计。产品使用原Fsys，实验软件SD端口没有进入产品库。原生卷I/O、实际SD、真实AP／CP会话、最终EVF／JPG及机身持久化耐久性仍未验收；T03f2父项和T12保持未完成。详见[integration-52-native-release.md](integration-52-native-release.md)。

## 2026-11-02：第51批中文、SD双入口及保存软件闭环

T11g的QEMU软件范围完成；仍不连接或操作相机，不新增CP／ISP硬件模型。保留产品Fsys端口和生产存储准入；软件SD目录端口仅编入实验启动库。实际运行原厂AP、原菜单和当前生产仓库代码，不以测试页面、内存目录预置或假成功回执替代。

| Evidence | 命令／回执 | 结果 | 边界 |
|---|---|---|---|
| E-375 | `boot-menu406/build.py --software-peer --software-storage --chinese`及独立恢复／完整配方构建 | 原厂语言setter25、同包三字体、真实16MiB Linux VFAT、测试SD提供者、AArch64只读导出助手交叉构建通过；清单分别记录产品／实验库身份 | 产品Fsys、输入DAT及原厂外观未改；实验库不能部署 |
| E-376 | `boot-menu51-final/tests.json`及`test_ap_targets_overwrite.py` | 定向49 passed，6.33秒、exit0；另3 passed，0.54秒、exit0。包含导出CRC／截断／退出码拒绝及旧动态AP服务夹具修复 | 非完整测试集；未隐藏初次过期夹具／断言失败 |
| E-377 | 主运行`native-boot-menu406-kugv5ljt` | 中文菜单／中文文件名；卡1 CUBE至C07生成1943B AJR2，纯参数AFD1至C20；实际回读记录／摘要有效 | 软件SD扫描／稳定读取／生产导入；不是原Fsys或照片效果 |
| E-378 | 主运行的导出44／50／81／83／87及原始帧 | 卡2浏览取消和八项临时调参均不写盘；显式Save产生C20_B generation2，initial保持、saved八项全部更新；另存C08成功 | 原菜单动作与真实回读后才显示成功；非物理掉电验证 |
| E-379 | 独立恢复运行`native-boot-menu406-zdhnoy02`，导出1 | 全新VFAT自然恢复5份原文件及36份缺失银行状态，逐字节一致；原厂界面显示C07／C08中文名、C20保存八值及FL2／FL3 | 没有重新导入或设内存快照；不据此确认真实持久化耐久性 |
| E-380 | `audit_storage.py`及`audit_prepared.py`，`boot-menu51-final/` | 两主运行140帧＋完整AFD1/AJR2文件补测29帧，169原始帧SHA及PNG逐字节核对；三次受控QMP退出0。完整配方导入C09后AFD1原字节与来源一致，其余槽不变 | 采用实际导出配方夹具，不是电脑优化精度对照；真实SD／CP／EVF/JPG／完整功能验收仍false，AJR3未在本批QEMU重测 |

CUBE恒等夹具在现有参考域43验证色的ΔE76统计均0、clipped=0，仅用于该数学用例，不推断任意LUT或照片精度。失败现场与边界见[integration-51-chinese-import-save.md](integration-51-chinese-import-save.md)。

## 2026-11-02：第50批离线启动修复与QEMU菜单验证

T11f离线范围已完成，整体仍`NOT_VERIFIED`。`protection()`此前仅接受单条VMA，自己的mprotect／COW已经分裂原AP的连续RX区间，导致自然登记完成后直接STALE、UI模块未装入；修复为逐段验证连续覆盖且权限一致，空洞、RWX／只读转变、溢出、解析失败仍拒绝。该缺陷由实际AArch64启动库在QEMU执行及宿主红灯用例共同复现，不依赖当前机身是否重启的猜测。

| Evidence | 命令／回执 | 结果 | 边界 |
|---|---|---|---|
| E-367 | `test_loader_maps406.py -k span_split`，修复前 | 1 failed／3 passed；连续RX被误拒，其余空洞／权限变化正常拒绝 | 直接编译生产函数，非整个AP执行 |
| E-368 | `test_loader_maps406.py test_loader_startup406.py` | 28 passed，1.31秒，exit0 | 含既有容量、失败失效和启动拥有者门禁；不增加设备资格 |
| E-369 | `software31/verify.py --recipe-bridge --capture-copies --bootstrap-only --output .local/fixed-custom-filters/boot-menu50-software` | 66 passed，11.82秒，exit0；配对构建通过 | 显式不链接不交付的AP／CP裸ELF探针；旧广范围3项缺参考资料错误未消除 |
| E-370 | 当前`boot-menu50-package`预检及`boot-menu50-loader`实际交叉链接；配对环境运行`packaging406/loader`目录测试 | 132前像／57声明、42窗AP保持；真实启动DSO97208B，13 passed，3.31秒，exit0 | UI／请求／仓库及资源表保持，只有启动库修复；没有新DAT |
| E-371 | `boot-menu406/run.py`，`boot-menu50-observe`与`boot-menu50-fixed`的自然启动对照 | 原库STALE且prepared=0／132原前像无差异；修复库prepared=1、56+3挂钩安装；缺软件对端时phase=4、installed=0 | 固定QEMU中实际Linux/AArch64 AP与DSO，非宿主替代；不运行CP硬件 |
| E-372 | `boot-menu50-peer-v2`下两次交互运行，目录尾缀`5ejlrtz7`／`v508qm9v` | 真HELLO编解码经过软件OSAL对端与原接收入口后installed=1；原厂M模式导航Custom Filters管理页、FL2／FL3、C07、C20及回绕ST，74次按键帧，正常MENU退出／重入；QMP退出均0 | 对端是明确软件夹具，不是实际CP。原/setting为tmpfs被生产存储拒绝，管理页如实显示Unavailable；英文显示验证，非中文验收 |
| E-373 | `test_request_handshake.py` | 7 passed，0.02秒，exit0 | 复用既有协议检查，不称CP图像消费 |
| E-374 | `a7r5-qemu/.venv/bin/python -B .../boot-menu406/audit.py`，输出`boot-menu50-final/verification.json` | exit0；74原始帧SHA、9关键PNG按原帧重生成逐字节相同，源／当前目标／导入导出及版本／资源表不变、无对端关闭对照、两次无异常QMP退出均核对 | PASS_OFFLINE_BOOT_AND_NATIVE_MENU_WITH_SOFTWARE_PROTOCOL_PEER；camera_io=false、actual_CP_peer=false、实际持久化／EVF/JPG／完整功能验收均false |

本批未连接或修改相机。调试过程保留：首个观察器输出目录／UID解析问题、软件对端过宽拦截造成客体异常、根环境缺Pillow及非TTY控制输入提前结束均有独立失败记录；最新窄包适配和项目既有QEMU环境已运行通过，不覆盖旧失败。详见[integration-50-boot-menu-qemu.md](integration-50-boot-menu-qemu.md)。

## 当前主线验证状态（2026-11-01）

2026-11-02最新E-366：用户再次明确继续替换；`loader-1d46936e92df.json`中原子rename、新文件SHA1／root:root／755及sync通过，但只读重挂载与一次安全收尾均EBUSY，进程退出1。后续仅只读取证：完整库95864B回读与候选逐字节相同，SHA256 `96650673fe19da1e5192086cbf9f6906f18c30340d5c3570abb312a19a9936c6`；/usr仍rw，进程518旧库有7段(deleted)映射，未运行新库。汇总`.local/incident409-20261101/loader-deployment-outcome.json`为PARTIAL，写入已完成而只读恢复／启动验收未完成；无重启、热初始化、杀进程、强制卸载或AP／CP／Backup写入。所有现场保留。下方E-365是此前失败，不代表最新文件仍为旧库。

2026-11-02：用户确认仅替换启动库、不自动重启。E-365为实际尝试失败回执`.local/incident409-20261101/loader-db81635a1045.json`，exit1：78文件摘要及剩余空间预检通过，Mac／RAM备份完成、同目录临时库创建及权限设置后，机身裁剪版`touch`不支持`-r`，停止于rename之前；`replaced=false`、mv命令0条，随后/usr封回只读并回读mounts确认。保留临时文件与现场，不清理、不重试、无重启。本地删除可选时间戳步骤后仅做离线计划检查；不记作已替换或设备启用通过。此前对该批“尚未连接相机”的描述限于T11e本地构建阶段。

最新用户反馈：资源修复后“恢复正常，但是没有自定义滤镜功能”。这是用户操作反馈，独立于此前脚本未执行MENU的回执。第49批已完成T11e本地启动库修复及审计，尚未连接相机或部署；整体继续`NOT_VERIFIED`。上次现场的512容量拒绝以及修复图像后旧摘要失配为两个已定位阻塞，不能据此承诺消除所有后续启动／握手问题。

| Evidence | 来源／命令 | 结果 | 边界 |
|---|---|---|---|
| E-360 | `software31/verify.py --recipe-bridge --capture-copies --bootstrap-only --output .local/fixed-custom-filters/loader-recovery-software-targeted` | exit0，62 passed，11.27秒；包含生产映射解析器及实际1090映射输入，生成UI／仓库等当前启动依赖 | 显式跳过不交付的AP／CP裸ELF编译探针；不执行ARM或模拟 |
| E-361 | 先前不带`--bootstrap-only`的相关宿主检查，`loader-recovery-software/commands.json` | exit1，916 passed／22 skipped／3 fixture errors，147.69秒；缺失已被清理的`R5ColorLab/scripts/edit_raw_front.py`等参考资料 | 不计完整回归通过，不为通过测试伪造历史输入 |
| E-362 | `packaging406/build_and_audit.py`，输出`loader-recovery-package/verification.json` | 当前42窗AP SHA为`8b34f12d4314a6aa829e14d17971c154575c68ae1d11c4573798f13a860d069a`，请求模块与现机取证副本相同 | 静态来源／配对预检；未改AP文件或相机 |
| E-363 | `packaging406/loader/build_loader.py`，输出`loader-recovery-library/{compile,verification}.json` | exit0，实际AArch64 Linux DSO 95864B，SHA256 `96650673fe19da1e5192086cbf9f6906f18c30340d5c3570abb312a19a9936c6` | 仅交叉链接，未执行目标库；非新DAT |
| E-364 | `.venv/bin/python -B .local/incident409-20261101/audit_loader_recovery.py` | exit0；实际ELF的Region数组49152B／2048项、BSS增加36864B；导入／导出／版本／依赖相同，71项编译资源表仅2图像变化且匹配机身修复；现机AP／三依赖库相同，源指纹均保持 | 独立只读比较历史机身备份和当前本地产物；不是当前设备运行验收，部署前仍需新身份／空间／属性预检 |

实机故障后新增授权修复证据：两份UXD复杂图像偏移缺陷已在本地复现并修正，4项定向通过、两份真实输入各3511载荷保持。用户批准整文件回退尝试因ENOSPC停在临时文件阶段，正式文件未替换；随后单独批准60处共240字节原位修复和本次临时文件清理，实际SSH回执`.local/incident409-20261101/offset-bbc1f47607e0.json`退出0，最终整文件SHA1与本地修正版一致，sync及/usr只读确认。未重启、未测试MENU，不能标记菜单恢复或完整滤镜通过。用户明确前期取证为重开机未按MENU的USB MSC现场。原4.08／4.09包仍有缺陷，继续停止试用；详见同目录故障README和主线记录。

第48批按用户授权将照片标记扩展并入新4.09，见[integration-48-photo-markers.md](integration-48-photo-markers.md)。T11d本地封装完成，原4.08保留；不声明实际照片标记叠加或设备通过。

| Evidence | 来源／命令 | 结果 | 边界 |
|---|---|---|---|
| E-354 | `test_unsigned_staging/test_aspect_merge/test_candidate_preflight/test_recipe_build_pair` | 45 passed，2.57秒，exit0；显式schema3／42窗、来源／范围／严格布尔及原AP内存精确逆转 | 无ARM执行或模拟；记录于`implementation48-prechecks` |
| E-355 | DAT专用环境：`test_upgrade_package.py`及`a7r5-dat-tool/tests/test_tool.py` | 42 passed，1.26秒，exit0；新版本／标记范围配对与原容器回归 | 临时测试身份；非设备升级 |
| E-356 | `test_marker_bootstrap.py` | 5 passed，5.55秒，exit0；生产canonical函数＋真实SHA宿主执行，完整原AP／标记窗、漏逆窗和篡改拒绝、旧7窗保持 | bootstrap机器码为明示夹具；不称真实ARM执行 |
| E-357 | `implementation48-software/verification.json` | 903 passed／22配置skip，151.53秒，exit0；395源与五项配对产物一致，产品产物保持4.08 | 复用未变CP原生构建指纹，不重跑硬件／指令模拟 |
| E-358 | `implementation48-package/loader/manifest/usr` | 实际42窗AP及完整启动校验DSO、70资源／4模块，USR完整树／inode保持、e2fsck0 | 标记实际叠加保持False；阶段回执不冒充设备结果 |
| E-359 | `implementation48-upgrade409/verification.json`及`implementation48-final/verification.json` | 实际完整4.09 DAT验签／独立解密／完整解包／导出通过，SHA256 `18d9093c5abb20e5aa576aae832d46f28b96a119bb51841643ef434ea32e9d19`；相对4.08 AP只多35窗、仅AP／启动模块变化、CP相同，原4.06与4.08完整SHA保持；九组多基址静态分支核对 | 公开研究签名非官方；照片标记呈现、机身接纳与成像／介质未验收 |

第47批已实际完成研究升级包及独立回读，详见[integration-47-upgrade-package.md](integration-47-upgrade-package.md)。T11c完成本地封装范围；整体NOT_VERIFIED和T12设备边界保持。以下历史批次的“无完整DAT”只描述当时代码状态。

| Evidence | 来源／命令 | 结果 | 边界 |
|---|---|---|---|
| E-349 | `implementation47-software-release/verification.json` | 903 passed／22 skipped，149.61秒、exit0；392源／5产物一致，AP／CP配对编译 | 跳过项为配置不适用；未执行ARM或模拟 |
| E-350 | `implementation47-multibase-components-final`、`implementation47-matrix9-layout`及`implementation46-final-native-v5` | 233项模块、123场景ASan／UBSan通过；实际RX39192／40960、静态RW48744／49152；51挂点1280B合同、69窗口正逆 | BW／SE仅接受每区三端点相同；无泄漏检查，完整Gamma格式及全基底模型不扩展 |
| E-351 | `implementation47-release-usr`、`implementation47-cp-stage-v2` | USR完整树／inode及e2fsck0；CP／FAT独立簇链回读及反向还原；当前同源AP／70资源／4模块 | 阶段回执的不可安装状态不冒充最终DAT结论 |
| E-352 | `a7r5-dat-tool/.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests/test_upgrade_package.py a7r5-dat-tool/tests/test_tool.py` | 36 passed、exit0；包含拒绝源变更、容器范围及正常签名工具回归 | 单测使用临时测试身份，不执行设备更新 |
| E-353 | `implementation47-upgrade408/verification.json`及导出目录`export-verification.json` | 754525608B完整4.08研究DAT；SHA256 `d7763345b1897a85d93b0493576536995c6ae122a11fa69b8dc1bcb034bed413`；验签／独立解密／再次完整解包／导出副本完整SHA通过，仅CP／USR／sum改变 | 相同公开研究身份，非官方签名；机身接纳／SD／掉电／EVF与JPG像素未验证；不改变设备信任规则 |

最终来源／导出／文档审计记录于`.local/fixed-custom-filters/implementation47-final/verification.json`。复用相同代码状态的行为证据，不重复执行903项或完整封装。

当前第46批的实际源码及离线接线见[integration-46-capture-flow.md](integration-46-capture-flow.md)。普通Capture请求、按值缓存与两次颜色重建已经接入；最终EVF源／YUV消费和JPG同Q四组件的已证条件链分别审计。整体保持NOT_VERIFIED，不把条件链扩为所有模式或像素验收。

| Evidence | 来源／命令 | 结果 | 边界 |
|---|---|---|---|
| E-346 | `experiments/software31/verify.py --recipe-bridge --capture-copies --output .local/fixed-custom-filters/implementation46-capture-flow-software-v4` | 786 passed／21 skipped，143.18秒、exit0；387来源相同，AP／CP／UI／仓库配对编译 | 21项为配置不适用；旧v1/v2/v3回执保留，不能作为模式保护修复后的当前结果 |
| E-347 | `implementation46-final-native-v4`及`implementation46-final-audit/target_sanitize.py` | RX38344/40960，静态RW48744/49152，heap63072；50hook／1176B合同，67窗口精确内存正逆；97场景ASan／UBSan（新target15＋342未变源上的既有82） | 首次脏堆、ID换代及旧／未知模式误授权均复现后修复；当前R150必须0；仅同次CP启动heap合同，不写镜像／执行目标 |
| E-348 | `implementation46-evf-flow/v3`四份audit；`implementation46-jpg-flow/jpg_color_submit_audit.py`、`implementation46-jpg-gamma-alias/audit.py`、`implementation46-grid-consumer/audit.py`和`implementation46-grid-eligibility/audit.py` | EVF同R／真实DMM／YC／YUV／原引用链；JPG同A／同Q颜色寄存器、实际Gamma银行CPU消费、1620B同步SRAM上传和默认ST强度来源均有固定原字节／CFG／pins | 原动态Connect、stage／mask、后端child、fresh/snapshot及原回退条件均保留，不声明每种变体逐帧四组件一致、物理像素或DMA最后引用 |

最终总审计路径在本批接入文档维护；原DAT、CPIO、USR三份完整SHA均与基线一致。完整Gamma格式未扩大；不以新增测试数量代替功能完成率。

当前第45批完成T03f2b限定软件生命周期及T08gamma45研究对照，见[Capture与第二Gamma接入](integration-45-capture-gamma.md)。真实八门、两通道mode1、原后处理及最终A回池已接入；同次CP启动的heap合同、最终像素与完整Gamma格式边界保持。整体仍为NOT_VERIFIED。

| Evidence | 来源／命令 | 结果 | 边界 |
|---|---|---|---|
| E-343 | `experiments/software31/verify.py --recipe-bridge --capture-copies --output .local/fixed-custom-filters/implementation45-capture-gamma-software-v2` | 710 passed、18 skipped，135.67秒，exit0；381来源相同，AP／CP请求、UI及仓库库配对链接 | skip为旧配置不适用；首次699 passed／18 skipped／10 fixture errors保留，不计通过；无目标执行 |
| E-344 | `.local/fixed-custom-filters/implementation45-capture-gamma-final/audit.py`及`implementation45-capture-memory/final-v2` | RX32052／32768、静态RW48632／49152、490记录54880B；八门460B／30挂点988B合同，44窗口精确正逆；26场景ASan／UBSan；原三输入SHA一致 | 修复无资格原厂scope误关闭；同次CP启动普通堆合同，不支持同址热重建；不是EVF／JPG像素或相机验收 |
| E-345 | `tools/compare_gamma.py`与本批audit独立复算 | 恒等／暖调96预算、明暗／局部色384预算，均两臂同额；四组三份最终误差由真实C重新计算一致；11项新Gamma定向用例包含在E-343 | 固定ST/context4及PT经验近似、17结点和61440表示政策；暖调改善而明暗退步，AJR2/AJR3及机身准入不扩大 |

最终同源证据为`.local/fixed-custom-filters/implementation45-capture-gamma-final/verification.json`。第44批及更早行均保留为其各自历史代码状态，不能代替本次结果。

当前第44批T08sector44完成限定软件范围，见[16区矩阵接入与误差选择](integration-44-sector-matrix.md)。AJR2兼容、AJR3/新能力/35帧、现有持久化、原sector入口及完整参考预测已经接通；默认仍AJR2。完整Gamma、Capture生命周期、第二域实际应用与最终EVF/JPG仍未完成，整体NOT_VERIFIED。

| Evidence | 来源／命令 | 结果 | 边界 |
|---|---|---|---|
| E-341 | `experiments/software31/verify.py --recipe-bridge --capture-copies --output .local/fixed-custom-filters/implementation44-sector-software-v3` | 645 passed、6 skipped，108.31秒，exit0；366项来源相同，配对目标和仓库库链接 | 首次崩溃/容量失败和第二次夹具编译失败均保留，不计成功；当前包含实际新AP/CP入口和原厂退出回归，无目标执行 |
| E-342 | `.local/fixed-custom-filters/implementation44-sector-final/audit.py`、本批预检与loader | 6组同预算模型复算；20000份损坏AJR3的ASan/UBSan；28窗口精确正逆；原3输入SHA一致；RX27508、RW静态48456/49152、启动库90184B/required1f1fff | 固定ST/context4＋PT近似，部分16区尾误差增大；无完整CP/USR/DAT更新、安装或像素准入，`camera_apply_allowed=false` |

当前第43批完成兼容现有AJR2/AFD1的电脑拟合器，见[实现及误差边界](integration-43-desktop-fit.md)。固定参考域的CUBE→整数拟合→文件导出→现有服务保存/导出/回导/恢复已有执行证据；没有修改原生固件代码或更新CP/USR/DAT。16色相区、完整Gamma与最终EVF/JPG仍未完成，整体NOT_VERIFIED。

| Evidence | 来源／命令 | 结果 | 边界 |
|---|---|---|---|
| E-339 | `experiments/software31/verify.py --recipe-bridge --capture-copies --output .local/fixed-custom-filters/implementation43-desktop-fit-software` | 633 passed、6 skipped，114.62秒，exit0；364项来源相同，配对AP/CP目标与动态库链接 | 新5项电脑拟合/取消/报告重放/现有服务导入，宿主与编译；不执行目标 |
| E-340 | `.local/fixed-custom-filters/implementation43-desktop-fit-final/audit.py`与三类4096预算对照 | 3组成品及基线/选优/最终误差复算，原3输入完整SHA一致；复用CP构建源及载荷摘要核对通过 | 512训练/25选优/18测试，ST/context4＋PT经验残差；两例改善一例保持，非照片精度，不新增机身准入 |

当前第42批E-337/E-338见[Gamma版本传递](integration-42-gamma-handoff.md)及[最终审计](../../../.local/fixed-custom-filters/implementation42-gamma-handoff-final/verification.json)：628项宿主回归、6项不适用skip，102.58秒/exit0；361项来源相同，目标RX26780、静态RW48136、18挂点432B合同，原288B包装区/408B启动尾不扩大，28窗口内存精确正逆及固定输入摘要通过。只完成T03f2a来源复制子范围；未开启mode1、未证明最终两输出或更新安装镜像。

| Evidence | 来源／命令 | 结果 | 边界 |
|---|---|---|---|
| E-337 | `experiments/software31/verify.py --recipe-bridge --capture-copies --output .local/fixed-custom-filters/implementation42-gamma-owner-bound-software` | 628 passed、6 skipped，102.58秒，exit0；361项源码冻结及配对目标链接 | 宿主与交叉编译；无ARM执行、硬件模拟和设备访问 |
| E-338 | `.venv/bin/python -B .local/fixed-custom-filters/implementation42-gamma-handoff-final/audit.py` | 固定输入、同源模块与18挂点、28窗口精确内存逆转、5份静态CFG审计通过 | 主构造至shadow身份；Capture实际版本、第二域应用、最终EVF/JPG像素及最后图像引用未关闭 |

本节对应[tasks.md](tasks.md)的M1～M4。原REQ/AC及已有E-000～E-194不删除；旧批次结果按各自代码和夹具范围使用。规划后已进入实际实施，当前来源、完整链路及限制见[主线记录](mainline-progress.md)，不能将旧规划回执当作本轮执行结果。

当前第41批E-335/E-336见[双入口接线](integration-41-dual-entry.md)及[最终离线审计](../../../.local/fixed-custom-filters/implementation41-dual-entry-final/verification.json)：619项宿主回归、6项不适用skip、配对目标编译链接和13项加载边界通过；367个来源一致，新USR74组件和AP七窗口独立回读／逆转、e2fsck0，原输入保持。T09c只完成源码／宿主／准备产物范围，实际菜单、介质和成像仍未验收，整体NOT_VERIFIED。

第40批E-320～E-334与565项按[历史接线](integration-40-native-and-ui.md)保留。该批一次误执行旧Unicorn的偏差DEV-001不删除；本次第41批没有指令模拟，不用本次范围改写历史。

| 里程碑 | Acceptance范围 | 主要可执行证据 | 本次状态 |
|---|---|---|---|
| M1 / T03g,T07e,T03f | AC-001, AC-002, AC-003, AC-007, AC-008, AC-010, AC-011, AC-012的对应子范围 | 原上游有效上下文→完整颜色包装器/Gamma选择；C07的AP输入/原消息/CP整组应用；ST/FL2/FL3保持；真实流/参数版本/最后借用者关联及失败 | NOT_VERIFIED；E-320～E-331已接实际消息、不可变C4/worker借用、主Gamma/颜色/网格入口及明确原厂退出；最终EVF/JPG输入身份与第二域仍未闭合，不将CPU最后读取当最后图像帧 |
| M2 / T08b2d4,T08b2d5 | AC-002, AC-005, AC-006, AC-007, AC-008, AC-010, AC-011, AC-012的对应子范围 | 当前CP完整模型来源/域/基底，恒等与非平凡LUT；量化组合的独立留出、灰阶/肤色/裁剪及单网格对照；完整候选到原消费者/缓存/寿命 | NOT_VERIFIED；完整ST参考近似／17维联合拟合／AJR2及原selected record主域源码接通；其他基底完整同条件资产、本机照片域与误差、第二域应用未覆盖，camera_apply_allowed=0不改 |
| M3 / T06d,T05b,T08b3b,T09b,T09c | AC-001, AC-002, AC-003, AC-004, AC-005, AC-006, AC-007, AC-009, AC-010, AC-011, AC-012, AC-013的对应子范围 | 原AP菜单与双入口文件/存储适配；浏览→转换或完整配方校验→保存/导出/回导→新目录恢复及取消/失败 | NOT_VERIFIED；619项当前宿主回归及13项启动边界通过；C01/C07完整转换／保存／发送、C06墓碑恢复原生、无模型的电脑配方导入均有源码及宿主证据；实际画面、机身介质/掉电与最终成像未验收 |
| M4 / T10,T11 | AC-000～AC-012全部必要离线部分 | 旧六槽兼容，12原厂及继承功能、资源/失败/预算、前像/白名单与精确回退；按变更范围集中相关回归和最终整包审计 | NOT_VERIFIED；T11c完整4.08研究DAT验签／独立解密／完整回读已通过，CP39192B RX／48744B静态RW、69窗口正逆和USR完整树／e2fsck0；完整基底预测模型、特殊模式和设备验收未完成 |
| T12 | 各AC中的真实设备部分 | 真实启动、SD/换卡、重启/掉电、取景/JPG样片及资源稳定性 | MANUAL_REQUIRED；当前未授权，禁止执行 |

当前第38批见[integration-38-native-bridge.md](integration-38-native-bridge.md)：完整配方已接原消息入口源码；原SOLID四页保留的新放置方案已通过离线准入验证，旧4KiB不足不再描述当前布局。实际原生消费者绑定、完整VD/C4同次输入及本机颜色/设备验收仍未完成；UI发布和安装门槛保持关闭。第37批的转换／保存证据按其代码范围保留。

### 第38批执行检查点

| Evidence | Code State / Step | Result | Scope |
|---|---|---|---|
| E-307 | `af_runtime_ap406/af_runtime/af_cp_recipe406/af_hs_cp406`、`test_ap_recipe_sender/test_cp_recipe406/test_recipe_actual_ingress` | 真实C入口同进程贯通完整28帧、共享版本、源／能力／旧包拒绝、待决／确定决定／ACK；原END截止误成功复现并修复 | 原系统服务为显式主机端口；软件prepared非像素，未知IO固定拥有权；无实际消费者不协商 |
| E-308 | `recipe_pairing`及`test_recipe_build_pair` | 软件／AP请求／加载器／冻结开关严格配对，旧缺字段按关闭，混用及非布尔拒绝 | 可选构建`AF_RECIPE_BRIDGE406`，不放开UI／安装 |
| E-309 | [carve最终构建](../../../.local/implementation38-placement/carve-link-v8/verification.json)、[实际放置](../../../.local/implementation38-placement/carve-link-v8/memory-plan.json)、[独立复核](../../../.local/implementation38-carve-safety-review/audit.json)及`test_cp_carve406` | 原SOLID尾扣四页，RX9164/12288／RW292/4096／永久尾408；TTBCR／TTBR／coarse池／4页PA与W^X／整CRC后Icache及phase2；10窗口内存正逆和旧六FNV保持 | C参考执行与实际Thumb静态分开，未运行目标；v1/v2缺最终核验已作历史，v3～v7容量失败保留；未安装CP |
| E-310 | [原C4／Gamma身份](../../../.local/fixed-custom-filters/implementation38-native-identity/README.md)及[有限source别名审计](../../../.local/snapshot-prefix-escape/README.md) | 静态确定49个C4指针字段、VD_Pre/Post真实header关联、两套Gamma、母C4八类提交及已审叶函数最后同步读 | 未闭合完整prefix退休／原生四组件消费；不把诊断16位计数当帧号，不要求所有AE/WB同私有版本，不用nofree池冒充可持续运行 |
| E-311 | [最新统一构建](../../../.local/fixed-custom-filters/implementation38-final-software/verification.json) | 402 passed in48.46s，退出0且前后源码一致；动态UI126312B及后端572552B不变，AP研究92128B／CP研究86420B编译链接成功 | 仅主机与交叉链接；前一次402/61.51s后AP动态库完整链接缺decode依赖已修，最终以此源及独立动态预检为准；未模拟或设备 |
| E-312 | [AP动态预检](../../../.local/fixed-custom-filters/implementation38-package-v2/verification.json)及[当前加载器](../../../.local/fixed-custom-filters/implementation38-loader/verification.json) | 当前配对桥AP动态请求49520B／12RELATIVE；原7AP窗口／132前像／57研究钩和16来源窗通过；启动库82440B编译链接 | 新增完整传输不产生准入；native consumer仍无绑定，原输入与CP文件不写 |
| E-313 | `af_cp_input406`、`af_cp_copy406`、`af_cp_override406`及对应host／fault测试；[独立审查](../../../.local/snapshot-copy-review/fixed-review.json) | 固定3来源336B、复制前busy／后发布、source epoch／真实VD校验；实际C复制中故障及发布后故障关闭公开资格，原copy始终一次 | 只证明输入历史及读资格；不保护整个原E70寿命，不代表原bank／图像退休 |
| E-314 | [真实VD来源CFG](../../../.local/input406-hook-sites/vd_cfg.json)、`test_cp_carve406`、[三模式最终回执](../../../.local/input406-hook-sites/DELIVERY.json)及[copy分支最终构建](../../../.local/input406-hook-sites/complete-capture-copies/verification.json) | 主／次原函数完整控制路径固定SP+B0／14；四原BLX改BL到同一phase回退，原LR、SP+C8／2C、实际ELF分派及原厂尾委派通过；RX12268／12288、RW628、tail404；三模式正逆还原原CP SHA，旧六三段及FNV保持 | 纯静态和内存正逆；含公开read_input ABI，无实际native consumer；没有运行ARM／设备 |
| E-315 | [当前统一回执](../../../.local/fixed-custom-filters/implementation38-copy-source-software/verification.json)；`verify.py --recipe-bridge --capture-copies` | 431 passed in68.02s，exit0，334个源文件前后指纹一致；UI与后端字节保持，AP研究92128B／CP研究91848B，AArch64／Thumb均链接 | 当前copy分支软件集成；原402项为前一检查点，不把固定地址研究ELF当真实carve装载或相机结果 |
| E-316 | [三段copy后写者审计](../../../.local/copy-postwrite-review/README.md)及其`verification.json` | 三copy→AFD2DA完整区间及辅助函数不改九值/DC0；canonical来源、原task91同步回调桥及已识别提交串行，静态audit exit0 | 支持固定入口单写者契约；gate外仍有canonical header写者，不是全系统live-buffer或退休证明 |
| E-317 | [永久门禁与旧六等价候选](../../../.local/fixed-custom-filters/implementation38-native-identity/BOOT-PERMANENT-GATES.md)、[Gamma栈复用](../../../.local/fixed-custom-filters/implementation38-native-identity/GAMMA-OUTER-REUSE.md) | 仅.local候选198B/原288B释放90B、4gate＋grid回退实际布局、原BL/LR保持、11140例整数逻辑及静态audit exit0；Gamma可复用616B真实outer栈 | 尚未并入生产或绑定native目标；旧六生产字节未改。header padding假设已被异常向量反证否决，新增容量0 |
| E-318 | [原银行发布屏障审计](../../../.local/implementation39-native-owner-barrier/README.md)及其`receipt.json` | frontend597／Pre3417／secondary1478／Post635条CFG与40条pins；确认timeout／部分pending仍能发布，Gamma与color独立翻转，static audit exit0 | 用户已于2026-10-31选择沿用原厂分组更新与回退；接受部分失败时暂时新旧组件并存，不另改原发布器。输入来源／数据借用及成像接入门禁保留 |
| E-319 | [最终源身份审计](../../../.local/fixed-custom-filters/implementation38-copy-source-software/final-source-audit.json) | 当前334源及实际copy构建指纹一致，原修改版DAT／CPIO／USR三个完整SHA均匹配 | 原输入保持；未写完整CP/DAT、未安装或设备操作 |

### 第37批当前证据

| Evidence | Code State / Step | Result | Scope |
|---|---|---|---|
| E-297 | `af_joint_basis.*`、`af_import.c`及`test_joint_basis/test_import_basis_binding/test_repository_basis_integration`；E-301统一回执 | 17维明暗／共享矩阵／共享CC1及残差网格分批搜索，seed重建、完整量化选优、取消和失败不发布通过 | 实际IMPORT编译路径，保留原8参数／AJR1格式；不将求解器正确等同机身颜色正确 |
| E-298 | `af_reference_joint/domain/assets/samples.*`，固定`reference-context4.bin/json`，E-301 | 377304B固定数值资产校验与实际参考构表／像素、显式域和schema2精确配对查询通过；9³采样859次／689唯一，512训练／43验证、区域不重叠 | q/16383来自固定上游预览约定；ST参考与PT经验网格显式外推，研究资格保持，有限色组代理不是实拍标定 |
| E-299 | `af_reference_import.*`及`test_reference_default_import.py`、`test_loader_reference_binding.py`；E-301/E-302 | 无预测器注入的实际默认service装配→中文CUBE转换／保存→删除源／关闭重开恢复；启动`open→library→reference→caps→UI`及失败不误报能力通过 | AP实际源接线与主机文件服务；没有声称实际SD、机内掉电／启动或其他基底精度；UI发布和原CP准入仍关闭 |
| E-300 | `af_recipe_transport.*`、`af_repository_recipe.*`、驻留解码工作及`test_reference_to_receiver.py`，E-301 | 同一参考完整配方保存／恢复／dirty快照→BEGIN＋26DATA＋END→拥有副本／校验／软件ACK，损坏／错序／会话／陈旧／唯一借用／拒绝ACK通过 | 新研究A7R1，无私设Sony消息号；未接实际handler，ACK是软件提交而非照片生效或最后帧释放 |
| E-301 | [最终软件回执](../../../.local/fixed-custom-filters/implementation37-delivery-software/verification.json)及完整输入／命令指纹 | 370 passed in57.20s，退出0，前后源码一致；动态UI126312B保持，后端572552B／`1e99a97d…e53c79`、AP82688B、CP研究81752B编译链接成功 | 主机契约与AArch64／Thumb编译链接，无ARM执行、QEMU／Unicorn／设备；早期340／368回执仅历史，不代替最终状态 |
| E-302 | [当前加载器构建](../../../.local/fixed-custom-filters/implementation37-delivery-loader/verification.json)与`test_loader_identity/test_storage_binding/test_media_binding/test_fsys_codec_mapping` | 编译链接80728B／`8e7f7898…bb54`；当前构建13项宿主检查通过，2.74s，退出0 | 复用匹配UI／AP字节的原预检，未放宽身份；无目标执行或新USR／CP／DAT安装产物 |
| E-303 | [原生静态路由审计](../../../.local/fixed-custom-filters/implementation37-native-routing/README.md)及`evidence.json` | 18来源／7完整窄窗；确认post-packed候选719f12／719f1a、S+20指针／S+24有效，纠正saved-copy条件；Gamma独立C4→shot路径 | 静态证据；没有安装gate、同步／排空或最后图像引用证明，跨阶段同版仍未通过 |
| E-304 | [紧凑空间实测](../../../.local/fixed-custom-filters/implementation37-cp-space-v2/verification.json)及[参考放置审计](../../../.local/implementation37-cp-placement-reference/verification.json) | `-Oz`无未解析helper，原4096B容量真实链接拒绝；测量RX7376B／RW288B；11公开文本Git blob＋4当前CP窄窗审计 | BLOCKED：扩大RX侵入L1、冷源侵入旧六FNV；上游代码区覆盖本包六网格，heap权限不明。测量ELF不可安装，不修改原包 |
| E-306 | [当前组合预检](../../../.local/fixed-custom-filters/implementation37-package/verification.json)、[USR准备镜像](../../../.local/fixed-custom-filters/implementation37-full-unsigned-usr/verification.json)及[独立回读](../../../.local/fixed-custom-filters/implementation37-final/image-readback.json) | 旧来源正确拒绝后重新构建／冻结；新USR410652672B／`b38f6371…df540`，7AP／70资源／4DSO、1043→1047，e2fsck0，74组件实际回读／7窗口逆转 | 普通文件离线准备；原inode和无关内容保持，CP不变、UI不发布，不是可安装DAT |

最终输入与文档／暂存区核对见[E-305收口回执](../../../.local/fixed-custom-filters/implementation37-final/verification.json)。DAT、CPIO及USR已重新算SHA256，与锁定基线一致；未生成可刷写包。T08b2e／T08b2d4b／T04b2e／T08b3b2仅关闭各自软件子范围，父项和总体仍为NOT_VERIFIED。

### 检查点及证据失效规则

- T03g可先记录完整参数消费检查点，但M1整体仍等待T07e/T03f；原函数返回不等于流/照片或最后引用已经确认。所有物理通信/RTOS/ISP服务边界单列，不造完成回执。
- M2必须有显式完整真实后端。独立误差报告须标出基底、参考八项参数、模型/固件摘要和适用域；模型内误差、模型自身偏差和实拍分列。误差准入与机身预算缺证时保留未确认状态，不能以合成零误差关闭AC-005/AC-006。
- M3逐项核对画面、原输入、成像确认和保存回执；完整客体、真实存储接口或容量证据缺失即记录对应缺口。隔离介质后端不证明物理卡、掉电或实际可用空间。
- 一个共享行为选择一个主要测试层，独立层间风险再补边界测试。阶段内不为每个字段重复整套命令；相关源码/编译产物/输入变更只使受影响证据失效；阶段结束集中一次集成，最终集中一次相关回归。
- 输入、审计器及其相关依赖未变时可复用验签、全部帧和归档来源证据；不能因为省时省略变更后的接入/故障验证。原批次含全源码快照的回执，只复用本次确认仍匹配的行为范围。
- 每次交付按“本次完整链路结果、未通过/未运行边界、阻塞所需最小输入、下一任务”记录。关键目标未达成时不以新增测试数或新子任务数量替代进展。

### 本次规划更新的V0核对

| Evidence | Code State / Step | Result | Scope |
|---|---|---|---|
| E-194 | 本次五份spec、规划前快照及第二十四批代码指纹；`mainline-plan-20261026.json` | V0核对需求/验收/任务/验证引用、任务ID和依赖、原勾选状态、文档链接/空白及功能代码不变 | 仅规划；M1～M4未执行，整体仍NOT_VERIFIED；不重跑代码未变的247项回归或同包审计 |

回执见[本次规划结构与范围核对](../../../.local/fixed-custom-filters/mainline-plan-20261026.json)。本次文档指纹与历史E-193的文档快照不同；代码指纹仍匹配时，既有相关行为证据保持有效，不把历史文档指纹称为当前文档指纹。

### 主线实施证据

| Evidence | Code State / Step | Result | Scope |
|---|---|---|---|
| E-195 | `cp_context406.py`、`cp_gamma_source406.py`及`native_joint.collect`，来源见`cp-load-25.json`，完整结果见`mainline-native-25.json` | PASS；原运行期状态生产器→原颜色初始化/完整包装器→同C4源Gamma选表/构造；12基底×2组参数×2银行共48组；现有联合/组件目标联验保持，9.728秒 | 原字段复制/外层Gamma格式化为明确窗口；运行属性/校准为夹具，原缺查询记录返回4；不含真实域、ISP、EVF/JPG或最后帧 |
| E-196 | `af_ap_ui.c/.S/.h`与动态链接脚本；`ui-mainline25/verification.json` | PASS；非零基址、41处前像/描述符、未绑定/失败拒绝、21原首指令回跳及3原BL目标；默认基址0的24处分支联验保持 | 动态绑定和原返回路径，不代表完整GUI或成像；基底编辑保持禁用 |
| E-198 | 固定同4.06源归档和`backup.ko`，`storage-mainline25/storage-evidence.json` | PASS（只读子范围）；4项来源和原Data_SearchId四例，保留输入表；确认可写VFAT配置与未知ID拒绝 | ET_REL偏移不是AP VA；未选定私有机内目录、未证明当前容量/同步耐久性，T02/T05b未完成 |
| E-199 | 当前`native/a7filters/tests`源码，`pytest-mainline-25.json` | PASS；256 passed in 10.34s，退出0，命令期间源码未变 | 本功能核心回归；完整客体/实验装载器和相机验收另列，不冒充端到端成像 |
| E-200 | 两仓库固定提交、`reference26-a7c2/source-manifest.json`、`reference26-r5/fetch.json`与公开原报告 | PASS；A7C2数值快照与R5 Edit运行表/阶段向量存在并核对；来源审查独立复算46缓冲和Gamma数值 | 修正此前笼统“无公开runtime”判断；A7C2不是R5，Edit虚拟原生捕获不是相机；未执行上游脚本 |
| E-201 | `af_edit_reference.*`、`af_edit_chain.*`、`reference_snapshot.py`及固定数值夹具；`reference26-r5/seven-operators/verification.json`、`build-edit-chain26/a64-execution.json` | PASS；七整数颜色算子及49152字节工作区的颜色子链，AArch64实际执行；单色patch逐字节相等，中途错误不发布 | 每阶段仅1种重复颜色；矩阵仅960内部像素主张原捕获一致；不含空间处理、sRGB桥、残差位置或机身照片 |
| E-202 | `pytest-mainline-26.json`所列中间源码指纹 | PASS；279 passed in 12.08s，退出0，命令期间源码未变 | 原调参页新发现的三入口修复之前的检查点；颜色及参数桥范围可复用，后续UI须补最终验证 |
| E-203 | `ui-mainline26/gui-verification.json`、`parameter-view/verification.json`及`ingress-verification-late.json` | PASS；30挂钩/48前像、33项定向和10项近远/迟注册；完整4.06客体32项导航/双向回绕、C07真实八项工作编辑/返回保留，93原始帧与PNG一致，Qt/QMP退出0 | 两份00组image UXC追加14编号图标，原记录/像素保持；固定名/C07内存夹具；动态名、基底、保存/取消、CP和六槽迁移未验收，T06d未完成 |
| E-204 | `af_edit_gamma_bridge.*`及本包锁定CP；`build-edit-chain26/gamma-native-consumption.json` | PASS；新AArch64参数轴桥→原CP完整Gamma构造6组，ST/FL2/FL3两列；128共同点保持18位、补61440、原元数据保持并精确撤销 | 参数坐标适配与匿名曲线消费；不写原厂机身槽、不证明实际sRGB/像素输入尺度或本机色差 |
| E-205 | 30处挂钩/三调参读取入口及全部当前核心，`pytest-mainline-26-final.json` | PASS；280 passed in 12.68s，退出0，命令期间源码未变 | 当前功能核心回归；替代E-202中已变化的UI范围；完整客体/实验装载器另有独立回执，相机验收未运行 |
| E-206 | `ui-mainline27/gui-verification.json`、`base-view5/verification.json`及`ingress-verification-late.json` | PASS；34挂钩/56前像，117原始帧与PNG一致；完整32项/双向回绕，十二基底含FL2/FL3、八值保持、焦点和图标随工作基底变化，Qt/QMP退出0 | 动态名称集成前的已冻结中间模块，非最终名称构建；C07仍是内存夹具，不含机内保存或CP应用 |
| E-207 | `reference27-r5/final-module-evidence.json`、`context-build/verification.json`及各`a64-execution.json` | PASS；完整Gamma/主逆表/有效次逆表和552B矩阵配置/73728B表逐字节匹配公开context4；事务候选Gamma/矩阵/CC1影响参考链，取消/失配不发布，输出拥有全部表，宿主与AArch64实际执行 | 显式Edit域，输出502544B/工作707896B；公开单色patch，不含sRGB桥、残差位置、完整AfJointModel或本机ISP |
| E-208 | `persist-label27/verification.json`与列出的C/测试指纹；60项定向模块及`test_native_pipeline.py`两架构 | PASS；普通目录切基底/保存/重命名/另存/恢复，名称仅从匹配的已校验记录发布，uncertain保持、显式旧副本恢复和清空隔离；60 passed in 2.96s，AArch64/ARMv7实际执行2 passed in 0.84s | 60项含参考表范围；目标架构使用明确内存后端，普通目录/缓存桥不等于原厂保存动作、机内文件服务或掉电验收 |
| E-209 | `names-mainline27/module-view6/verification.json`、`gui-English-locale-verified-partial.json`、`gui-fonts-reset-verification.json`及`implementation.md` | PARTIAL；38挂钩/66前像/35原目标，36项定向/非零装载；139+101原始帧/PNG一致、Qt/QMP均0；32项/双向回绕、十二基底/八值、两页英文标题/同槽刷新/编号回退，以及真实Reset取消/确认后690+163原数组值保护通过 | 英文locale中文字形FAIL；恢复同包被tmpfs遮蔽的中文字体不等于跨语言fallback，中文locale像素未验。内存文档夹具，不含机内保存/CP；原基址0 collector明确排除三名称入口，由非零装载与完整客体另验，T06d不勾选 |
| E-210 | `pytest-mainline-27-final.json`，当前38挂钩/66前像的核心源码指纹 | PASS；321 passed in 14.88s，退出0，执行前后核心源码一致 | 本功能相关核心回归，替代E-205受影响范围；完整客体帧、实验装载器和设备验收分别列证据 |
| E-211 | `reference27-r5/integration-review-evidence.json`及只读复算脚本 | PASS（数据锚点及邻域子范围）；本包CP ST第6列纵值摘要与公开预设一致，Edit128共同点32×轴/2×纵值；CC1排列/后四×2、矩阵96项打包对应与20项语义差异；AArch64 width1拒绝不发布、width5常色成功 | 未把第6列命名为EVF/JPG；不将运行属性夹具视作本机真实矩阵/CC1，不提供完整AfJoint后端或sRGB桥 |
| E-212 | `ui-mainline27/save-entry-evidence.json`、`save-entry-review.md` | PASS_STATIC_ONLY；14前像、48条原六槽绑定及19指令窗口复算，确认Reset旧数组风险与原Backup后台写入口 | 保存/另存需新增明确菜单动作；原通知→后台唤醒/耐久完成未执行，不宣称原函数返回即落盘 |
| E-213 | `af_edit_cp_gamma.*`、`test_edit_cp_gamma.py`；`reference27-r5/cp-gamma-adapter/verification.json`及`baseline-audit.json` | PASS；宿主5项与AArch64实际11项，原576B/轴摘要绑定，基线及非零CP候选→自含128点X/Y；61440独立变化/不可表示、坏源/非单调/别名/首末取消不发布；输出1024B、无外部work | 新增独立桥与定向证据，E-210既有321项来源保持，未重复未变化的旧核心；既有18位坐标桥不变，不含sRGB/其他基底/EVF/JPG或完整联合模型 |
| E-214 | `final-integration27.json` | PASS（V0）；代码来源/指纹保持、94份Python AST、100处本地引用、父项未误勾选、暂存区空及本任务客体无残留 | 仅离线整合核对，E-209仍PARTIAL、整体NOT_VERIFIED；未操作设备或生成安装包 |
| E-215 | `ui-mainline27/language-entry-evidence.json`、`language-entry-review.md`、`names-mainline27/font-provenance.json`及`font-language-native-partial.json` | PARTIAL；静态0x75b getter/setter/启动/Backup及34银行行复核；同源字体和原资源查询对应FONT_S_CHINESE/简中资源银行 | 未执行未知语言值的setter，不将调试枚举排列、字体namespace0x33或B9B资源银行当完整语言模型映射；中文locale字形及跨语言fallback仍未通过 |
| E-216 | `continuation28-names/gui-chinese-verification.json`、`locale-recipe.md`及冻结module-view6 | PASS（中文名称范围）；原语言确认路径／同包三个字体，70原始帧与PNG像素一致，61Qt操作、Qt/QMP退出0；两页“暖光·城市”及刷新／墓碑回退／八项保持 | 原语言模型为明确离线夹具；不写个人Backup，不声称跨语言fallback；新管理菜单须同一新构建另验，E-209失败现场保留 |
| E-217 | `af_media/repository/repository_service`及`test_native_media/repository`；`continuation28-storage/target/os-independent-check.json`、六阶段`os-execution.json`；新`continuation28-media-os/run-20261027-095949/os-execution.json` | PASS（后端子范围）；宿主4+5项；同版AArch64内核/glibc2.25真实fd／保存／独立进程恢复／坏槽隔离，双遍修复另验同inode-size-mtime覆盖拒绝、取消保持和32768B稳定摘要，QMP退出0 | 私有16MiB RAM目录，不等同机内位置／实际空间／掉电；旧OS媒体范围早于双遍修复。完整导入接口的合成模型仅测接线，service只开放纯参数cap0x0b |
| E-218 | `continuation28-menu/gui-confirm-v1.json`、`gui-final-v2.json`及两次真实记录严格导出 | PASS（v2限定功能）；旧40挂钩147次Qt取得C07创建／保存／C20另存实际记录；41挂钩新客体97次Qt、正常service_open从真实文件恢复C07代号2和C20代号1，无catalog内存seed；中文原调参页、八值、C07重入、显式保存代号3／取消自动返回／第二页实际读130B及摘要通过；Qt/QMP均0，原163项与690保持 | v1仍PARTIAL且含空C08导航测试，固定导出只覆盖C07/C20；v2功能闭环不含LUT转换／成像／真实机内介质／启动上次选择持久化。IMPORT job=0，NOT_READY明确；文件／目标根标题最后中文修订另验，不将旧英文标题当中文通过 |
| E-219 | `af_edit_joint.*`、`test_edit_joint.py`及`.local/continuation28-color/verification.json` | PASS；宿主5项、实际AArch64 14组；规范化1815B配方与内容摘要缓存6次构建／1次命中，原Gamma／矩阵／CC1参数桥及5列邻域消费，取消／别名／坏源不发布 | 显式Edit整数域，cache502624B、work709216B；不可表示节点／矩阵舍入和非零grid拒绝，不是完整AfJointModel或sRGB／ISP效果 |
| E-220 | `cp_grid_context406.py`及`continuation28-cp/verification.json`、`original-grid-context406-final-source.json`、26组原窗口 | PASS（原初始化／状态机范围）；ST/FL2/FL3×双银行六例，原初始化使查询4→0，原四次颜色调用自然进入网格打包后空输出保护 | 未发布真实输出；原分配链停在5c9050读取未初始化每核线程表前，无伪造线程／缓冲／锁／能力。driver、EVF/JPG和最后帧仍未证明 |
| E-221 | `final28-tests-1793070873407178000/pytest.json`、`sanitizer.json`，206项核心源指纹 | PASS；356 passed in 23.08s，退出0；仓库六个实际普通目录场景ASan/UBSan均退出0，前后源码无漂移 | 本功能相关核心及新仓库事务；ASan未启用泄漏检测，不覆盖原厂GUI/RTOS/ISP或真实介质。后续GUI若改产品源码，只使对应范围失效 |
| E-223 | `af_grid_model_valid`、默认关闭的paired夹具及显式数学fixture；`.local/continuation28-color/grid-scope/final-freeze.json` | PASS；原PT捕获误准入ST的红灯复现后修复，12宿主／AArch64 2442项检查，原捕获摘要在ST/PT均拒绝、输出保持 | 11对公开捕获均PT且固定非网格参数；另摘要仅区分数学实验，不是产品准入，旧“ST保守”结论撤回；完整四组件模型仍无可用后端 |
| E-224 | `af_repository.c`、`test_native_repository.py`；`.local/continuation28-storage-review/final-freeze.json` | PASS；错误IMPORT源绑定catalog可破坏其他槽却耐久成功的红灯已复现；首次读取前跨层区间／溢出预检，10项仓库＋媒体测试、增强定向及glibc2.25 A64编译通过 | INVALID失败回执、无源写／进度／新记录、原槽／名称保持并可恢复；opaque model.context由可信拥有者固定。最终DSO须含新修复，旧中间IMPORT构建不作当前准入证据 |
| E-225 | `af_ap_media.*`、`test_ap_media.py`；`continuation28-media-bridge/verification-lifecycle.json` | PASS（文件到浏览接口）；2项实际普通目录场景、AArch64编译，真实scan／同代take／双遍read／中文名与摘要、陈旧／取消／source别名拒绝／显式新目录重绑，延迟prepare/finish不调用show/back | 原D4在宿主为明确服务边界，统一GUI另验；读取后READ_READY仅报告转换未就绪，不产生IMPORT或Saved。同步读最多8MiB，未承诺读取期间按键取消 |
| E-226 | `continuation29-route/original-D4-open-overload.json`、`original-D4-list-capacity.json`及`continuation29-title/original-group-header.json` | PASS（原路径限定）；原3b2事务／影子、完整20B开屏队列／wrapper转参、首项token解析、原D4呈现模型21行／红区及CreativeLook组标题查询执行 | 3bc不是父页；开屏返回仅表示排队；2ed是显式队列夹具，不冒充实际Main DS。末端字形／滚动／actual apply仍须GUI |
| E-227 | `continuation29-exporter/final-freeze.json`、`host-reassembly.json`和实际`os-execution.json` | PASS（导出助手资格）；旧glibc／同版内核真实只读固定五文件、必需缺失／链接／输出错误拒绝、offset／END／长度重组及marker／双CRC／纯参数解码通过 | 测试记录明确EXPORTER_TEST_ONLY，不用于GUI恢复；旧od导出判FAIL保留，真实GUI记录必须另导出并核验 |
| E-228 | `test_ap_ui_lifecycle.py`及`continuation29-lifecycle/verification.json`；含`ui_manage_failed`的当前模块 | PASS；3项：确认不扫描／未close不排、NOT_READY回管理D4后等待actual apply且不重排、IMPORT/CREATE开屏失败／group变更可清理重试，目录及持久化job保持 | AP getter／模型事务／开屏队列是明确服务边界，原执行复用E-226；不能据此称真实选择器画面通过，不虚称执行过旧版本失败 |
| E-229 | `continuation29-confirm/integration.md`、`confirm-wrapper-verification.json`及`continuation28-menu/module-enter-v1/verification.json` | PASS（确认门禁子范围）；原输入7例／完整ENTER关闭顺序，确认包装器8项、三菜单一次性许可6项；40挂钩／85前像构建及59项相关检查通过，源码期间无漂移 | 原+88方向键亦可调用，旧Saved画面不能证明OK闭环；仅原ENTER获准关闭调用点授权一次，finally清除。该构建早于短名称与后续返回修复，最终GUI另验；E-221受影响UI范围由本行及后续定向证据替代 |
| E-230 | `continuation29-title/compact-names-verification.json`、`original-D4-selected-title.json` | PASS（名称路由子范围）；原右侧标题独立BL定位及3组原窗口；新中英文AArch64名称7项通过，20槽／64文件固定短标签与完整标题分开，未分配私有标记不进UXC、禁用后仍安全解码 | 新增右侧标题挂钩与真实窄行／完整文件名画面须最终统一构建验证，不能用定向服务替代像素验收 |
| E-231 | `continuation29-final-color/final-freeze.json`、`README.md`、`thread-table-xrefs.json` | PASS（历史独立审查）；核对同源CP／两个公开参考，保存210个线程表立即数候选；当时未定位直接生产器，后续E-236已补。旧boot工具CP摘要不同，不能借其状态补当前服务 | 非零grid真实消费域／sRGB桥、完整服务到输出发布、EVF/JPG版本和最后帧仍独立未完成；候选搜索不证明生产器不存在，照片也不是唯一补证途径 |
| E-232 | `sanitizer29-1793074988647855000/verification.json`及其编译文件／头文件指纹 | PASS；因`af_ap_manage.c`新增真实确认许可，重新编译ASan／UBSan并执行六个实际普通目录仓库事务，全部退出0、源码期间不变 | 替代E-221受影响的仓库内存检查范围；未启用泄漏检测，合成联合模型只用于接口测试，不验证真实菜单／颜色／物理介质 |
| E-233 | `continuation28-menu/module-enter-v2/verification.json`、`continuation29-title/original-creative-current.json`及`current-and-lifecycle-review.md` | PASS（最终UI集中回归）；41挂钩／88原前像／36原目标，84968B模块SHA `9561c161…913cbd76`；75项相关测试35.86秒通过、源码无漂移，含返回7项／私有current10项，另18例原getter／初选窗口 | 描述符+78专用getter保留用户selector，原690锚点变化／原厂切换／禁用使其失效；只修原UI身份，非拍摄／CP应用。新客体的字体、保存恢复及文件浏览另列E-218 |
| E-234 | `continuation29-title/picker-localization.json`及对应四份C／测试指纹 | PASS（文案子范围）；实际新客体发现文件组标题仍为英文，新增model25固定文案；六项宿主测试通过，原文件名／epoch／intent和目录不变，语言切换及陈旧状态有执行证据 | 浏览／目标C和对应测试在E-233后变化，最新模块与中文像素另验；不能用英文旧画面关闭中文标题 |
| E-235 | `continuation29-title/original-D4-trash-help.json`、`trash-shortcut-review.md` | PASS（原快捷键路由）；27组原输入／D4构造／分派／listener执行，私有组的C4按下为HELP259，唯一业务写为帮助属性19a1=0，松键／重复不产生业务 | 底部垃圾桶是C4物理图标，不能解释成删除功能或天然disabled；原691、选择／预览／Reset无命中，实际帮助页返回及快照另由GUI验收 |
| E-236 | `cp_grid_context406.py`、`test_cp_grid_context406.py`及`continuation29-thread-writer/integrated-six-cases.json`、`mmu-original-barrier-final.json` | PASS（原初始化子范围）；ST／FL2／FL3双银行六例0.530秒，每例原5e3b58返回并执行628次写生成四核线程指针；原分配越过5c9050，停在5e5f08访问缺失GICC前；错源三个入口预拒绝1项测试通过。MMU原上游CP15读取成功后到5ea8f0四核屏障，计数1/0/0/0，未跳过等待 | E-220及E-231的旧线程表停点由本行补齐；无host TCB／假锁／假服务，未写另三核计数，未把GICC映射成零RAM。真实多核启动、MMU／GIC及输出发布／ISP／EVF-JPG仍未完成 |
| E-237 | `continuation28-menu/module-enter-v3/verification.json`、`gui-localized-v3.json`及`comment-only-v0/current-artifacts.json` | PASS（当批UI范围）；41挂钩／88前像、77项35.25秒通过；最后客体51次Qt，中文标题／槽状态／浏览／取消／两类HELP往返及五文件保持，原帧与PNG一致，Qt／QMP均0。随后仅修误导注释，两种配置预处理一致；当批源重建AP两个ELF及DSO均与对应实测字节相同 | 当批模块`module-comment-v4`84968B SHA `a34b897a…bd24dd9e`、service-comment-v3 94072B SHA `edfb37c4…058ed3`，完整摘要以回执为准。10月30日覆盖确认改变目标与UI源码，受影响范围由本批新证据替代；完整LUT／CP／机身介质仍未验收 |
| E-238 | `repository30-1r2b_4dh/verification.json`及全部编译源／头指纹 | PASS；真实目录仓库9项1.75秒通过，另ASan／UBSan9组全部退出0，源码无漂移；含覆盖／陈旧拒绝／旧副本／新目录恢复与两阶段发布故障 | 宿主普通目录；发布后不确定不报成功并冻结，明确恢复后解除；合成联合模型只验证接口，未启用泄漏检测，不是原菜单或机身持久化 |
| E-239 | `continuation30-color/runs/run-1793297935821040000/verification.json`、`freeze.json`及`verify_all.py` | PASS（来源和数据域子范围）；一次来源读取复核7组原打包／8窗口复制、6组原A7L6验证／绑定及99,372项固定PT设计编码关系，实际5.28秒，带工具／报告指纹 | 相对SRAM以RAM验证，不执行RTOS锁／MMIO；405坐标不命名为RGB/YUV；固定PT数值关系不验证上游全部捕获、留出误差或本包sRGB桥；flat驻留不等于boot数据复制，未改产品模型 |
| E-240 | `continuation30-cp/loader-data-window.json`、`verify_loader_data.py`及`continuation30-color/loader-payload-independent.json` | PASS（原加载参数窗口）；实际原header复制／SL加载／mapper入参说明物理源=f57000+128000=107f000，独立原字节与算术复核文件偏移f77000，A7L6文件／VA／边界摘要一致 | 撤回漏加SL的错误候选，不存在该候选造成覆盖的证据；确认flat数据页来源，不执行完整boot或实际ISP，独立算术不算新增boot次数 |
| E-241 | `continuation30-cp/qemu-run-ck3wf7s5/receipt.json`、`source-pages-service6.json`及漏页反例`qemu-run-widcq4rz/receipt.json` | PASS（原初始化／查询错误路径）；真实四核MPIDR、屏障3/5/5/5、原MMU及模型GIC，原事件初始化／IRQ ABI前提后53cd40完整返回fffffc01、输出0且原锁释放。163840字节必要源，834个翻译TB逐字节含跨页审核；漏53b页在53b50c真实拒绝，QMP／QEMU退出0 | 非完整boot和成像成功；pool119c788空导致原分配自然失败，待原生产器。审计验证全部翻译块及已输出exec引用，不声称TCG链式块的每次执行都逐条记日志；先前预算截断只计源一致前缀，漏页旧路径不作产品故障 |
| E-242 | `overwrite30/module-v1/verification.json`、`original-targets/original-targets-dispatch.json`及`root-gui-verification.json` | PASS（T09b1限定闭环）；89320B模块SHA112e7457…e323670，41挂钩／88前像、37项32.59秒；实际原D4两段确认默认取消、MENU取消／悬停零任务、CREATE C20代2、COPY源工作值到C20代3且源记录不变；新AP恢复FL3／+3，源恢复+2；实际容量不足phase5/result−9/durable0、5文件保持；207原帧／PNG逐字节核对，原690／163项保持 | 三轮状态为FAIL／FAIL／PASS：前两轮故障夹具分别重挂EBUSY、缺wc，失败前步骤单列复用，不改判整轮成功；最后Qt／QMP0。已移除不适用重挂动作，容量夹具只填固定16MiB私有tmpfs且大小实核。非机内路径／真实介质／CP照片，不验收完整功能 |
| E-243 | `repository30-mcr9u6cp/verification.json`、`clear30/module-v1/verification.json`、`clear30/service-v1/service-media-build.json`及`clear30/record-export-verification.json` | PASS（清空实现／离线预检）；仓库12项1.39秒及ASan／UBSan12组退出0；统一AP模块46项33.08秒、93624B／41挂钩／88前像；服务94856B、能力0x1b、GLIBC 2.25／6项公开符号核验；固定导出解析器5项通过 | 原菜单和全新AP墓碑恢复另验；非相机存储／成像。双副本仍允许最新墓碑损坏后回退旧完整记录，独立复现见`continuation30-clear-review/run-k8cq6nz6/verification.json`，未改变通用恢复契约 |
| E-244 | `clear30/root-gui-verification.json`及两轮`candidate-clear30-root-v{1,2}/runs/*` | PASS（T09b2限定闭环）；143原帧／PNG逐字节一致，实际当前C07清空拒绝／默认取消／悬停零任务，记录保持；明确确认生成C20第4代规范墓碑，新AP仅实际记录恢复为空，再CREATE第5代，源C07与旧完整副本保持；两轮Qt／QMP退出0，原690／163项保持 | 原AP软件原帧，CP仍禁用；RAM目录非机内存储，健康墓碑恢复不代表最新损坏墓碑永不回退 |
| E-245 | `continuation30-cp/osal-full-v14/qemu-run-opu8dlyp/receipt.json` | PARTIAL_NOT_CLOSED；原四核／MMU／GIC后执行原OSAL依赖及53a52c，原查询53cd40返回0、句柄92a4601f，1100个翻译TB来源通过，QMP／QEMU退出0 | 构造尾回调注册仍返回ffffffff／表未更新；不透明句柄不是网格指针，非完整启动／输出发布／EVF／JPG |
| E-246 | `rename30/root-backend.json`及`repository30-7zgq13oi/verification.json` | PASS（重命名后端）；4文件前像与隔离绿灯后像精确核对后串行应用，15项真实目录回归1.38秒与ASan／UBSan15组退出0；63B UTF-8名称／dirty保持／陈旧拒绝／新进程恢复／发布前失败及发布后不确定冻结通过 | 当批仅后端，原键盘后续见E-249；显式recover沿既有契约将working重载为saved，不承诺恢复未保存工作；非机身介质 |
| E-247 | `continuation30-cp/reproducible-osal/qemu-run-wdi7_ogl/receipt.json`、`consumer-v3/qemu-run-jfm0o5vd/receipt.json`及`consumer-v8/qemu-run-y005b_34/receipt.json` | 原池／查询／回调拒绝可复算模式PASS，36段256KiB／1084TB；完整原消费者先返回−3，原574bcc注册端点成功后进入真实分配回调、返回−4／216B输出零，1424TB来源PASS，均QMP／QEMU0 | 消费者两轮仍PARTIAL_NOT_CLOSED；银行39d真实生产／正确任务调度未完成，不把原错误返回或非零资源句柄称为成像闭环；独立原注册／mode/arena来源见`continuation30-{endpoint,arena,mode,mode-entry}-review` |
| E-248 | `rename30/module-v1/verification.json`、`repository30-xy8h8a9t/verification.json`及`rename30/gui-v1-verification.json` | 第一版正常键盘流程PASS；73项37.75秒、107408B／57挂钩／132原像，与隔离提案ELF相同；仓库15项1.26秒／消毒器15组通过；真实输入A并生成C07第4代，dirty+3／saved+2保持，取消／空名零任务无写；548B完整恢复、两组98B设置保持；86原帧一致，Qt／QMP0 | 该报告只验第一版正常流程，未覆盖的异常及新AP恢复由后续E-249补齐；不改判旧版本或用它单独关闭T09b3。三原设置命令未做动态拦截，前后数值相同不扩大为调用数为零；非机身存储／成像 |
| E-249 | `rename30/module-v{2,3}/verification.json`、`root-stage7-integration.json`、`gui-v2-verification.json`、`restore-v3-verification.json`及`gui-v4-verification.json` | PASS（T09b3限定离线闭环）；资格／HELP、中间poll和实际D4父组失配均先有红灯再修复，最终78项41.71秒、107456B／57挂钩／132原像。实际四种原键盘输入d、第5代仅名称变化、dirty+3／saved+2保持；全新AP真实记录恢复d／FL3／+2。最终模块取消及未改名零任务，五文件保持，548B在收尾后恢复、两组98B设置保持；后续三轮91+45+70=206原帧逐字节一致，Qt／QMP均0 | 只复用未变的保存后端，明确各轮ELF摘要；最后UI SHA837e0e59…7ae9d24e。快照可能早于下一次管理刷新，首次D4画面不作为收尾完成回执；原设置数值不变不等于动态调用计数为零。任何init／D4之前的open拒绝与同址旧事件边界仍留M4；非机身介质或成像，父T09b／M3仍未完成 |
| E-250 | `continuation30-cp/reproducible-rtos/qemu-run-0u_33g37/receipt.json`、`reproducible-tomco/qemu-run-8bsbsb6d/receipt.json`、`continuation30-bank-config-review/agent/verification.json`及`continuation30-cp-boundary-review/verification.json` | 原RTOS组0前缀PASS／2061TB；原表六例核对20B×14、group／core与回调ABI。正式原TOMCO完整扫描自然group2，原完整.data及timer登记核验，当前1651TB逐字节含跨页源PASS、QMP／QEMU0；整体为BLOCKED_ORIGINAL_WDT_MMIO，原609e18写40000→f1388344发生DataAbort／DFSR808 | 保留原wdt_on1／tmo7，无host组写／清锁／硬件RAM化；未到银行／成像。旧v1／v2缺初始数据的timer拒绝不作产品故障，v2返回−17更正旧−2误读；旧v4两个TOMCO标志的矛盾由新模式修正，历史不改写。源审计PASS不等于完整启动PASS |
| E-251 | `legacy30-review/materials-check.json`及`README.md` | PASS_MATERIAL_CONSISTENCY_ONLY；六款1215B网格／108B联合载荷与材料、补丁后像一致；48条旧模型／Backup来源和seed调用边界核对 | 不重读DAT／不执行原函数／不VM，非当前个人设置、完整迁移或成像验收；C01～C06继续原委派，T10／T02不勾选，不以纯参数seed代替旧增量语义 |
| E-252 | `final-integration30.json`及`final_check30.py` | 最终V0：AST／局部文本与引用、当前UI／服务／CP冻结来源、实际回执状态／任务边界、原输入摘要及暂存区／本任务进程核对 | 复用未变化范围的有效行为证据，不重跑无关全套；整体仍NOT_VERIFIED，原WDT模型缺口阻塞成像，不生成可安装包、不操作相机 |
| E-253 | `continuation31-native/{cp-preset-freeze,ap-preset-freeze,root-integration,root-ap-integration}.json`及原消息定向回执 | AP原发送／不可变会话、单调版本、并发与故障关闭；既有CP PRESET到原锁整组输入准备、原快照定向通过，本次宿主回归保持 | UI发送未绑定；原厂完整九字段回退、最终银行／流／最后帧未证明。factory-roundtrip-review.md明确只恢复FL3 base不足以恢复八项；prepared不是成像 |
| E-254 | `continuation31-import/backend/{verification,root-integration}.json`及`continuation31-software/verification.json` | 联合拟合与留出验证分批执行，12项任务文件契约、实际文件读取／摘要／取消／候选提交／保存恢复纳入统一144项，当前源编译与回归通过 | 显式完整模型，测试合成后端仅接线；无默认假模型，误差非本机实拍，首次双读／解析仍有界同步 |
| E-255 | `continuation31-import-ui/{freeze,verification,root-integration}.json`、`continuation31-schema/{verification,root-integration}.json`及统一回执 | 浏览模板到目标确认／有效LUT覆盖；UI16项定向契约及纯参数／AJR1混合恢复通过，不改旧STORE.ID／旧记录；已排新票据时父页失败保留输入 | 原D4／媒体服务为明确软件边界，非完整客体新画面或实际SD；原厂12／未迁移旧6仍保护 |
| E-256 | `continuation31-import/service-review/verification.json`、`rebind-before/`及统一回执 | 真实旧前像复现READ_READY误放行换绑；修复后持有期间rebind／cancel／prepare均BUSY，原选择／代号／缓冲保持；候选提交前摘要再核 | 只释放未提交选择，活动转换等待任务实际完成；无新线程，不伪造资源释放或保存成功 |
| E-257 | `continuation31-export/{backend,ui}`冻结与串行集成回执及统一回执 | 原注册树新增1604无冲突／57挂钩；纯参数已保存版本导出、默认取消／真实ENTER、O_EXCL、写入同步／独立回读／失败不确定纳入144项通过 | 显式普通目录，非实际SD；导出不保存dirty、不改body代号；失败文件保留，无自动覆盖／清理 |
| E-258 | `continuation31-software/verification.json`及`final-integration31.json` | 统一144 passed in 18.07s／源码不变；动态AP112024B、固定AP152088B、AArch64/glibc225后端110680B编译链接通过；最终输入与引用核对单列 | 不启动虚拟机／外设模型、不操作相机；硬件模拟封存，实际模型／原厂完整回退／取景JPG／机内路径与迁移仍未完成，不生成可安装固件 |
| E-259 | `continuation32-factory/{source-freeze,root-integration,evidence-index}.json`、原getter／锁来源及本次统一回执 | 12原厂索引与非零八值的C快照、cap／slot0兼容拒绝、FL3→C07→FL3完整九字段输入准备和显式UI事件／具体runtime回调通过；原包装器静态取证／编译 | 128B、13consumer保持；旧单字段异步顺序未知，UI默认无绑定；固定研究映射不代表实际装载与成像 |
| E-260 | `continuation32-management/red.json`及统一回执 | 完整LUT另存／改名／保存／导出／非当前清空、完整AJR1／报告／摘要保持、工作与保存分离、服务大载荷导出、重开墓碑、陈旧／损坏拒绝通过 | 真实临时文件与菜单宿主契约，非实际SD或新完整界面；调参后不沿用初始误差保证 |
| E-261 | `.local/continuation32-model/{source-lock,verification}.json`及统一回执 | 固定99,372点／298,116通道的ITP＋SSCS到矩阵输入逐码相等，漏SSCS反例64,805通道／最大1111码；拒绝与目标编译通过 | 整数前端差0不代表完整渲染／本机ΔE0；不注册完整AfJointModel或猜网格语义，固定源锁随测试保留 |
| E-262 | `continuation32-legacy/{freeze,source-evidence,root-integration}.json`及统一回执 | 11对getter/meta、66绑定；三基底／八值／shadow与固定完整资产快照，27↔18矩阵及条件Gamma，17宿主拒绝／保持契约通过 | 外部须给原锁下已就绪窗口；没有取得个人数据、不执行迁移，AJR1缺来源时明确不支持 |
| E-263 | `continuation32-software-v2/verification.json`及`final-integration32.json` | 最终187 passed in 21.29s／源码不变；动态UI116352B、后端110832B、AP82432B／CP71652B，固定UI与前端／legacy对象亦编译通过；输入／引用核对单列 | 首轮185通过2旧断言失败保留；修正有效LUT的新契约及不一致快照拒绝后复验。受限模式额外发送有红灯并修复；不启动模拟器、不操作相机，M1～M4不提前完成 |
| E-264 | `continuation33-cp/{source-freeze,snapshot-source-final,root-integration}.json`及`continuation33-review/{factory-pending-receipt,review-freeze}.json` | 原锁内副本覆盖与原状态独立；完整118B gate／锁准入、显式NATIVE及单调版本；实际UI C＋CP叶复现连续原厂切换／原厂调参滞留，修复后六类事件回归通过 | 原gate仅静态核对和交叉编译，未安装；factory pending非排空／照片回执，全部模式及原最终消费者仍待接入 |
| E-265 | `.local/continuation33-color/{verification,root-integration}.json`及README | 3类宿主case及ARMv7编译通过；完整AJR1深拷贝、operation/C4/source身份、实际1215源、mode0/index0缓存及陈旧／别名／并行拒绝 | 表字节适配，clone伴随绑定及selector/dispatch双挂钩未安装；原指针残留不可free，不提供完整网格/sRGB像素模型 |
| E-266 | `continuation33-software/verification.json` | 202 passed in 28.02s，无源码漂移；动态UI112352B／固定UI152392B／仓库110832B／AP82632B／CP76536B编译链接通过；57UI挂钩／132原像声明保持 | 仅宿主行为与目标编译，CP软浮点／禁自动向量化；不运行目标、模拟或相机，不生成可安装固件；仓库产物与上一批相同 |
| E-267 | `continuation33-package-integrated/verification.json`、`icon-path-source-check.json`及集成预检 | 5项宿主契约、当前UI／132原像／57挂钩、16源窗口、两非零布局／组合冲突通过；ET_DYN26888B、11RELATIVE、4个单B出口及396B垫片 | 资源真实名23/32另经源归档核验及当前定向修正；默认AP计划只有本任务4窗口，aspect只作对照；非实际装载或32槽发布 |
| E-268 | `continuation33-placement-integrated/{placement,bounded-link}.json`及CP放置V2冻结 | 本批CP SHA410c569e…、RX/RO4348B／RW跨度268B；4项门槛通过；408B真实尾部有界链接按预期拒绝 | V1旧32模块2220B不代表本批，历史保留；BSS1216仅算术余量，不授予分配/执行，整体BLOCKED |
| E-269 | `continuation33-package/loader-staging-input-v1.json`及`loader-build-v5/verification.json` | 51384B真实Linux/glibc225准备DSO链接通过；1项宿主COW逆补丁／输入不变／坏文件拒绝／默认publish与storage BUSY通过，迁入共享后1.61s复验 | 只有准备，无原注册时序准入producer，不手调注册、不安装57或CP挂钩、不启32槽／默认存储；未执行目标 |
| E-270 | `continuation33-usr/{source-freeze,append-freeze,three-dso-final-audit,two-image-report}.json` | 新DSO13项／大图追加4项宿主通过，真实三模块与两图分别派生、全树／原inode／旧块及ACL保持，独立e2fsck0 | 原USR与DAT保持；新增／替换仅新派生普通文件，不挂载、不签名，不是机身持久化 |
| E-271 | `continuation33-full-unsigned-usr-v2/{verification,e2fsck}.json`及同目录实际输出 | 4AP窗口＋70资源＋4DSO完整串行组合，410652672B／SHA3b53450d…6b92；原1043项inode及无关内容保持，独立e2fsck0；清单6项宿主定向通过 | 第一版有效内容保留，修复回执发布窗口后再运行v2；内容回执不单独宣称镜像已发布，须检查实际输出。CP未改、UI不发布、signed/DAT/installable均false |
| E-272 | `final-integration33.json`及staging独立审查／四项发布故障回执 | V0复核核心源码未漂移、各模块实际摘要、实际最终USR及内容回执、当前CP拒绝、AST／文档链接、原DAT／USR／CPIO和Git暂存区保持 | 复用未变202核心及17文件工具证据；不运行目标／模拟／相机、不读取私钥，状态只为未签名准备完成，整体NOT_VERIFIED |
| E-273 | `continuation34-media-package/verification.json`、`continuation34-integration/media-loader-host.json`及自然登记冻结 | 原init_array[104]先观察再尾调原构造一次，原登记5591项后取得单次回执；双shim796B／7AP窗口，132原前像及57研究挂钩不变；当前COW与父fd／独立媒体回执7项PASS | 生产挂钩56项，排除已完成的原登记BL；不是自然启动或完整UI验收，publish仍BUSY |
| E-274 | `continuation34-cp-paired-current/verification.json`、`continuation34-cp-{bootstrap,memory,host}-final-v4/verification.json`及`cp_bootstrap/test_header_binding.py` | 当前源重新绑定后RX3204B／RW272B，引导408B／快照befb35，原CRC literal e20078b4与实际ELF一致；9窗口内存往返、5组宿主边界PASS，生成头隔离及实际map阶段码2项0.10秒PASS | extraMap保留阶段1／2，执行仅阶段2；旧六源与前缀保持；phase初始RW只在原完整loader契约下成立，不证明任意MMU／并发热unmap；未写CP或执行目标 |
| E-275 | `continuation34-media-snapshot/{freeze,verification-v1/verification}.json`、`continuation34-fsys/freeze.json`、`continuation34-media-abi/evidence.json`及当前统一构建 | 同锁AP来源核对原锁／getter；私有0x150复制、坏前像／别名／错误getter均不发布。原Fsys5 typed接口、完整64token、同代元数据及双遍内容／首末SHA、失败／取消和路径限制，19项canonical宿主PASS；目标编译链接PASS | 原snapshot/Fsys边界为宿主注入，非原函数执行或实际SD；只支持slot0/1、原PRO根及安全ASCII文件名；generation不是物理介质代号 |
| E-276 | 当前`tests/test_media_provider*.py`、`test_native_media.py`、`test_repository_import_service.py`及E-277 | 两种提供者互斥、活动输入驻留及任务复制／重读／保存恢复；context起始字节与源缓冲4条回归先红后绿；进度回调在已验证区域／末次修改源2条回归先红后绿 | 新原生context不缩窄为fd，原fd后端保持；完整context外部寿命仍由可信调用者负责；合成模型只证明接线，不授予实际颜色模型资格 |
| E-277 | `continuation34-media-software/{verification,commands}.json`、`continuation34-media-loader/verification.json`、`continuation34-integration/media-loader-host.json` | 240 passed in33.81s，当前native／test源码无漂移；动态UI116704B、repo112160B、AP/CP请求及新增Fsys／快照目标构建PASS，启动库74488B／6e54f91d…c390；启动库7项1.84s PASS | 本轮仅宿主C／文件事务和交叉链接，无目标、QEMU、Unicorn或设备执行；完整模型未绑定时仍NOT_READY |
| E-278 | `continuation34-integration/staging-input-media-v3.json`、`continuation34-full-unsigned-usr-v3/{verification,e2fsck}.json`及实际输出 | schema2固定7AP窗口＋70资源＋4DSO，410652672B／SHAb503cc6c…e661；原1043项inode和无关内容保持，新增后1047项，e2fsck0；当前冻结清单f860bcd9…1f0d | 真正派生普通文件；CP未变、UI不发布、DAT／signed／installable均false；不冒充机内持久化、真实SD或完整成像验收 |
| E-279 | `.local/continuation34-native-media-loader-review/{README,verification,freeze}`及canonical `loader/test_media_binding.py` | 独立审查无新增阻断项；原函数抽取的第五导出／异基址／第20个RX前像拒绝、半绑定错误与重绑BUSY三组隔离PASS，canonical同ABI三组0.50秒PASS；provider别名问题已复现并修复后只读确认 | 桩测试替换动态装载及服务边界，不证明真实dladdr、页权限、卡I/O或原UI ready；4MiB单缓冲与8MiB双遍I/O分开 |
| E-280 | `continuation34-integration/final-media-audit.json` | 最终V0绑定当前240项代码状态、实际组件／USR和CP仅内存计划、原输入摘要、AST／文档链接及暂存区保持 | 只关闭本批离线接线与准备，不关闭完整模型、成像、迁移或T12；整体仍NOT_VERIFIED |
| E-281 | 当前`test_ap_cards.py`／`test_ap_cards_flow.py`／`test_media_card_service.py`／`test_loader_picker.py`，选卡模块冻结及原ID证据 | 默认取消／真实ENTER／Main后选卡扫描、取消／错父／禁用／忙／读失败及fd旧路由；修复loader漏IMPORT／EXPORT选择器位。已纳入E-283 | 原UI／Fsys边界为宿主替身；未执行原呈现器、真实选卡或新完整菜单，不新增创意外观槽 |
| E-282 | `continuation35-fsys-encoding/freeze.json`／`encoding-evidence.json`及canonical UTF-8测试 | 同包Find长名与Open双向UTF-8、非BMP及锁／计数来源；8code＋GOT＋module初始化／6指针只读guard；中文／组合字符／127B、非法序列／路径／128B、策略前后失败及别名。原19＋新25项纳入E-283 | 完整库来源与实际读区权限先核；不写编码、不执行原Fsys；实际SD和机内中文键盘不在此证据内 |
| E-283 | `continuation35-software/{verification,commands}.json` | 首版281 passed in39.67s，当时源码及编码fixture无漂移；动态UI122064B、repo112696B、固定AP及AP／CP请求／适配器交叉链接通过。长源名保留／默认短名保存恢复及后部坏UTF-8拒绝已覆盖 | 仅宿主C／普通文件事务与交叉链接；没有目标／模拟／设备执行，合成模型不授予真实颜色资格 |
| E-284 | `continuation35-package/verification.json`、`continuation35-loader/verification.json`及`continuation35-integration/loader-{media,host}.json` | 132原前像／57研究挂钩，未来发布仍56；启动库79688B／13b55bb2…d99f。6项0.89秒＋7项1.88秒PASS，映射先于读取／基址改变／半绑定拒绝、默认BUSY及COW逆7窗口 | 文件／动态服务为宿主边界，目标未执行；自然启动、产品准入及实际CP配对仍缺 |
| E-285 | `continuation35-integration/staging-input.json`／`image-readback.json`及`continuation35-full-unsigned-usr/{verification,e2fsck}.json` | 首版7AP窗口＋70资源＋4DSO，410652672B／9c89db39…c013；原1043项inode及无关元数据保持，1047项；e2fsck0，实际文件独立回读全部74组件并逆AP回原摘要 | 未签名准备文件；CP不变／UI不发布／无DAT／不可安装，不当作机内持久化或取景JPG验收 |
| E-286 | `continuation35-cp-source`／`continuation35-cp-binding`的README及冻结回执，`continuation35-integration/c4-store.json` | 原bef550 gate ABI／fallback／距离、原query、同步raw读取及heap；240de2注释校正。新增22窄窗／28指令证明快照→大输入复制→C4异步副本→原任务及双bank实际生成，reset与packed free区别 | 已明确当前私有版本不随九字段传播；同次版本、原任务排空和全部持有者／最终raw释放未证。没有安装空gate、执行CP或写源CP文件 |
| E-287 | `continuation35-dates-integration/final-audit.json` | 本批最终V0核对当前行为回执源摘要、实际组件／USR、原输入、编码原窗口、AST／文档引用和暂存区 | 复用有效283＋13证据，不重复运行成功测试；父任务／完整模型／成像／迁移与T12不改为完成 |
| E-288 | `continuation35-fsys-encoding/date-followup.json`及`continuation35-dates-integration/{red,green}.json` | 原只读Read访问字段及原Find精确6B映射独立核对；误STALE实际1失败／1通过→修复后2通过。只忽略18..19/22..25，保留20..21更新10ms和全部其他16日期字节，逐字节变化均拒绝且不发布元数据 | 不改原日期缓存、无编码或属性放宽；原Close何时持久化访问日期未执行，不声称特定卡实际触发 |
| E-289 | `continuation35-dates-software/verification.json`、`continuation35-dates-loader/verification.json`及`continuation35-full-unsigned-usr-v2/{verification,e2fsck}.json`／独立回读 | 当前283 passed in39.57s无源漂移；启动库79736B／8154453e…8305，7项1.96秒重新PASS，6项实际依赖不变的loader抽取契约复用。新v2 410652672B／eece3077…c422，7AP＋70资源＋4DSO、1043→1047及全部回读／e2fsck0 | 本批首版v1及34批v3均保留。CP不变、UI未发布、无DAT且不可安装，真实颜色／成像／迁移／介质不随283项变成已验收 |
| E-290 | `continuation36-core/version-regression.json`及`test_cp_version_atomic.py`／原厂回切／CP入口契约，E-295统一结果 | 旧同版本覆盖实际先失败；新版本与完整输入同锁提交，零／重复／回退／64位边界拒绝，会话不重建；实际packet.version经入口传递 | 版本仍未随原C4复制或绑定图像，未将诊断变量或PRESET返回改称应用成功 |
| E-291 | `continuation36-cp-final-{module,bootstrap,memory,host}/verification.json`及header绑定测试 | RX3352／RW288／phase1a3ac60，BSS扩292而原页表根保持；408B尾与CRC44b0e57f、实际phase字核对，9窗口内存逆转／5宿主组／2项0.09秒PASS | 旧六源及包装器前缀保持，未写CP文件或执行目标；旧3204／272／ac50只能作历史，不能混用 |
| E-292 | `continuation36-lut-transport/{report.md,verification.json}`及当前provider测试，E-295统一结果 | bootstrap元数据登记→原refresh解析→真能力就绪后一次bind，5项纳入289；失败／重入／已选择及未准入不绑定、无自动send。完整1943B与128B／无ACK／四层kind1拒绝已定位 | 原AP消息gate未装、admission0；只补发送器准备接线，未证明UI→CP运行。完整payload协议／驻留／统一消费仍缺 |
| E-293 | `continuation36-cp-owner/{README.md,verification.json,freeze.json}` | 38窄窗／19指令及宿主浅引用反例：原worker串行，但借用源先刷新再查pending；2310de共同退出需完整10B，8B会截断；纠正提交成功返回1／失败0 | 没有同步／排空证明不安装raw恢复gate，排队版本不当消费版本，原任务完成不当图像完成 |
| E-294 | `continuation36-color-model/{README.md,evidence.json,freeze.json}`及`continuation36-color-refresh/{README.md,refresh-evidence.json,freeze.json}` | 15来源／两NPZ及新ColorLab固定8bd8564f…的12文本有界审计，5关键文件与旧缓存逐字相同；仍缺本版照片域桥／非零网格像素算子，未填假predict／摘要 | 不把旧路径迁移误作缺算法，未遍历全部训练／历史总结；Edit整数／另机型／固定PT响应不解除本版模型门禁，不能据此报告本机联合误差 |
| E-295 | `continuation36-final-software/verification.json`、`continuation36-core/{loader-host,image-readback}.json`及`continuation36-full-unsigned-usr/{verification,e2fsck}.json` | 当前289 passed in28.36s及目标链接；启动7项1.93秒；动态UI126312B、启动80464B。新USR410652672B／37e0a25b…fd47，7AP／70资源／4DSO，1043→1047及74组件／AP逆窗口／e2fsck0 | 输入DAT／CPIO／USR保持；CP未变／UI不发布／无DAT／不可安装。289不等于完整模型、相机成像或全部任务完成 |
| E-296 | `continuation36-core/final-audit.json` | 当前源码／配对组件／实际USR／原输入、冻结报告及AST／引用／暂存区的最终只读V0 | 复用有效行为结果，父项与总状态NOT_VERIFIED，不恢复模拟或操作设备 |
| E-222 | `final-integration28.json` | 最终V0语法／引用／当前构建及证据指纹、输入摘要、父项／暂存区和本任务进程核对 | 只整合已执行范围；不将普通目录、菜单或原初始化子链当可安装固件，整体NOT_VERIFIED |

文件位于[本地主线证据目录](../../../.local/fixed-custom-filters/)，E-219另在[颜色参数证据目录](../../../.local/continuation28-color/)。本批接线与证据范围见[integration-28.md](integration-28.md)。新增原上下文布局更正见[主线记录](mainline-progress.md)；历史E-189的拆分夹具继续保留，不再解释为原厂实际对象关系。

## 证据边界

实施前工作区干净，HEAD `290c79e`。已确认根目录 `.venv` 为Python3.14，pytest、pyelftools、capstone、unicorn可用；numpy和Cryptodome由现有桌面捆绑目录按命令显式提供，不安装新依赖。

之前会话中的原厂二进制定位只作线索。本轮已针对指定4.06重新验证。历史4.06回执不算本次新运行的结果。

本次仅新增本功能源码、测试与规格。未修改输入DAT、冻结复现材料及已有清单；未打开相机、USB、SSH或真实SD接口，未读取私钥。第五批生成独立研究ELF并在匿名AP内存安装真实分支，未导出AP补丁文件或可安装包。

| Evidence | Code State | Command / Step | Result | Scope |
|---|---|---|---|---|
| E-000 | 实施前HEAD 290c79e | git status、现有源码/规格/依赖检索 | PASS，工作区干净 | 范围与运行环境 |
| E-001 | 新增入口及边界用例 | `pytest tests/test_baseline.py`；新增模块先失败后通过；补充`..`路径拒绝用例后再次失败，归一化修复后3项通过 | PASS | 同长度改包、非法路径/符号链接、错误组件、报告不覆盖；合成输入仅验证拒绝 |
| E-002 | 当前指定4.06及最终审计源码 | README中的`a7filters.baseline ... --investigate --report ...`，本轮最终实际运行 | PASS；736841帧、751577088明文字节、147归档条目、71项目标；验签及内部校验通过 | 当前修改包前像与输入不变，不证明新增成像功能 |
| E-003 | 最终`af_slots.c/.h` | E-007同一批次中的12项原生槽位测试，实际编译并调用C库 | PASS | 固定容量、独立编辑、八项边界、保存快照/失败/过期完成、LUT重置保留及复制独立；不含存储或CP接入 |
| E-004 | 最终`af_cube.c/.h` | E-007同一批次中的12项原生解析/求值测试，实际编译并调用C库 | PASS | 非对称轴顺序、域映射/输入夹取、非法输入、容量预算、非有限值及失败不发布输出；不含ISP拟合 |
| E-005 | 与最终C源码相同 | README中的三条`clang --target=... -c`，启用`-Wall -Wextra -Werror` | PASS；AArch64槽位、ARMv7 Thumb槽位、AArch64 CUBE目标文件 | 仅编译，未链接进AP/CP，未执行目标架构产物 |
| E-006 | 与最终C源码相同 | README中的ASan+UBSan编译命令及`native-sanitizer` | PASS；退出0，20000次确定性输入/状态探测 | 主机C代码内存/未定义行为检查，不能代替目标ABI或设备异常验证 |
| E-007 | 最终新增可执行源码及测试 | `./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short` | PASS；27 passed in 2.61s | 3项入口+12项槽位+12项CUBE；无机身/真实SD操作 |
| E-008 | E-002中的当前AP；隔离描述符/记录夹具 | Unicorn执行`0x1bd91d0…0x1bd9200`，没有外部函数调用 | PASS；19条原记录+33条合成记录+两次未命中，共54次查询 | 仅原指令查找窗口，未执行整个页面或注册合成ID；呈现器容量仍未证明 |
| E-009 | 续实施最终`baseline.py`及`access_evidence.py` | README中的`a7filters.baseline ... --investigate --report .local/fixed-custom-filters/access-evidence-406-continuation-02.json`，本轮实际运行 | PASS；验签/736841帧/147归档条目/71目标及两份辅助库重核通过 | 输入仍为指定4.06，不调用旧前像补丁器，不访问设备 |
| E-010 | E-009锁定AP | 原厂`0x1bcf3fc`枚举7组、`0x1bd924c`选择分派34次 | PASS；容量限制/保护区/顺序/尾调身份符合预期 | 描述符、可见性、注册表及setter为明确边界；不证明真实呈现器、ID注册或模型写入 |
| E-011 | E-009锁定AP及两个同包Backup库 | 7组消息/回执、3组AP同步包装器、3组BackupManager记录检查 | PASS；确认同步状态被后续日志覆盖，记录查询与异步入队语义符合原代码 | 仅客户端；不证明服务端/新记录/空间/耐久提交。错误为离线注入，无真实保存失败事件 |
| E-012 | E-009锁定CP | 八个通知接收器、五档锐度范围的两段复制、两种双缓冲索引 | PASS；目标字节/转发/索引切换和回调顺序符合预期 | 来源指针/构造器/回调边界为夹具；不证明真实成像状态或帧释放 |
| E-013 | 续实施最终新增可执行源码/测试 | `./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short` | PASS；28 passed in 3.65s | 新增错误组件执行前拒绝用例；其余原生核心/CUBE回归通过 |
| E-014 | 本轮最终源码摘要 | 文档链接/空白检查、代码与回执指纹核对 | PASS（见续实施摘要） | 新增接入证据源码/测试及更新的规格；C源码未变，复用E-005/E-006有效证据 |
| E-015 | 新增`native_paths.py`及接入后的`baseline.py` | README审计命令，报告`native-paths-406-continuation-03.json` | PASS；固定4.06重新验签、736841帧、147归档条目、71项目标及辅助库核对 | 同一修改包；无设备I/O或安装补丁 |
| E-016 | E-015锁定AP/CP | 新增3组父项缓存、4组门控/挂载、6组文件写入错误、5组CP来源链 | PASS；18组原指令场景；真实ARM memcpy与上下文构造执行 | 来源链已知调用者属于初始化；系统调用/功能谓词为夹具，不证明空间、实时应用或帧释放 |
| E-017 | 最终`af_record.c/.h`和独立格式用例 | `pytest tests/test_native_record.py`：源码缺失时先失败，实现后22项通过 | PASS；22 passed in 3.11s | 记录格式、校验、预算、双副本恢复选择/冲突/未知版本及代号耗尽，不含文件后端或预设语义 |
| E-018 | 最终`af_record.c/.h` | README的AArch64及ARMv7 Thumb两条`clang --target ... -c` | PASS；警告视为错误，产出两份ELF目标文件 | 仅编译，未链接或执行新目标架构产物 |
| E-019 | 三个原生模块及扩展后的探测器 | README的ASan+UBSan编译及`native-sanitizer-03` | PASS；退出0，20000次输入/状态/记录探测 | 新增随机记录破坏和恢复选择；不证明实际介质异常或掉电恢复 |
| E-020 | 最新全部新增模块及测试 | `./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short` | PASS；51 passed in 0.27s | 3入口+12槽位+12CUBE+22记录+2原指令执行前拒绝；无相机/真实SD |
| E-021 | 最新源码、目标文件及回执摘要 | 空白/文档链接/字段/ELF目标架构检查，源码和产物指纹记录 | PASS（见第三批摘要） | 文档更新后执行V0，不重复运行代码未变化的E-015～E-020 |
| E-022 | 本批最终审计入口、界面证据源码及指定4.06 | README的`--investigate-ui --ui-adapter ...`，回执`ui-access-406-04-final.json` | PASS；736841帧、147条归档、71目标和同包C++库重新核对 | 额外库独立摘要；不修改原基线清单，不读私钥或访问设备 |
| E-023 | E-022锁定AP/C++库 | 原厂注册器/树平衡/迭代，33个身份查询、32名称分派及呈现写入 | PASS；5591→5605，重复插入不增加；1589项页面映射；节点及名称组件保护区保持 | 分配、资格、基底/别名及呈现器引用为边界；未证明完整画面/导航/实际AP注册已安装 |
| E-024 | E-022锁定AP及本批测试ELF | 八项原厂回调128组；新增AArch64代码320次入口分流、320次读取、33身份及12原厂委派 | PASS；原厂步进/边界符合预期；用户不访问原厂18项数组、不改保存值且回退后无槽位串扰 | 目标代码确实执行；入口分流只在模拟器，未安装AP挂钩，未调用CP/存储 |
| E-025 | E-022核对的68份UXC及`ui_resources.py` | 在内存追加14个默认名并检查旧记录、计数/指针和精确逆变换 | PASS；每份3038→3052项，总增长9520字节，原记录保持 | 未导出资源补丁，未执行原生UXC加载器或字体绘制；非动态滤镜名验收 |
| E-026 | 本批`af_ui.c/.h`及名称夹具测试 | UI源码缺失时先编译失败，实现后10项通过；资源模块缺失时先失败，实现后6项通过 | PASS；10 passed in 1.95s、6 passed in 0.01s；同范围由E-029最终回归覆盖 | 用户参数隔离/边界/委派/拒绝及资源格式；不冒充机内安装 |
| E-027 | 本批`af_ui.c`及未变的`af_slots.c` | README的两条AArch64编译及既有`ld.lld`链接命令 | PASS；测试ELF 70088字节，SHA-256 `af66c83c…394a3ba` | 独立测试地址0x92000000，后由E-024执行；未链接进AP/CP |
| E-028 | 四个原生模块和扩展后的探测器 | README ASan+UBSan命令及`native-sanitizer-04` | PASS；退出0，20000次输入/状态/记录/UI探测 | 主机内存及未定义行为，非相机或真实介质验证 |
| E-029 | 本批最终可执行源码及测试 | `./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short` | PASS；70 passed in 3.25s | 4入口+4组件拒绝+12槽位+12CUBE+22记录+10界面+6资源；无设备I/O |
| E-030 | 本批最终源文件、文档、审计及产物 | 文档链接/空白/ELF架构/回执字段检查，源码与产物指纹记录 | PASS（见第四批摘要） | 复用E-022～E-029对应行为证据，后续只改文档 |

E-002的输入SHA-256为 `3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2`。审计开头和结尾均验证该摘要，输入长度754525608字节。

本地回执（均为本轮新生成，位于被忽略的`.local`，不含导出的固件镜像）：

- [最终基线与原指令窗口审计](../../../.local/fixed-custom-filters/baseline-406-20261025-final.json)
- [补充静态原指令窗口](../../../.local/fixed-custom-filters/research-windows-406-20261025-01.json)
- [独立查找窗口执行回执](../../../.local/fixed-custom-filters/list-lookup-406-20261025-01.json)
- [最终源码和产物摘要](../../../.local/fixed-custom-filters/verification-20261025-final.json)：锁定12个源码/测试/基线文件及7项本地证据产物。文档调整不影响已记录C行为证据。
- [续实施最终接入审计](../../../.local/fixed-custom-filters/access-evidence-406-continuation-02.json)：包含本轮69组原指令场景；三个门槛仍为false。
- [续实施源码与结果摘要](../../../.local/fixed-custom-filters/verification-continuation-02.json)：本轮最终14个源码/测试/基线文件和审计摘要。上一阶段E-007由本轮E-013补充，不把旧Python源码指纹当作当前指纹。
- [第三批原厂通路审计](../../../.local/fixed-custom-filters/native-paths-406-continuation-03.json)：重新完整审计，包含旧窗口和新增18组场景；三个门槛仍为false。
- [第三批源码和产物摘要](../../../.local/fixed-custom-filters/verification-continuation-03.json)：锁定本批可执行源码/测试和编译产物，记录51项测试及消毒器结果。文档和底层成像未接入的边界另行核对。
- [第四批最终界面审计](../../../.local/fixed-custom-filters/ui-access-406-04-final.json)：原厂注册/名称呈现/128组参数回调、68份名称夹具及目标代码执行，仍无实际AP挂钩或完整画面结果。
- [第四批源码和产物摘要](../../../.local/fixed-custom-filters/verification-continuation-04.json)：本批源文件、独立测试ELF及70项回归、消毒器和回执指纹。

未安装依赖；基线审计通过单条命令的`PYTHONPATH`使用已有捆绑依赖。完整可重复命令见[实施入口](../../custom-filters/README.md)。

## 第十四批验收覆盖快照（历史记录）

以下保留当时的覆盖和缺口描述，不作为最新总状态；后续进展见相应批次与本文件顶部M1～M4主线计划，不能据此称现有解析/求解/误差核心尚未编写。

| Acceptance | Status | Evidence / 缺口 |
|---|---|---|
| AC-000 | PASS（前像审计） | E-110重新核对指定4.06整包/71目标、同包OSAL/其他辅助库及103资源来源；未产生增量固件，后续补丁仍需独立回归 |
| AC-001 | PARTIAL | E-088补齐32名称的真实命名空间/分文件加载及保留，原组件/导航和提交保持；完整AP/Qt联合显示、实际装载与安装未验收 |
| AC-002 | PARTIAL | E-096/E-098完成完整预设、成像字节/摘要、初始/保存值及本地恢复；实际ISP schema、机内存储和成像版本未接入 |
| AC-003 | PARTIAL | E-096/E-098完成真实C保存、另存、清空及写入期间继续调参的快照语义；实际候选预览取消和原厂菜单尚未接入 |
| AC-004 | PARTIAL / MANUAL_REQUIRED | E-096/E-098完成本地普通目录及目标内存后端的双副本事务、重建目录恢复和墓碑；短写/EINTR/ENOSPC/同步/关闭/发布/回读失败通过。实际机内位置/容量、掉电及换卡重启未验证 |
| AC-005 | PARTIAL | E-004、E-005；CUBE解析/求值可编译，机内拟合及原生输出未实现 |
| AC-006 | NOT_RUN（计算） | E-096已验证误差元数据封装及调参后报告不适用；尚无真实ISP拟合、量化或误差计算，不能提供色差保证 |
| AC-007 | PARTIAL | E-110保持组件、输入/刷新/资源和纯参数适配，E-111联验原AP/OSAL/CP消息到原快照及颜色/锐度窗口；物理IPC与版本回执、其余算法后段、完整AP/Qt与成像未闭环 |
| AC-008 | PARTIAL / MANUAL_REQUIRED | E-111/E-112复现输入中间快照与消费者银行独立发布，E-113补资源类型、最后请求成功/失败及独立持有计数。EVF/拍摄流、统一版本发布、全部持有者/最后帧和会话握手未证明，不能确认取景/JPG一致性 |
| AC-009 | NOT_RUN / MANUAL_REQUIRED | SD菜单/替换/导出尚未接入，未操作真实卡 |
| AC-010 | PARTIAL | E-087/E-088保持当前包及原厂34份_f，原厂12名称（含FL2/FL3）和旧六款/新增用户名加载保持；实际六槽迁移、其他功能在新增安装后的回归仍未验证 |
| AC-011 | PARTIAL | E-111～E-114补发送失败、输入/银行非原子、JPEG三步失败与持有保持、数据段RW/NX边界；149回归通过，C不变复用E-108消毒器。实际机内预算/掉电、跨核会话、真实RTOS及硬件失败未验证 |
| AC-012 | PASS（本阶段） | 输入未变、源码/任务状态与回执核对；设备相关功能未声称通过 |

完成任务为T00、T03a/T03b/T03c、T04a、T04b1、T04b2a、T05a、T06a、T06b1～T06b3、T06b4a/T06b4b/T06b4c1/T06b4c2、T06b4c3a/T06b4c3b/T06b4c3c1、T06c、T07a/T07b、T08a；均限定离线子范围，不包括完整界面或成像。T01～T03为部分研究，T04/T04b/T05/T06/T07/T08整体及T09～T11保持未完成；机内存储、物理IPC/版本握手/完整CP消费/帧寿命、拟合、菜单及匹配4.06客体仍待完成。T12真实设备验收为`MANUAL_REQUIRED`，当前未授权。最新见[第十四批交付](continuation-14.md)及[消息/帧接入](communication-frame-access.md)。

本轮T01～T03的接入研究有可执行增量，但整体done condition仍不满足。具体缺口、两处旧假设修正及新来源链分别见[接入证据](access-evidence.md)和[原厂通路补证](native-paths.md)。独立记录格式通过不改变实际保存/成像接入门槛。

第四批界面接入完成T06a，具体地址、证据边界及T01/T06b剩余项见[界面接入清单](ui-access.md)。不能把32个名称组件写入或模拟器入口分流记作完整原厂页面已安装。

禁止用本机C核心测试、交叉编译或静态字段核对替代AP/CP实际接入、ISP像素及真机验收。

## 未完成部分的具体风险

- 列表扩展：身份查找支持读取新条数，但呈现器/导航对象和18项原厂参数数组尚未统一扩展。只改条数可能越界或选错参数；现阶段不生成该补丁。
- 内部存储：历史可写挂载不能证明当前容量和掉电顺序；猜测路径或复用未知Backup记录可能破坏原设置。未选定写入区，未执行迁移。
- CP应用：运行期复制/派生已执行，但C4浅复制仍借用共享根；锁拒绝可能返回0，队列拒绝也清完成标记。缺少帧所有者和最后引用证据时，可能混用参数或过早释放，尚未切入实际拍摄链。
- LUT转换：通用三线性求值不等于原生ISP色表可表达；基底差异、量化和裁剪误差未测量。没有将解析成功显示为“已导入生效”。

回退边界：输入DAT与历史实现均保持原状，本阶段新增代码尚未接入生产入口，不需要对相机或个人设置执行回退。

## 第五批：真实AP分支与显示快照

以下证据绑定当前第五批源码；第四批ID候选已被撤回，不能用E-022～E-030替代新身份的行为验证。

| Evidence | Code State / 命令 | Result | Scope |
|---|---|---|---|
| E-031 | 当前源码，README的`--investigate-ui --ui-adapter …05.elf --ap-ui-module …05.elf`，新回执`ui-access-406-05-final.json` | PASS；重新验签、736841帧、147条归档、71目标及辅助库 | 指定修改版4.06，输入摘要保持；同时重跑既有窗口、资源和接口分流 |
| E-032 | E-031的`ap_ui_hooks.tail_records`及元数据窗口 | PASS；165次五类索引解析、38组原厂资格、36组参数可编辑标记 | 新行不继承C06资格索引，+0x14读取经过原指令；+0x7a语义和完整触摸路径未证明 |
| E-033 | `af_ap_ui.c/.S/.ld`，AArch64交叉编译链接后由E-031执行 | PASS；模块77360字节，SHA-256 `b2906b76…6151931`；14处分支前像/回跳核对，初始化BL返回，5605行注册、32/33/0三态枚举 | AP匿名副本、加载基址0、资格/别名为边界；未执行全局初始化后续流程；精确恢复描述符与原分支 |
| E-034 | 同一E-031的真实挂钩执行 | PASS；20用户快照、160可编辑询问、320调参、128原厂回调回归及12原厂显示逐字节对比；陈旧选择/未知布局拒绝，原六槽模型读取与防覆盖通过 | 保存值及槽间隔离保持；用户路径正规化器调用0次，不写18项数组；没有刷新通知、照片/视频模式接受或CP成功回执 |
| E-035 | `./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short` | PASS；82 passed in 2.65s | 当前最终行为源码；12界面测试含快照、9分支编码/集合、5错误组件拒绝及既有核心/资源回归 |
| E-036 | README消毒器命令构建`native-sanitizer-05`并执行 | PASS；退出0，20000次确定性探测，新增快照/标记输入；ASan+UBSan无报告 | 主机四个通用核心，AP绝对地址模块由E-031在目标架构执行，不在主机直接运行 |
| E-037 | 在QEMU目录用其`.venv`执行`runtime_manifest.verified_inputs()`，错误和缺项保存至`qemu-preflight-05.json` | BLOCKED；清单为4.00，CPIO和DTB两个固定输入不存在 | 未启动VM、未改清单或尝试绕过校验；完整32槽画面/Qt按键/原始帧均NOT_RUN |
| E-038 | 第五批源码、测试、文档及产物摘要，链接/空白/证据字段/架构检查 | 见`verification-continuation-05.json` | V0；行为复用E-031～E-036，不重复运行成功回归 |

当前核心覆盖由E-035更新；AC-001/AC-007/AC-010仍为PARTIAL，E-033/E-034不等于完整原厂界面、真实六槽迁移或机身接受。参数显示是调用显示入口后读取的原厂布局对象，尚未证明按键后自动刷新和原厂像素输出。

当前阻塞和风险见[第五批界面接入结论](ui-access.md)。继续保留`full_global_initialization_verified=false`、`refresh_notification_connected=false`、`photo_mode_semantics_verified=false`、`uxc_loader_verified=false`、`full_native_screen_verified=false`、`installable_candidate_allowed=false`。

## 第六批：原厂输入门控纠错及直接赋值

第五批E-034的受限查询和标记解释错误：1表示受限，不能据返回1声称可编辑。下层回调数值、身份和行尾证据仍保留；上层可用性由下列新证据替代。纠错原因见[纠错记录](retrospective.md)。

| Evidence | Code State / 命令 | Result | Scope |
|---|---|---|---|
| E-039 | 原第五批ELF `ap-ui-hooks-05.elf`，重新从原厂0x220ae78调用；`inhibit-regression-06-red.json` | REPRODUCED；C07对比度7按增加仍为7，期望8，受限返回1 | 旧错误的可执行复现；保留原ELF和失败回执，不代表当前修正失败 |
| E-040 | 当前代码及研究ELF，README审计命令，新回执`ui-access-406-06-verified.json` | PASS；固定修改版4.06重新验签、736841帧、147条归档、71目标和辅助库 | 同时重跑旧窗口、资源、目标核心、缓存和真实AP输入联验；输入DAT保持 |
| E-041 | E-040的`ap_ui_hooks`，从0x220ae78/0x220af84和0x220933c进入 | PASS；17焦点映射、20槽320次上层步进、480合法/320越界赋值；空槽、陈旧选择、非法焦点、快照/实时限制拒绝；原厂128组按键、8项受限及8项直接赋值/非赋值消息保持 | 允许标记为0，受限为1；用户调参期间0x690模型保持0且不写18项数组。焦点组件getter、锁和原厂setter为夹具；显示由测试显式调用，无自动刷新或列表提交验收 |
| E-042 | E-040的`ui_cache`，同包真实构造器0x1c938a8/树平衡及别名/缓存指令 | PASS；5591项二级别名、19旧/14新增查询、14个新行缓存跳过窗口，非栈写入0 | 只证明新二级身份0x2b36大于0x2b34时跳过旧缓存；不是完整初始化或所有消费者兼容性 |
| E-043 | 当前最终源码；`./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short` | PASS；84 passed in 2.64s | 增加直接赋值的范围/失败不发布/保存隔离用例及缓存错误组件拒绝；13项通用界面测试、6项错误组件拒绝及既有回归 |
| E-044 | README的ASan+UBSan编译及`native-sanitizer-06` | PASS；退出0，20000次确定性探测 | 四个通用核心，新增直接赋值和快照输入；AP绝对地址代码由E-040在AArch64执行 |
| E-045 | 本机clang AArch64编译、既有ld.lld与`af_ap_ui.ld`链接，随后由E-040执行 | PASS；研究ELF77512字节，SHA-256 `48ebcb67…8ed238e`；15处分支/前像/跳板及精确回退保持 | 编译命令和源/产物摘要见第六批摘要；模拟器专用地址，不可用于机身 |
| E-046 | 第六批源码/测试/文档/产物指纹、Python语法、ELF架构和链接检查 | 见`verification-continuation-06.json` | V0，复用同状态的E-040～E-045行为证据 |
| E-047 | 只读检查QEMU清单及固定文件存在性，`qemu-input-presence-06.json` | BLOCKED_FIXED_INPUTS；仍为4.00，固定CPIO与DTB缺失 | 本轮未重新执行QEMU输入验证器或启动VM；既有失败E-037保留，完整原厂帧/Qt交互仍NOT_RUN |
| E-048 | 同一已校验AP的12段原指令及唯一受限函数名，`research-windows-06.json` | RECORDED（静态） | 门控/焦点/直接赋值来源可复查；两条选择模型写入与刷新候选仅定位，不声称已执行或接通 |

本轮修复通过，不改变整体`NOT_VERIFIED`。实际列表提交的两条0x690写入路径、刷新订阅、完整初始化/模式、UXC加载、持久化/另存和CP仍未完成；不把上层事件返回1当作保存、成像或自动刷新成功。具体入口和风险以[第六批界面接入结论](ui-access.md)为准。

## 第七批：列表安全隔离、刷新查询和导航修复

| Evidence | Code State / 命令 | Result | Scope |
|---|---|---|---|
| E-049 | 同一已校验AP，原始0x1c6f208/0x25966cc执行；`selection-isolation-07-red.json` | REPRODUCED；19和32分别写入0x690，伴随属性通知 | 事务/变更日志/通知为隔离边界；未操作相机 |
| E-050 | 最终源码、07测试适配ELF与07c AP模块；README完整审计命令，`ui-access-406-07-verified.json` | PASS；736841帧、147条归档、71目标及辅助组件重核，输入DAT保持 | 所有原有窗口/资源/核心/缓存及新增AP分支联验；不导出AP |
| E-051 | E-050中两条上层分派0x1bd924c/0x1bd9348至真实挂钩 | PASS；40用户提交隔离、26原厂/特殊项委派、16非法/禁用叶子、8限制布局、4影子副本及3空槽 | 用户0x690/通知/预览外层消息均不变化；原厂值和通知顺序保持。页面映射真实树，事务和消息封装为边界，不代表成像应用 |
| E-052 | E-050原厂0x1e97a24查询、0x1ec7388调度窗口及0x1e1e1d8/0x1e1ea74快照消费 | PASS；1197次窗口、843次调度及消费；重复查询不丢请求、非目标页面/陈旧身份拒绝、原厂脏位保持；320上层步进＋480合法/320非法赋值 | 用户编辑全局属性广播0次；帧驱动仅按真实调度请求调用快照函数，无关字段计算器及对象引用为夹具；未执行整帧循环或呈现器绘制 |
| E-053 | 07b失败复现`navigation-07-red-corrected.json`，07c由E-050回归 | REPRODUCED→PASS；C07后退误跳C20，补齐对象别名0x1bd1ef8后130次双向导航/环绕、32名称窗口通过 | 原初red文件附错上下文，由重放版本替代；当前页面/身份/屏幕准入和名称组件引用为夹具，无UXC/像素验收 |
| E-054 | 最终源码；`./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short` | PASS；84 passed in 6.49s，退出0，`pytest-07.json` | 主机通用核心及边界回归；AP模块由E-050在目标架构执行；未变核心消毒器复用E-044，不重复运行 |
| E-055 | 本机clang AArch64及ld.lld，真实20处分支/前像/跳板联验 | PASS；模块82344字节，SHA-256 `1588084b…67e9475`，描述符与分支精确回退 | 编译/链接及来源摘要见第七批摘要；仅基址0离线研究模块 |
| E-056 | 第七批最终源码/测试/文档/报告摘要及语法/链接/边界字段检查 | 见`verification-continuation-07.json` | V0；复用本批有效行为证据 |
| E-057 | QEMU目录使用其`.venv`实际执行原`verified_inputs()`，`qemu-readiness-07.json` | BLOCKED；清单仍4.00，CPIO/DTB缺失，原验证器报“输入不存在或越界”；现存另三输入摘要均符合原清单 | 未启动VM、未改清单；真实Qt按键、原始帧/PNG和完整画面仍NOT_RUN |
| E-058 | 同一已核验AP的15段原指令及五处GUI前像，`research-windows-07.json` | RECORDED；五处局部前像匹配 | 不代表4.06客体、完整模拟层适配或实际装载基址/分支范围证明 |
| E-059 | 同一已核验AP，初始化两路正规化及后续读取，共6组窗口；`initializer-risk-07.json` | REPRODUCED / UNFIXED；18→17为正常索引，19/32→−1并读到基底数组前4字节哨兵 | 仅寄存器/数组前哨兵和锁/日志为夹具，未执行完整初始化或后续写入；该风险阻止进入完整界面试跑，后续T06b4必须修复 |

本批T06b3完成其离线边界，整体仍`NOT_VERIFIED`。当前`native_ui_refresh_query_connected=true`，但`refresh_notification_connected=false`、`full_refresh_draw_verified=false`、`full_native_screen_verified=false`；完整初始化、模式、资源装载、成像和耐久保存均未验收。接入方案与剩余工作见[第七批清单](ui-access.md)。最终代码及产物指纹见[本批摘要](../../../.local/fixed-custom-filters/verification-continuation-07.json)。

## 第八批：调参初始化隔离及原厂基底编号

| Evidence | Code State / 命令 | Result | Scope |
|---|---|---|---|
| E-060 | 旧07c模块从原厂0x220a7ac进入；`initializer-entry-08-red.json` | REPRODUCED；C07读原厂基底数组前4字节，正规化返回−1，0x1700变为无效菜单0x2b36 | 本体指令执行；组件引擎/锁/日志/通知为边界，未操作相机 |
| E-061 | 最终源码及08研究ELF；README完整审计命令，`ui-access-406-08-verified.json` | PASS；重新验签、736841帧、147归档成员、71目标和同包辅助组件；输入保持 | 同时重跑旧接口、资源、缓存、24处真实分支及新增初始化联验 |
| E-062 | E-061中`parameter_initialization`及已有输入/刷新场景 | PASS；20用户/12原厂初始化、40用户基底回调阻断/2原厂回调委派、空槽/重入/禁用/限制拒绝；24组基底映射、12种子映射/4非法拒绝；1218查询窗口、864快照消费 | 用户初始化不读写原厂基底数组、不调用原正规化器；原厂0x1700写入/通知保留。组件引擎、事务及成像包装器仍为夹具，不等于实际迁移、基底编辑或完整画面 |
| E-063 | 最终源码；`./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short` | PASS；84 passed in 1.55s，退出0；`pytest-08.json` | 主机核心及边界回归；AP绝对地址模块由E-061执行，未变通用核心消毒器复用E-044 |
| E-064 | 本机clang AArch64编译与ld.lld链接，E-061执行24处分支/前像/跳板及精确回退 | PASS；模块82864字节，SHA-256 `c2dbb4d2…4b8adec7` | 新增两处函数入口B和两处带原目标验证的BL；基址0研究模块，未实际装载或安装 |
| E-065 | 最终源码/测试/文档/产物指纹及语法/链接/字段检查 | 见`verification-continuation-08.json` | V0，复用本批有效行为证据 |
| E-066 | QEMU目录用其`.venv`执行原`verified_inputs()`，`qemu-readiness-08.json` | BLOCKED_FIXED_INPUTS；仍为4.00，固定CPIO/DTB缺失，原验证器拒绝；另三输入摘要保持 | 未启动VM、未改清单；完整Qt按键/帧/PNG仍NOT_RUN |
| E-067 | 同一已校验AP的8段原指令、内部基底选择值与菜单表，`research-windows-08.json` | RECORDED；确认初始化与独立基底回调边界；内部10/11→选择值17/18 | 修正E-059的函数归属和此前种子夹具假设，不将静态表或单函数执行视为完整成像 |

本批T06b4a完成其离线边界，T06b4和整体仍未完成。完整组件配置/模式、实际AP线程/装载、UXC、整帧绘制及像素、成像和持久化继续未验证；独立基底编辑明确关闭。最新接入说明见[第八批清单](ui-access.md)，最终指纹见[第八批摘要](../../../.local/fixed-custom-filters/verification-continuation-08.json)。

## 第九批：原厂组件状态、真实焦点及资源入口

| Evidence | Code State / 命令 | Result | Scope |
|---|---|---|---|
| E-068 | 当前最终源码、09研究ELF；README完整审计命令，`ui-access-406-09-verified.json` | PASS；指定4.06重新验签、736841帧、147归档成员、71目标及同包辅助组件；输入不变 | 同时回归24处分支、列表提交、32名称、初始化、八项输入及1218次刷新查询/864次快照消费 |
| E-069 | E-068的`native_components`、`parameter_initialization`及八项输入 | PASS；16节点原插入、4焦点模式、禁用/恢复、隐藏/重复隐藏及3节点释放；20用户/12原厂初始化、320步进、480合法/320非法赋值 | 焦点读写、禁用/隐藏和树操作为真实代码；回调/附属散列表仍为原表派生夹具。160次焦点UI通知，成像参数广播0次；未验收完整组件/轮盘/页面生命周期 |
| E-070 | 本机clang AArch64和ld.lld，README的09编译链接命令 | PASS；AP模块82864字节，SHA-256 `c2dbb4d2…adec7`，与08相同 | C/S/链接脚本未变；24处分支前像、回跳、命中及精确恢复由E-068执行；不是可安装模块 |
| E-071 | 最终源码；`./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short` | PASS；84 passed in 1.75s，退出0；`pytest-09.json` | 主机核心/边界回归；AP联验由E-068覆盖。未变C核心消毒器复用E-044，不重复执行 |
| E-072 | E-068同源AP/C++库及同包libObj.so，仅匿名读取；`research-windows-09.json` | RECORDED；10段AP窗口、107条描述/16输入项、两份回调原表、树删除窗口及资源管理器静态入口 | libObj.so摘要独立记录；未执行UXC加载器，未声明ABI/字体/像素通过 |
| E-073 | QEMU目录现有`.venv`执行原`verified_inputs()`，`qemu-readiness-09.json` | BLOCKED_FIXED_INPUTS；清单仍4.00，固定CPIO/DTB缺失，其他三输入匹配 | 未启动VM、未改清单；真实Qt按键、完整帧/PNG、MENU重开/退出仍NOT_RUN |
| E-074 | 当前源文件/测试/文档/产物指纹及语法/本地链接/证据字段检查 | 见`verification-continuation-09.json` | V0，复用E-068～E-073有效行为证据，不将静态分析算作功能通过 |
| E-075 | 独立机器执行原0x1af57c0，107条原表；`full-table-constructor-09-boundary.json` | UNBOUND_LIBRARY_CALL_STOPPED；0x16dacb0对应同包C++散列表扩容0xb7e08未绑定，PC=0、LR=0x1af4a5c | 是测试环境缺少库绑定，不能据此断言AP故障；未绕过扩容或纳入通过的完整构造结果 |

T06b4b完成限定的离线焦点/组件状态接入，T06b4c和整体T06b4保持未完成。原getter/setter、禁用和隐藏夹具已经移除；全局回调注册、附属散列表构造、真实事件导航/轮盘、完整模式和页面回收仍待验证。研究模块基址仍0、默认关闭，UXC/整帧绘制、CP取景/JPG、LUT拟合和机内持久化尚未闭环。未操作相机、未导出固件。当前具体入口见[第九批清单](ui-access.md)，指纹见[第九批摘要](../../../.local/fixed-custom-filters/verification-continuation-09.json)。

## 第十批：完整组件、原生参数导航与文字记录查找

| Evidence | Code State / 命令 | Result | Scope |
|---|---|---|---|
| E-076 | 同包原构造/注册和原资源探测；`component-bucket-10-red.json`、`callback-bucket-10-red.json`、`component-containers-10-red.json`、`resource-namespace-10-red.json` | REPRODUCED；桶请求88/136字节被节点预算拒绝；完整对象隐藏实际释放6节点；12原厂名称不属于用户字符串池 | 区分隔离后端/旧夹具预期与AP故障；未操作相机，纠正后再进入E-077 |
| E-077 | 当前最终行为源码及10研究ELF；README完整审计命令，`ui-access-406-10-verified.json` | PASS；重新验签、736841帧、147归档成员、71目标及C++/libgcc/libObj同包辅助组件；输入保持 | 24处分支、提交/初始化隔离、旧八项输入、列表导航/名称、1218刷新查询/864快照消费和新组件/资源查找联验 |
| E-078 | E-077的`native_components`、`native_hash_runtime` | PASS；107项原构造、15回调注册、六容器、原组件及两份注册表析构；234块所属分配全部释放，保护区保持 | C++扩容111次/下一桶27次及六种辅助入口执行原代码；普通节点64字节/1MiB池保持，三档桶仅原调用点例外；错误调用点/65字节/重复释放拒绝。库自身初始化、整个AP启动和真实Qt生命周期未验收 |
| E-079 | E-077的`parameter_initialization.native_component_navigation`和原0x220933c非赋值消息 | PASS；8参数左右/环绕16例、禁用跳过2例；隐藏项不进入结果，消息实际写焦点而不改预设 | 原控制器/组件函数执行；Qt键盘、触摸轮盘、整帧输入/绘制未验收 |
| E-080 | E-077的`native_resource_lookup`，同包libObj 0x122930→0x122870 | PASS；68份原始/追加资源、20用户文字名称2992次查询，含1224次缺失/越界空值；记录身份/地址/UTF-8保持 | 文件内容由夹具装入内存，无外部调用；12原厂名称属于其他命名空间，原厂名称/数据库/UXC文件获取/缓存寿命/字体/像素仍未验收 |
| E-081 | clang AArch64和ld.lld，README的10编译链接命令 | PASS；模块82864字节，SHA-256 `c2dbb4d2…adec7`，与09相同 | C/S/链接脚本未变；24处分支及精确恢复由E-077执行。基址0研究模块不可安装 |
| E-082 | 最终源码；`./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short` | PASS；88 passed in 1.69s，退出0；`pytest-10.json` | 新增辅助库身份在模块/CPU之前拒绝；通用C核心未变，消毒器证据复用E-044；真实新路径由E-077覆盖 |
| E-083 | 同包AP/libgcc/libObj/global.xdb，`research-windows-10.json` | RECORDED；8段AP、5段资源库窗口、辅助函数入口、UXA头/239分组与其他资源头 | global.xdb 16424字节，独立摘要记录；0x1235d8为缓存切换，实际记录查找是0x122930；静态证据不算数据库加载成功 |
| E-084 | QEMU现有`.venv`执行原`verified_inputs()`，`qemu-readiness-10.json` | BLOCKED_FIXED_INPUTS；仍4.00清单，固定CPIO/DTB缺失，其他三输入匹配 | 未启动VM、未改清单；Qt键盘/完整帧/PNG及MENU重开/退出仍NOT_RUN |
| E-085 | 当前最终源码/测试/文档/回执/产物及输入指纹，语法/链接/字段检查 | 见`verification-continuation-10.json` | V0；复用同代码状态E-077～E-084，不重复执行成功回归 |

T06b4c1/c2完成限定的原组件/回调构造、回收、参数导航和焦点消息接入。T06b4c3及整体T06b4继续未完成：原厂其他命名空间、数据库/UXC装载、字体/像素、实际AP装载/线程与4.06客体仍有缺口。CP取景/JPG、机内持久化、LUT拟合和误差报告未交付，未生成可安装固件，未操作相机。当前入口与风险见[第十批清单](ui-access.md)，最终指纹见[第十批摘要](../../../.local/fixed-custom-filters/verification-continuation-10.json)。

## 第十一批：原资源文件加载、原厂名称、引用与失败保护

| Evidence | Code State / 命令 | Result | Scope |
|---|---|---|---|
| E-086 | 同包libObj原入口；`resource-mmap-11-red.json`、`resource-borrow-11-red.json` | REPRODUCED；原MAP_FAILED在0x122a84无效读取；未配对借用引用的探测留下文件引用，配对后清空 | 前者为隔离注入的原失败；后者为探测协议纠正，不当作AP泄漏。均无相机事件 |
| E-087 | 当前最终行为源码、11研究ELF；README完整审计命令，`ui-access-406-11-verified.json` | PASS（前像及限定联验）；重新验签、736841帧、147归档成员、71目标及同包辅助库；103资源来源逐项记录；输入不变 | 24处AP分支、提交/初始化/组件/导航/八项输入、1218刷新查询/864快照消费保持，并运行新资源加载机；完整AP/Qt联合未验收 |
| E-088 | E-087的`native_resource_loader` | PASS；34语言原始/追加共68组、3536查询，952次原文件缺新名称空返回；原厂12项及旧六款保持 | 原文件/UXA/UXC加载、缓存、引用执行；272打开/关闭及映射回收，1564块所属分配有释放记录。POSIX/内存/引擎上下文为后端，字体/像素未验收 |
| E-089 | E-087的保护记录、故障场景及STUB命中 | PASS；匿名库一个4字节分支＋20字节跳板；272正常映射、数据库/UXC失败恢复通过，保护均精确撤销 | 原−1未改成0；原成功及关闭路径保持。源库/DAT未改、未导出库；真实装载基址/页权限/线程及所有资源消费者未验收 |
| E-090 | E-087的7类故障 | 6类REJECTED_AND_CLEANED；未保护mmap保留ORIGINAL_INVALID_READ_REPRODUCED | open/stat/UXA及UXC错误魔数、保护后的数据库/UXC mmap失败回收；原失败有1个虚拟打开文件，未冒充恢复或实际机身故障 |
| E-091 | clang AArch64和ld.lld，README的11编译链接命令；保护汇编单独构建 | PASS；原AP研究模块82864字节、SHA-256 `c2dbb4d2…adec7`保持；保护ELF66208字节、SHA-256 `a4552ceb…75550aba`，.text为20字节且与运行字节一致 | 原AP模块C/S/链接脚本未变，新增保护汇编独立；两类产物仅供隔离研究，不是安装候选 |
| E-092 | 最终源码；`./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short` | PASS；93 passed in 1.99s，退出0；`pytest-11.json` | 新增数据库身份、虚拟设备路径/容量在CPU之前拒绝；汇编器核对及0/−1/正常指针目标路由通过。通用C核心未变，消毒器复用E-044 |
| E-093 | 同包13段原函数、5个POSIX符号及保护边界，`research-windows-11.json` | RECORDED；实际文件对象/加载/引用/回收入口及失败检查前像 | 静态窗口与E-087行为绑定，不将接口后端等同真实系统I/O或引擎启动 |
| E-094 | QEMU原`verified_inputs()`，`qemu-readiness-11.json` | BLOCKED_FIXED_INPUTS；仍4.00清单，固定CPIO/DTB缺失，其他三输入匹配 | 未启动VM、未改清单；Qt键盘/完整帧/PNG及MENU重开/退出仍NOT_RUN |
| E-095 | 当前最终源码/测试/文档/回执/产物与输入指纹，语法/链接/字段检查 | 见`verification-continuation-11.json` | V0；复用同代码状态E-087～E-094，不重复执行成功回归 |

本批完成T06b4c3a/c3b/c3c1的限定离线边界。原库失败与匿名保护后恢复分别记录；源libObj及输入DAT均保持。T06b4c3c及父任务仍未完成：资源机和AP挂钩尚未在同一个完整4.06 AP/Qt客体联合，字体/整帧、实际装载/权限/线程、其他资源消费者及真实页面生命周期仍待验收。CP取景/JPG、持久化和LUT拟合/误差未交付，未操作相机，未生成安装包。详细代码入口见[第十一批清单](ui-access.md)，指纹见[第十一批摘要](../../../.local/fixed-custom-filters/verification-continuation-11.json)。

## 第十二批：完整载荷、普通目录事务、编辑联动和版本引用

| Evidence | Code State / 命令 | Result | Scope |
|---|---|---|---|
| E-096 | 最终源码；`tests/test_native_persistence.py`，包含在E-101中 | PASS；28项实际C编译/字节格式/普通目录/故障联验 | SHA与独立hashlib对照，最大256KiB成像字节；未来格式/坏数据/同代冲突、短写/EINTR、ENOSPC、fsync/close、发布/回读不确定；保存/另存/墓碑及新目录恢复。机内路径未选择 |
| E-097 | 最终`af_versions.*`；`tests/test_native_versions.py`，包含在E-101中 | PASS；2组实际C版本/引用契约 | 三银行、64引用、在用保护、失败保持旧版、过期确认及重复释放；单次初始化生命周期，回执由测试驱动，不是CP |
| E-098 | 最终原生核心；`tests/native_pipeline.c`及`test_native_pipeline.py`，E-101保留ELF | PASS；AArch64和ARMv7分别运行实际指令 | 每种20槽八项UI分流→保存→目录重建恢复→另存/墓碑→版本引用；独立Python最终文档摘要一致。文件后端为显式内存，不是实际AP/CP握手 |
| E-099 | 最终C源码；`native-sanitizer-12-final.json` | PASS；编译/执行退出0，ASan+UBSan下20000次输入/目录/记录/UI/完整文档探测，以及20槽事务/版本闭环 | 本机内存边界证据；不证明真实线程/文件系统/ISP预算 |
| E-100 | 最终研究源码及build-12 UI/AP ELF；`ui-access-406-12-verified.json` | PASS；重新验签、736841帧、147归档条目、71目标及103资源来源；原24 AP分支、1218刷新查询/864快照消费保持 | 新AP ELF 82904字节，SHA `d9ff98a2…9167d6`；AP挂钩C/S/ld未变，槽位恢复函数新增后重新链接。CP有12直接调用及466立即数候选，保留107窗口；静态扫描不能证明实时到达或帧寿命 |
| E-101 | 最终源码/测试指纹；`pytest-12-final.json` | PASS；134 passed in 4.04s，退出0 | 包括原93项与新增41项；CP超量扫描先真实失败，再用300候选的有界窗口回归及真实DAT审计通过。初期失败记录保留，不伪装首次成功 |
| E-102 | 最终源码/文档/本地回执/产物/输入指纹和链接检查 | 见`verification-continuation-12.json` | V0；复用E-096～E-101，只读检查QEMU原清单和文件，未启动VM或改变默认客体 |

## 第十三批：CP运行窗口、完成语义和纯参数适配

| Evidence | Command / 输入 | Result | Scope |
|---|---|---|---|
| E-103 | 最终研究源码；`audit-command-13-final.json`及`cp-ui-access-406-13-final.json` | PASS；43.529秒，重新验签、736841帧、147成员、71目标及103同包资源；原24 AP分支、1218刷新查询、864快照消费和资源加载保持 | 输入仍为指定修改4.06；无设备/介质/私钥访问。CP候选13直接调用、595立即数、152窗口只是静态计数 |
| E-104 | E-103的`native_paths.cp_realtime` | PASS；原运行期0x898548、3组参数更新、真实ARM memcpy；4消费者复制、13完成身份/非法13拒绝、6掩码、3上下文选择、4个工作尾部 | 互斥为明确的0x24持有模型；原队列/RTOS/算法主体未运行，流身份和帧寿命未证明 |
| E-105 | E-103的拒绝、共享根反例及JPG窗口 | PASS；锁拒绝仍返回0、2组队列拒绝仍清标记、旧消费者读到新9/5；2组JPG状态保存/事件参数、计数2→1及原池链表更新 | 输入/拒绝/状态为显式夹具，不伪造硬件成功；单个任务完成、ready与回调不满足版本或帧释放确认 |
| E-106 | `af_cp406.*`、E-103的`target_cp406_parameters`、`build-13-verified/commands.json`及E-107中的目标闭环 | PASS；原AP参考12基底、新ARMv7编码、原CP上下文/颜色/锐度派生联验；LUT无写拒绝；两种目标ISA各20槽的参数前缀摘要一致 | 前缀其他字节保持，深层帧/校准为零夹具；ELF66996字节、SHA `ffaddb4c…3cde7b2`，最终重构建逐字节一致。没有安装实际CP挂钩/IPC |
| E-107 | 最终源码/测试；`pytest-13-final.json` | PASS；143 passed in 2.16s，命令退出0且代码运行期间不变 | 实际C、原143项范围含新适配/执行器边界与512地址预算；目标ELF保留在`pytest-13-targets`，非相机验收 |
| E-108 | 最终C；`native-sanitizer-13-final.json` | PASS；ASan+UBSan编译/执行退出0；20000次输入/状态/记录/UI/文档/CP前缀探测及20槽保存/引用/前缀闭环 | 本机内存/未定义行为证据，不证明机身预算或真实并发 |
| E-109 | 最终源码/文档/回执/产物/输入指纹、链接及历史不变性 | 见`verification-continuation-13.json` | V0；复用E-103～E-108，不重复跑成功行为验证；实际机内存储、ISP模型/误差与菜单仍未完成 |

细节和接入放行条件见[CP接入证据](cp-access.md)，复算命令见[第十三批交付](continuation-13.md)。总体保持`NOT_VERIFIED`，未产生可安装固件。

## 第十四批：原AP/OSAL/CP消息、银行发布与JPEG持有

| Evidence | Command / 输入 | Result | Scope |
|---|---|---|---|
| E-110 | 最终源码；`audit-command-14-final.json`及`cp-ui-access-406-14-final.json` | PASS；46.649秒，指定修改4.06重新验签、736841帧/147成员/71目标、同包库/103资源；原24 AP分支、1218刷新/864快照消费及12基底目标适配保持 | 未改DAT/库或研究ELF；OSAL新增同包只读来源核对，不改71项目标基线 |
| E-111 | E-110的`ap_cp_messages`，同包`libosal_uipc.so` | PASS；原12字节封装/分配/来源/ioctl、原CP任务/表分派，9条消息到原快照及颜色/锐度派生；−7发送失败、2类非参数边界及中间混合快照 | ioctl/分配/搬运为隔离后端；完整future、物理IPC/版本握手及CP消息释放未执行；不是实际新槽事件或成像回执 |
| E-112 | E-110的`cp_frame_stages.parameter_bank_publication` | PASS；2银行索引×4掩码共8组，原颜色/锐度getter、根及操作上下文指针独立更新/保留 | 旧指针/待处理位是夹具，未运行并发任务；原发布不校验同一滤镜版本，流身份仍未知 |
| E-113 | E-110的`cp_frame_stages` | PASS；4类LiveView阶段对象/RTTI/虚表静态绑定；5组照片JPG最后请求/三处失败，保留独立持有计数或完成节点/资源池归还 | 原JPG虚表/方法执行，三个驱动结果、锁与诊断为显式夹具；非EVF路由或整帧最后释放证明 |
| E-114 | 最终源码及测试；`pytest-14-final.json` | PASS；149 passed in 6.37s，退出0；运行期间代码不变 | 新库身份/长度/CP拒绝、初始化数据段范围/RW/NX/坏描述符及阻塞锁停止；原实际C与目标ISA闭环保持。C逐字节未改，ASan/UBSan复用E-108 |
| E-115 | 源码/测试/文档/回执/输入/产物及历史不变性，`verification-continuation-14.json` | V0指纹、语法、链接及证据状态核对 | 复用E-110～E-114，不重复执行相同成功验证；整套功能仍未完成，没有安装候选 |

具体调用链、夹具与接入风险见[消息及帧接入证据](communication-frame-access.md)，复算命令见[第十四批交付](continuation-14.md)。

## 第十五批：原子输入、完整银行集合、帧双重屏障与原回复/EVF入口

| Evidence | Command / 输入 | Result | Scope |
|---|---|---|---|
| E-116 | 最终`af_apply.*`/wire及`native_apply.c`，E-120的实际C/目标ISA测试 | PASS；128字节包/独立CRC，20槽、13消费者、三集合、64帧、范围预留/启动/取消/失败排空、旧帧不变/过期回执/会话及耗尽拒绝 | 事件由测试驱动；未接实际任务、帧输出或消息命名空间，不等于物理握手/统一银行已安装 |
| E-117 | 最终ARMv7 ELF与E-122的`cp_atomic_prepare` | PASS；九字段/更新标记及原快照首/中/末3组互斥交错，解锁后全量新值；无锁混合快照反例和非法/LUT无写拒绝 | 原0x24为显式持有模型；输入准备不等于银行生效，真实RTOS/CP入口未安装 |
| E-118 | E-122的`cp_resource_release` | PASS；原成对资源守卫成功/驱动失败两组，节点/使用/持有退役、原缓冲归还函数、句柄清除 | 失败仍有使用标记却摘链回池；仅归还请求，不证明缓冲管理器/像素/DMA或最后帧结束 |
| E-119 | E-122的`cp_reply`/`cp_evf_display_entry` | PASS；5回复成功/分配失败/发送失败回收/两类过滤，原来源和ARM memcpy；EVF两类型绑定、原初始化和0x9059081a通知入口 | 过滤不发送也返回0；分配/队列/诊断为后端，EVF通知前停止；颜色银行/实际显示/版本握手未证 |
| E-120 | 最终源码/测试，`pytest-15-final.json` | PASS；156 passed in 2.83s，命令3.066秒、退出0，源码期间不变 | 新协议/来源拒绝及两种目标ISA实际执行；原UI/保存/CP前缀回归保持 |
| E-121 | 最终C和`native-sanitizer-15-final.json` | PASS；ASan+UBSan重新编译/执行退出0，20000次探测及20槽/13消费者/三银行/64帧完整契约 | 主机内存/未定义行为证据；不证明真实线程、机身预算或成像 |
| E-122 | 最终源码与新研究ELF，`audit-command-15-final.json`/`cp-ui-access-406-15-final.json` | PASS；45.741秒，指定修改4.06重新验签、736841帧/147成员/71目标、同包库/103资源，原24 AP分支/1218刷新/864快照保持 | 源码期间不变；原AP/UI/前缀ELF不变，新原子输入ELF66984字节SHA `58a1b8fb…199aa0b`；无设备或安装 |
| E-123 | 最终源码/测试/文档/产物/输入/历史及链接，`verification-continuation-15.json` | V0指纹、语法、引用和证据状态核对 | 复用E-116～E-122，不重复执行成功行为；总体仍NOT_VERIFIED |

接口、实际地址和阻塞项见[整预设与帧接入](atomic-bank-access.md)，复算及交付文件见[第十五批交付](continuation-15.md)。T03d/T04b2b/T07c/T07d完成各自限定范围，T03/T04/T07与整套固件未完成；T08/T09保持未完成。当前未解出的路由/寿命/ISP格式不能用合成握手或误差替代。

## 第十六批：原收发入口、私有HELLO及消息引用

| Evidence | Command / 输入 | Result | Scope |
|---|---|---|---|
| E-124 | E-130的`native_ap_request_lifetime`，同包AP/OSAL/C++ | PASS；3组原请求：完整原基底发送/包装器/两个C++对象回收/CP消费，−7发送失败后输出0，带回复在无超时futex前停止 | 分配/释放/锁/诊断和ioctl为后端；串行库分支，未执行宿主syscall/真实回复或AP整体启动 |
| E-125 | E-130的`cp_native_message_pool` | PASS；5组原分配/完整接收/引用/归还和空闲块恢复，原不支持命令回复/发送失败释放；旧端忽略HELLO | 24字节头，来源−12/长度−8/引用−14；池描述符/锁/队列为夹具，消息最后引用不是图像最后帧 |
| E-126 | E-130的`cp_native_notifications` | PASS；原EVF24字节封装，0x1234与0x11234实际通知相同；原缓冲标志/查询1→0→1 | 低16位、缓冲句柄/标志均非64位版本或DMA/整帧完成；序列化/发送及真实银行关联未执行 |
| E-127 | E-130的`native_hello_handshake`、新两种目标ISA模块 | PASS；双端真实匿名分支、原128字节收发和消息释放，4组成功/截止/损坏/回复发送失败；默认关闭/旧消息委派/PRESET无写拒绝、精确撤销 | 不分配Sony命令ID；时钟/会话及传输为明确后端，仅入口兼容确认；真实启动/轮询/断线恢复/成像未接 |
| E-128 | 当前最终源码/测试，`pytest-16-verified.json` | PASS；163 passed in 8.30s，命令8.525秒、退出0，运行期间源码不变 | 新握手/来源/BSS范围/NX与原槽位/UI/保存/目标ISA核心回归；SIMD由E-127真实入口覆盖 |
| E-129 | 最终C/头文件，`native-sanitizer-16-final.json` | PASS；ASan+UBSan，20000次探测包含新HELLO/截止/损坏包，编译0.938秒/执行1.148秒、退出0 | 之后仅汇编/Python变化，C/头文件逐字节保持，复用有效主机范围；绝对地址桥接C/S由目标ISA原入口联验，不在宿主调用设备入口 |
| E-130 | 最终源码/研究ELF；`audit-command-16-verified.json`及`cp-ui-access-406-16-verified.json` | PASS；82.968秒，指定修改4.06重新验签/736841帧/147成员/71目标/103资源，原24 AP分支/1218刷新/864快照保持 | 新AP/CP ELF 71536/71032字节，SHA `3dd1eb6f…5562dc65`/`85d741eb…3071ee8`；既有研究ELF和DAT保持，无相机或安装 |
| E-131 | 源码/文档/回执/输入/产物/历史及链接，`verification-continuation-16.json` | V0指纹/语法/引用/状态核对 | 保留初期失败和旧成功回执；最终仅以当前汇编和源码对应证据放行离线范围，总体仍NOT_VERIFIED |

新SIMD哨兵先实际失败并保留`handshake-simd-16-red.json`，随后修复AP跳板的Q0～Q31/FPCR/FPSR保存恢复；旧成功回执不作为新汇编验收。原子银行/最后图像帧、真实时钟与启动、机内持久化、LUT模型/拟合和实际菜单继续未完成。具体范围与复算见[第十六批交付](continuation-16.md)、[消息与握手接入](handshake-ingress.md)。

## 第十七批：原任务启动、单调时钟、轮询与缓冲占用

| Evidence | Command / 输入 | Result | Scope |
|---|---|---|---|
| E-132 | 最终新C运行时及原AP系统导入，构建16命令、E-133/E-135/E-136 | PASS；一次启动、8字节非零随机会话、单调毫秒检查、50毫秒等待/1000毫秒截止，故障关闭及空错误退避 | 无固定会话/墙上时钟回退，64位随机标识有概率碰撞；不是认证或严格重建代号 |
| E-133 | E-137的`native_task_runtime`及新AArch64/ARMv7模块 | PASS；原IWrapperImaging注册、双端原任务启动/接收、原OSAL、15组运行时及故障/旧会话场景；完整寄存器哨兵与精确撤销 | 系统服务/线程创建/IPC为显式后端，完整线程/TLS/栈/物理超时及发送失败缓冲所有权未验收；HELLO不确认成像 |
| E-134 | E-137的`cp_native_notifications.buffer_claim_reuse` | PASS；原0xb2b37e占用/−10拒绝/再占用、旧归还重放清除新占用、其他句柄覆盖全局标志 | 迟到归还为夹具重放；像素分配器/DMA/最后帧未证明，不能以句柄/0x1934564触发owner_end |
| E-135 | 当前源码，`pytest-17-final.json` | PASS；177 passed in 7.09s，命令7.330秒、退出0，源码不变 | 运行时核心/故障/来源/参数门控和既有回归；目标入口与寄存器由E-133覆盖 |
| E-136 | 当前C/头文件，`native-sanitizer-17-final.json` | PASS；ASan+UBSan 20000次含运行时的探测及原契约，编译0.997秒/执行0.511秒、退出0 | 仅主机纯核心；绝对地址桥接和真实系统服务不在宿主调用 |
| E-137 | 当前源码/新运行时ELF，`audit-command-17-final.json`和`cp-ui-access-406-17-final.json` | PASS；151.514秒，指定修改4.06重新验签/736841帧/147成员/71目标/103资源；原24 AP分支/1218刷新/864快照保持 | 新AP/CP ELF 77168/71188字节，SHA `8a2ec37a…bc786903`/`196da0a5…2297beb`；不生成安装候选 |
| E-138 | 源码/文档/回执/输入/产物/历史及链接，`verification-continuation-17-final.json` | V0语法/指纹/引用/证据状态核对 | 初版退避失败、缺失时钟回调复现和旧回执保留，最终以当前运行时源码/ELF及E-137为准；总体NOT_VERIFIED |

T04b2d完成限定离线范围，T03f/T03/T04/T07及LUT/菜单整体仍未完成。空错误缺退避先在原入口复现后修复，保留`runtime-idle-17-red.json`；时钟回调缺失沿用旧值的复现保留于`runtime-clock-port-17-red.json`，修正后所有证据均重跑。运行时来源、剩余银行/帧/拟合依赖和复算见[第十七批交付](continuation-17.md)、[运行时接入](runtime-access.md)。

## 第十八批：原生LUT网格转换

| Evidence | Code State / Step | Result | Scope |
|---|---|---|---|
| E-139 | 固定上游`8b563d46`、公开v2模型与来源回执 | 数值/源码摘要及Git blob身份核对；模型SHA `8879499f…b85a45` | 借鉴网格与响应数学，独立C实现；对方BIN/槽位/地址不移植，模型仅保守允许ST |
| E-140 | `af_grid.h/.c`、`af_grid_fit.c` | 有界预测/优化/量化/取消/独立评估；最多4096样本和256迭代、工作区499436字节 | 无动态分配、文件或libm；只拟合网格，不是完整12基底/CC1/Gamma解算 |
| E-141 | `reference-fit-18.json`中`reference_parity` | PASS；与原`PairedModel/stencil`10000点对照，最大通道差5.3891×10⁻⁷ | 实际数学定义与C对照，未启动上游服务或设备 |
| E-142 | E-146的`native_lut_grid` | PASS；2441项AArch64断言、实际拟合网格与8档模式共9组进入原CP完整打包函数，字节一致且保护区保持 | 原`0x231654`与405项排列实证；不等于像素效果、动态应用或帧寿命 |
| E-143 | `reference-fit-18.json`中4个独立留出案例 | PASS；温和暖色/非线性平均ΔE76约0.757/1.277，反转压力约84.851 | 模型内误差，582训练/1135留出；不保证任意LUT，不是本机实拍验收 |
| E-144 | 当前源码，`pytest-18.json` | PASS；187 passed in 7.03s，命令7.349秒，退出0且源码未变 | 新网格行为及既有相关回归 |
| E-145 | 当前C/头文件，`native-sanitizer-18.json` | PASS；ASan/UBSan 20000次探测与实际拟合/报告/取消，编译1.325秒、执行0.504秒 | 主机核心内存/未定义行为；不覆盖物理服务/成像 |
| E-146 | 当前源码及新网格ELF，`audit-command-18.json`与`cp-ui-access-406-18.json` | PASS；149.056秒，修改4.06验签/736841帧/147成员/71目标/103资源；原24分支/1218刷新/864快照保持 | 新AArch64 ELF 88704字节，SHA `6dfd13fb…062fa1`；输入未改，无安装候选 |
| E-147 | 源码/文档/输入/历史/回执/引用，`verification-continuation-18.json` | V0指纹与语法/引用终检 | 保留排列/取整失败回执和旧产物；总体NOT_VERIFIED |

T08b1完成限定离线转换核心，T08b/T08及实际菜单/存储/成像接线仍未完成。沿用原厂成像、快照和资源管理优先，银行/帧租约研究核心未安装。来源、实证、误差与复算见[第十八批交付](continuation-18.md)、[LUT转换报告](lut-conversion-18.md)。

## 第十九批：原厂完整网格控制器

| Evidence | Code State / Step | Result | Scope |
|---|---|---|---|
| E-148 | `cp_grid_route.py`执行原0x230da8及既有助手/查询/判定/打包 | PASS；6款首次打包/指针发布及重复复用，12种空查询模式阻断，profile字段1的内嵌缓冲 | 全部原指令，无服务返回拦截；不命名未知索引为EVF/JPG |
| E-149 | 同一匿名上下文装入第十八批AArch64实际候选 | PASS；同槽新表/FNV未触发重建的反例，原缓存索引0失效后405字更新且重复复用 | 只改匿名数据页，失效写入器未安装；原来源0xff/0强度规则分别验证 |
| E-150 | 当前源与候选边界及原控制器回退 | PASS；12原厂编号和248/255不误用六款，3类坏头/摘要不应用，非法候选及错误CP在执行前拒绝 | 原来源无表/空句柄为夹具；不覆盖全部原厂ISP状态 |
| E-151 | 当前源码，`pytest-19.json` | PASS；192 passed in 7.25s，命令7.530秒，退出0且源码未变 | 新边界和既有相关回归；C未变复用E-145消毒器 |
| E-152 | 当前源码，`audit-19.json`与`cp-ui-access-406-19.json` | PASS；151.189秒，修改4.06重验签/736841帧/147成员/71目标/103资源，原接入与网格目标联验保持 | 新增`native_lut_grid.native_controller`；未构建新ELF或安装固件 |
| E-153 | 源码/文档/输入/历史/回执/引用，`verification-continuation-19.json` | V0语法、摘要、引用及有效证据核对 | C/旧构建/消毒器证据有效性核对；总体NOT_VERIFIED |

T08b2a限定范围完成；T08b2、真实新增槽解析器/应用、导入菜单及机内保存仍未完成。原表选择地址与失效字段已有局部执行证据，但真实串行拥有者、源表寿命及取景/JPG仍未证明，不安装裸写。见[第十九批交付](continuation-19.md)和[原控制器接线](grid-route-19.md)。

## 第二十批：联合组件与整数搜索

| Evidence | Code State / Step | Result | Scope |
|---|---|---|---|
| E-154 | 用户确认及当前spec，固定上游7份只读源码 | 四组件联合拟合列为必做；核对Edit输入域/16扇区与本包端点增量/18位Gamma差异 | 上游源码只读缓存，不执行/移植模型；原网格响应不能当完整后端 |
| E-155 | `af_joint.c`与E-160的`native_joint_core` | PASS；当前ST/上界源共5组Gamma576字节逐字节一致，矩阵27项/CC1 24项原增量窗口和保护区通过 | 原CP算术窗口及显式基值/栈；完整原函数/绝对系数与像素未证明 |
| E-156 | `af_joint_fit.c`及AArch64研究ELF | PASS；1871断言、65预算、四组件均接受改进，11824字节工作区，训练量化MSE 6.0233244×10⁻⁵→0 | 合成耦合后端和训练集，不是本机真实LUT或留出误差 |
| E-157 | 原生联合测试/目标检查 | PASS；取消、非有限预测、模型中途失败、非法/重叠/错误CP及单网格能力拒绝，输出和结果保留 | 只验证事务与模型契约；声明能力不能证明模型准确 |
| E-158 | 当前源码，`pytest-20.json` | PASS；203 passed in 7.80s，命令8.025秒、退出0且源码未变 | 新联合组件/搜索及既有相关回归 |
| E-159 | 当前C/头，`sanitizer-20.json` | PASS；20000次含联合组件探测与搜索/取消，ASan/UBSan编译1.425秒、执行0.506秒 | 主机内存/未定义行为，不含目标服务或像素 |
| E-160 | 当前源码/联合ELF，`audit-20.json`与`cp-ui-access-406-20.json` | PASS；151.113秒，修改4.06重验签/736841帧/147成员/71目标/103资源，原24分支/1218刷新/864快照保持 | 新ELF80168字节，SHA `632be037…b7bc2`；无安装固件 |
| E-161 | 源码/文档/输入/历史/回执/引用，`verification-continuation-20.json` | V0语法、摘要、引用及有效证据核对 | 原产物不改，真实完整预测未实现，总体NOT_VERIFIED |

T08b2b/T08b2c限定范围完成；T08b2d及T08整体仍待真实全链路模型、联合留出误差和实际应用。不得以合成零误差或组件窗口核对当作“机内联合拟合已完成”。见[第二十批交付](continuation-20.md)、[联合核心与模型边界](joint-conversion-20.md)。

## 第二十一批：原Gamma非均匀采样域

| Evidence | Code State / Step | Result | Scope |
|---|---|---|---|
| E-162 | 当前CP原0xaa8688/0x41363c完整选择/构造 | PASS；12原厂/6既有各7列共126组，129点域0～65535，当前均为同一非均匀轴 | 影子原载荷、零调试全局、数值列/指定更新输入；不证明真实模式或启动 |
| E-163 | `af_gamma406.c`与新AArch64扩展 | PASS；原轴逐字节一致、9组整数区间、8组ST/PT/FL2/FL3完整候选消费，附属字段与保护区保持 | 不实施或推测硬件插值/舍入，不把横轴直接等同显示sRGB |
| E-164 | 原标记249/行51的匿名候选 | PASS；原包装器继续施加旧tone，与独立整数期待一致、不同于最终候选 | 仅复现旧增量与完整曲线语义冲突，未改旧包装器或操作机身 |
| E-165 | 新组件/入口拒绝测试 | PASS；初始缺源码失败后实现；扩展符号地址漏检先失败，修复后在CPU前拒绝；坏元数据/重叠/错误CP不发布 | 失败回执保留；模拟ELF元数据只验证边界，真实ELF另由E-168执行 |
| E-166 | 当前源码，`pytest-21.json` | PASS；210 passed in 7.90s，命令8.135秒、退出0且源码未变 | 新Gamma域/记录与既有相关回归 |
| E-167 | 当前C/头，`sanitizer-21.json` | PASS；20000次含Gamma域/联合探测；ASan/UBSan编译1.431秒、执行0.545秒 | 主机内存/未定义行为，不含硬件/像素 |
| E-168 | 当前源码/新ELF，`audit-21.json`与`cp-ui-access-406-21.json` | PASS；153.548秒，修改4.06验签/736841帧/147成员/71目标/103资源，旧接入保持 | 新模块80568字节，SHA `0d5ca328…6ea600`，新增原Gamma完整构造联验 |
| E-169 | 源码/文档/输入/历史/回执/引用，`verification-continuation-21.json` | V0语法、摘要、引用及有效证据核对 | 全部旧产物保持，真实全颜色模型/设备验收仍未完成 |

T08b2d1限定离线范围完成；T08b2d、T08、实际用户槽成像及菜单/机内保存继续未完成。未将非均匀横轴或原Gamma构造当作完整联合预测，见[第二十一批交付](continuation-21.md)、[Gamma参数域](gamma-domain-21.md)。

## 第二十二批：联合候选与管理事务

| Evidence | Code State / Step | Result | Scope |
|---|---|---|---|
| E-170 | `af_joint_asset.*`与独立小端/SHA期待 | PASS；1943字节完整配方、CP/模型/基底、最终Gamma和研究标记，头/正文损坏与未来版本拒绝 | 未批准为机身ISP schema，不安装CP读取器 |
| E-171 | `af_joint_report.*`、`af_grid_color_report`与24色独立数学 | PASS；非零平均/P95/最大/灰阶/肤色ΔE76及裁剪，差≤0.00015 | 最终8位sRGB/D65模型误差，不是传感器/机身测量 |
| E-172 | `af_import_cube/document/asset` | PASS；四组件同一后端搜索与独立留出、进度/三阶段取消、样本重合/预算/后端失败不发布 | 显式合成后端8训练/4留出只验事务，不提供默认真实模型 |
| E-173 | `af_persist_rename/export`和普通临时目录全链 | PASS；8项调参、重命名保留工作值、保存/工作双导出、保存/另存/墓碑、擦除输入后的新目录恢复 | 发布后不确定冻结、容量/重叠拒绝；未操作SD或机内存储 |
| E-174 | 最终123672字节研究ELF、AArch64实际执行 | PASS；2273检查，146948字节工作区、2236字节候选、代号5、71进度单位 | 内存后端和合成模型，不是AP菜单/系统服务或原CP应用 |
| E-175 | 当前源码，`pytest-22.json` | PASS；230 passed in 8.78s，命令9.023秒、退出0且源码未变 | 新20项及既有相关回归 |
| E-176 | 当前C/头，`sanitizer-22.json` | PASS；20000次含整份配方损坏和已有状态探测；ASan/UBSan编译1.819秒/执行1.231秒 | 主机内存/未定义行为，附同源原生事务 |
| E-177 | 当前源码/最终ELF，`audit-22.json`与`cp-ui-access-406-22.json` | PASS；150.084秒，修改4.06验签/736841帧/147成员/71目标/103资源，旧接入与Gamma/网格联验保持 | 新`offline_import_transaction`，不生成安装包 |
| E-178 | `verification-continuation-22.json` | V0源码、文档、输入、历史产物、构建来源及引用核对 | 旧产物不变，父任务及总体NOT_VERIFIED |

T08b3a/T09a的离线核心完成；T08b2d/T08b3/T08及T09实际接入仍未完成。未将研究配方、普通目录或合成零误差当成完整机内功能，见[本批交付](continuation-22.md)、[导入与管理事务](import-transaction-22.md)。

## 第二十三批：原颜色完整构造和插值消费

| Evidence | Code State / Step | Result | Scope |
|---|---|---|---|
| E-179 | `cp_color406.py`原完整`0x71e41e`与新C/AArch64 | PASS；186组矩阵、三独立校准、逐扇区/统一bank/内嵌表及回退、54字节/保护区 | 普通属性/校准为显式夹具；原内嵌FL2/FL3系数来自同包 |
| E-180 | 原完整`0x71e670/0x71e9c8`与新原生重建 | PASS；66主域（62写入）、134第二域（112完整/22诊断停止），符号修正/差分/元数据/无写入路径 | 原诊断前停止，未模拟诊断返回；动态校准分支未验证 |
| E-181 | 当前六款实际载荷、原包装器和`af_color406_add` | PASS；18组身份/flag门控、108次完整构造，构造后增量与第二域元数据保持 | 匿名原载荷影子，不执行整机引导或实际槽迁移 |
| E-182 | 原完整`0x71b8a0`常规路径与独立整数/AArch64 | PASS；180组两级Q8插值、权重0/128/256、原状态元数据及保护区 | 合成阈值和数值参数，不认定色温/曝光或ISP像素 |
| E-183 | `pytest-23.json`及目标颜色契约 | PASS；241 passed in 9.21s，命令9.533秒；目标127检查，扩展成套/范围在CPU前拒绝 | 当前代码状态、11项新增及旧相关回归 |
| E-184 | `sanitizer-23.json` | PASS；20000次含随机颜色端点/插值；ASan/UBSan编译1.986秒/执行1.099秒 | 主机内存/未定义行为，不含硬件或颜色标定 |
| E-185 | 最终ELF，`audit-23.json`与`cp-ui-access-406-23.json` | PASS；155.753秒，修改4.06验签/736841帧/147成员/71目标/103资源，Gamma/导入及旧接入保持 | 新`native_color_context`；最终121880字节研究模块，未生成安装固件 |
| E-186 | `verification-continuation-23.json` | V0源码、文档、输入、历史产物、构建来源及引用核对 | 保留并行QEMU实验目录，未扩大修改范围；总体NOT_VERIFIED |

T08b2d2限定离线范围完成。真实联合像素模型、当前运行条件与用户槽成像应用仍待T08b2d/T03/T07，菜单和机内存储仍待T01/T02/T05/T06/T09；不是仅差真机测试。详见[本批交付](continuation-23.md)、[原颜色构造与消费](color-parameters-23.md)。

## 第二十四批：完整矩阵消费与动态校准

| Evidence | Code State / Step | Result | Scope |
|---|---|---|---|
| E-187 | 原`0x71e74e/0x73e654`、完整主/第二域、新解码 | PASS；6组动态/回退/禁用，24组主域及24次第二域；符号、未选指针不可读和原不写保持 | 动态/全局字节为夹具，未取得真实校准；原不支持第二域未开放 |
| E-188 | 原完整`0x71d37c`、独立整数和新AArch64 | PASS；72组×16=1152扇区，原差分舍入/饱和、旧六款门控、状态副本及写区/保护区/源保持 | 常规profile；时间平滑/额外矩阵关闭，不含像素或硬件上传 |
| E-189 | 原`0x719ef6`前缀及整函数失败探测 | PASS（前缀限定）；ST/FL2/FL3到网格前停止，双profile字段及错配矩阵反例；整函数在`0x230de6`停止 | 不完整上游夹具，不是相机故障；不扩大映射或伪造返回，整包装器未验证 |
| E-190 | `pytest-24.json`及目标颜色契约 | PASS；247 passed in 9.18s，命令9.413秒；目标168检查，新增独立有理数/扩展元数据拒绝 | 当前代码状态及相关回归，源码未变 |
| E-191 | `sanitizer-24.json` | PASS；20000次含动态字节/矩阵混合探测；ASan/UBSan编译1.921秒/执行1.133秒 | 主机内存/未定义行为和原生事务，不含相机 |
| E-192 | 最终ELF、`audit-24.json`及`cp-ui-access-406-24.json` | PASS；156.399秒，修改4.06验签/736841帧/147成员/71目标/103资源；原Gamma/导入/网格/UI/运行时保持 | 新`native_color_consumption`，121976字节研究ELF；不生成安装固件 |
| E-193 | `verification-continuation-24.json` | V0源码、文档、输入、历史产物、构建来源及引用核对 | 不介入其他QEMU任务；上游身份、完整模型和总体仍NOT_VERIFIED |

T08b2d3限定离线范围完成。原厂上游profile/权重生产器、完整网格对象及实际像素/EVF/JPG仍待T08b2d/T03/T07；菜单和机内保存未接通。见[第二十四批交付](continuation-24.md)、[原颜色消费与身份约束](color-consumption-24.md)。
