# 固定 32 槽创意外观：实施入口

当前第41批新增[CUBE／电脑配方双入口](../specs/001-fixed-custom-filters/integration-41-dual-entry.md)：SD浏览同时接收`.cube`与现有`.a7filter`。CUBE沿用机内拟合；完整AJR2或纯参数AFD1无需拟合模型即可校验、保存到同一用户槽。新增[电脑配方封装工具与用法](tools/README.md)，不新增电脑训练器或对方BIN兼容。619项当前宿主回归通过、6项不适用跳过，13项加载边界另列；配对模块、新未签名USR、367来源和74组件独立回读见[本批交付](../../.local/fixed-custom-filters/implementation41-dual-entry-final/交付说明.md)。

第40批原生接线见[接线与边界](../specs/001-fixed-custom-filters/integration-40-native-and-ui.md)：32槽/八项原UI、C01～C06明确overlay、默认参考LUT转换／保存／完整发送、CP worker与四组件入口及真实HELLO后的启动发布已落源码，沿用原厂分组失败行为。该批565项及未签名USR按[历史离线审计](../../.local/fixed-custom-filters/implementation40-final/verification.json)保留，不能当作新双入口源码的证据。

完整目标尚未完成：其他原厂基底LUT模型、最终EVF/JPG流身份及第二Gamma来源仍缺；当前默认固定ST参考模型不保证机身色差，实际启动／介质／照片未验证，禁止刷入准备镜像。存在一次已停止的旧Unicorn误执行，具体与失败记录见第40批DEV-001；未操作相机。以下第38批及更早内容按历史范围阅读，不作为当前未实现项清单。

## 第38批及以前的历史检查点

2026-10-31当时检查点见[完整消息、四处复制与独立四页](../specs/001-fixed-custom-filters/integration-38-native-bridge.md)。完整配方已接实际AP／CP消息函数的软件入口，DBC／三E70原调用共用常驻回退，原栈真实VD与输入版本已伴随传递，复制中故障竞态已修复。当时含公开读取ABI的CP分支RX12268／12288B、RW628B、原尾404／408B；最终页表权限和CRC才授予执行，原页表／栈／旧六款保护保持。431项宿主回归及交叉链接按该历史源状态保留。

完整原生成像消费者仍未绑定，FULL_RECIPE实际协商、UI的kind1和32槽发布继续关闭。旧4KiB容量不足属于已解决的历史布局问题；当前依赖是原VD/C4真实输入版本、原bank内四组件应用及CPU输入借用退休。下方第37批转换／保存记录继续有效，不将新消息入口或放置验证当成取景/JPG完成。

第37批转换交付见[10月31日默认参考转换与导入](../specs/001-fixed-custom-filters/integration-37-reference-import.md)：Gamma／矩阵／CC1／经验网格完整近似预测、17维受约束联合求解已接实际默认IMPORT服务及启动能力绑定。真实中文CUBE转换、保存／删除输入后恢复及同一配方28帧接收／软件ACK通过。当时370项宿主回归、13项启动检查及目标编译链接通过；未运行目标、硬件模拟或相机。

第37批当时的4KiB超限现由上述四页方案解决；原生四组件同快照／packed寿命及实际消息安装仍未闭环，完整功能继续`NOT_VERIFIED`。默认ST参考／固定PT经验格为有来源近似，误差是模型内误差；机身存储／旧六迁移及取景JPG仍未验收，准入与UI发布保持关闭。原修改版4.06、原厂含FL2/FL3及旧六款材料未改写。

## 此前阶段记录

第32批软件交付见[10月30日剩余接线](../specs/001-fixed-custom-filters/integration-32-software.md)：完整LUT另存／改名／导出／非当前清空、原厂九字段快照及配对回退、显式研究UI请求、参考RAW前端及旧六槽快照适配；当时187项宿主测试通过。下方记录按原日期／代码范围保留，不能以旧“IMPORT未就绪”覆盖本轮默认转换已接入的事实。

最新实施见[主线记录](../specs/001-fixed-custom-filters/mainline-progress.md)、[验证证据](../specs/001-fixed-custom-filters/verification.md)和[10月30日继续实施](../specs/001-fixed-custom-filters/integration-30.md)；此前完整原菜单实帧见[integration-28](../specs/001-fixed-custom-filters/integration-28.md)。整体仍为`NOT_VERIFIED`，未操作相机、真实SD或覆盖现有修改4.06，未生成可刷写固件。

10月30日已完成C07～C20纯参数覆盖、非当前槽清空及原键盘重命名的限定离线闭环：两段真实确认、默认取消／悬停零任务、当前槽保护、记录与健康墓碑在全新AP恢复。覆盖207帧、清空143帧；改名最终78项、后续三轮206原帧核对通过，四种原键盘显示“滤镜名称”，实际输入d／新AP恢复，dirty工作与保存值分离。仓库15项真实目录与15组ASan／UBSan通过。未观察任何init或D4的open拒绝仍留M4；完整LUT模型和机身介质尚未开放。

原4.06界面的32项导航、八项／十二基底及FL2／FL3、中文名称／编号／Reset隔离已有对应实帧。本轮41挂钩／88前像接通真正ENTER确认、创建／保存／另存与取消自动返回，修复用户槽重入回ST；C07／C20真实保存记录经独立解码后在全新AP客体正常启动恢复，无catalog内存seed。最后两轮97及51次Qt操作的原始帧与PNG一致，Qt／QMP均退出0；最后77项相关测试通过。原厂690及163项保持。

`af_media`已接显式fd扫描／双遍稳定读取，原浏览器第二页实际选择中文`.cube`文件并核对130字节及摘要。`af_repository/service`已接完整记录保存、名称发布和恢复；最新能力0x3b服务已在原键盘客体实际加载，不含IMPORT。读取后明确显示“LUT转换尚未就绪”，无IMPORT任务，不把浏览成功当转换完成。实际机身路径／VFAT／空间／掉电、SD绑定及旧六槽迁移仍未准入；客体RAM保存不等同机内耐久性。导出的完整AP菜单仍待接入；最新墓碑损坏仍可能回退旧完整版本。

两参考项目的数值来源按提交固定；10月30日另核对Hearts-Ace新提交和固定PT平色数据，不自动替换本包模型。七个颜色算子、完整Gamma／逆表／矩阵表及三组件候选适配／缓存已执行；sRGB桥和当前CP非零网格的完整联合预测仍缺证。原池查询、四核RTOS及同源TOMCO自然group2已实际执行；加载原完整.data后，当前在原看门狗MMIO写f1388344时DataAbort，1651个完整TB源PASS、QMP0，整体BLOCKED_ORIGINAL_WDT_MMIO。原银行／AP/CP输出、EVF/JPG及最后帧仍未闭环，IMPORT保持关闭；未将硬件当RAM或跳过初始化。旧六款材料一致性已核对，实际个人设置与迁移仍缺证，C01～C06继续原委派。

独立`af_edit_cp_gamma.*`另将公开ST与本包CP第6列的精确锚点落实为摘要绑定的数值适配：共同点X×32/Y×2，不能表达的61440自由度明确拒绝，宿主5项及AArch64实际11项通过。它不改变旧18位坐标桥，也不标识真实EVF/JPG或提供完整四组件模型。

既有完整预设、编辑/保存事务、普通目录恢复、有锁CP输入、运行时及四组件联合整数搜索继续保留；分模块历史结果在下方列出，不能将旧阶段的通过范围扩大为当前完整机内功能。完整LUT目标仍为Gamma/矩阵/CC1/网格联合拟合，优先复用原厂成像和资源管理。参考及数值范围见[REFERENCE.md](REFERENCE.md)。

## 输入与继承

只接受现有修改研究4.06，754525608字节，SHA-256：

```text
3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2
```

`baseline.json` 锁定AP、CP、68份菜单资源及WBI。原厂4.00只作对照，不调用旧的原厂→4.06补丁器。保留FL2/FL3、六款滤镜、矩阵/Gamma/色度、名称、NTSC、声音候选和现有加载逻辑；后续修改需给出增量白名单与回归，不能以当前静态审计代替新增功能验证。

## 当前可运行的功能

1. `a7filters.baseline`：只读普通DAT，检查固定输入摘要、外层CRC、研究公钥验签、全部解密帧、明文头、全部归档成员、内部校验清单、更新器及71项目标文件。匿名明文关闭后释放；不导出固件、不读取私钥、不访问设备。输入开头/结尾均核对摘要。拒绝 `/dev`、`/Volumes`、系统路径和符号链接。
2. `--investigate`：针对当前4.06核对19条列表、144条模型/备份绑定、8个setter及AP通知/CP接收字段；以Unicorn执行当前AP的真实查找指令窗口，对19条原记录和33条合成记录进行54次查询。合成记录只验证循环边界，不分配真实菜单ID，不证明呈现器容量、完整界面启动或实际逐帧消费。
3. `native/af_slots.*`：12个原厂身份与20个用户槽命名空间分开，基底和八项参数验证、独立工作/保存/初始值、覆盖拒绝、异步保存快照、失败保留和过期回执拒绝。只改变调用者内存；`af_finish_save(...,1)` 必须由未来真实存储适配器在持久化成功后调用，不能拿测试确认冒充设备保存。
4. `native/af_cube.*`：无动态分配、无文件/locale依赖的有界三维CUBE解析，及红轴最快的三线性求值。支持TITLE、LUT_3D_SIZE、DOMAIN_MIN/MAX、注释和CRLF。拒绝1D/混合/未知指令、重复头、缺/多行、NUL、非有限/超范围值和容量超限。最长行4096字节、尾数最多32位十进制数字、指数绝对值最多64；最大文件长度/维度由调用者显式提供，产品上限仍需资源测量。输出结构仅成功后发布，样本工作区是候选暂存区，失败时不可当作有效滤镜。**解析/求值不是原生ISP色表拟合**，不推断源文件为sRGB，不接收视频Log能力声明。
5. `a7filters.access_evidence`：通过`--investigate`执行当前AP/CP及同包两个Backup库的69组接入场景：7组有界枚举、34次选择分派、7组Backup消息/错误、3组同步包装器、3组BackupManager既有记录检查、8个CP接收器、5档锐度范围转发、2种双缓冲索引。描述符/可见性、消息服务和构造器/完成回调是明确夹具边界；未访问服务端或硬件。辅助库另行核对摘要，不改71项目标清单。具体证据、错误串链修正和接入缺口见[接入证据](../specs/001-fixed-custom-filters/access-evidence.md)。
6. `a7filters.native_paths`：同一审计再执行18组原厂通路场景：3组父项缓存扩行、4组功能门控/挂载、6组文件写入错误、5组真实CP初始化来源/上下文链。原厂ARM memcpy也执行原指令；系统调用停在模拟器内。当前包确实含LUT代码，但本机启用值、空间和照片适用范围未知；原厂文件写入器吞掉同步/关闭错误。详见[原厂通路补证](../specs/001-fixed-custom-filters/native-paths.md)。
7. `native/af_record.*`：32字节显式小端头、槽号/版本/代号/长度/双CRC校验、不透明载荷封装和双副本恢复选择。拒绝未知版本和同代冲突，代号不回绕，失败不发布输出。该模块只计算记录和下一写入位置；完整载荷和事务由第15～17项接入。[格式契约](../specs/001-fixed-custom-filters/record-format.md)。
8. `native/af_ui.*`：固定33行身份（32槽＋特殊项）到12原厂/20用户槽的分流，八项工作值读取、步进、直接赋值及原厂显示记录输出。保留旧身份，C07～C20研究身份为0x15d9～0x15e6，避开原厂哨兵0x15d8；此前候选块已撤回。用户路由不提供原厂数组索引，原厂返回明确的委派状态。显示标记按原厂“受限”语义：0允许，1受限。该通用核心不含AP绝对地址。
9. `--investigate-ui`：从同一已验证DAT读取并核对C++库，执行原厂5591→5605行注册、重复插入、1589项页面映射、32名称分派及选中名称呈现写入、128组原厂参数回调。在内存为68份UXC追加C07～C20默认名并反向核对，不写资源文件。可加`--ui-adapter`执行本地AArch64测试ELF，联合验证320次模拟器入口分流和320次读取；它不安装AP挂钩。具体容量边界和剩余改动见[界面接入清单](../specs/001-fixed-custom-filters/ui-access.md)。
10. `native/af_ap_ui.c/.S/.ld`、`a7filters.ap_ui_hooks`、`ap_ui_selection`及`ap_ui_initialization`：离线AP研究模块，24处真实分支及原指令跳板，真实注册初始化窗口、33行枚举和165次行尾解析。40次用户列表提交隔离、26次原厂/特殊项委派、130次双向导航/环绕及32名称窗口保持。第八批补齐20用户调参初始化、12原厂初始化、空槽/重入/限制/禁用拒绝；FL2/FL3内部编号映射及12种种子/4非法拒绝通过。40次用户基底回调阻断、2次原厂回调委派，独立基底编辑尚未开放。20槽320次步进、480合法/320非法赋值及128组原厂按键保持；1218次刷新判定窗口、864次原厂快照消费通过。活动对象、事务、无关字段计算和帧驱动仍为夹具边界；完整组件/回调构造、焦点与导航接入见下一项，无整帧/绘制验收。默认关闭，基址0仅供研究，严禁将ELF用于机身。完整初始化、模式、UXC、CP及持久化仍未闭环。`--ap-ui-module`只写匿名内存，不导出AP。
11. `a7filters.ui_components`、`ui_hash_runtime`：第十批执行原107项完整构造、15条全局焦点回调注册、六个关联容器及原析构；234个所属分配全部释放，不再手工构造回调/附属散列表。原参数导航16组双向/环绕、2组禁用跳过及非赋值焦点消息通过；20槽八项输入保持。扩容及六种辅助函数执行同包C++/libgcc代码，错误库在执行前拒绝。默认节点64字节限制和1MiB池保持，88/136/184字节桶仅原调用点例外；65字节、错误桶调用点及重复释放拒绝。通用内存、锁/通知和退出登记仍为边界；C++库初始化、全AP启动、Qt页面生命周期和触摸轮盘未验收。细节见[第十批接入记录](../specs/001-fixed-custom-filters/ui-access.md)。
12. `a7filters.ui_cache`：以原厂构造器注册5591项二级别名表，检查19个原身份及14个新身份，执行全局缓存初始化的14个新行跳过窗口，确认不写旧缓存。只证明该窗口；其他二级身份消费者和完整AP初始化仍未验收。
13. `a7filters.ui_resource_lookup`：执行同包libObj.so的0x122930/0x122870指针窗口；68份原始/追加资源、20用户文字名称共2992次查询，含1224次缺失/越界空返回。该窗口本身不验证文件获取和其他命名空间，后续完整文件/名称加载见下一项。
14. `a7filters.resource_vm`、`ui_resource_loader`、`resource_guard`及`native/af_resource_guard.S`：第十一批用只读内存文件后端进入原文件对象、UXA/UXC路径解析/魔数检查、缓存和引用/回收。103份同包文件含34份原厂_f名称文件，34语言原始/追加68组、3536次查询；保留12原厂（含FL2/FL3）及旧六款，新增14默认名只在68份用户资源副本。272次打开均关闭并撤销映射，1564块所属分配均有释放记录。先复现原MAP_FAILED无效读取，再在匿名库副本加入4字节分支/20字节跳板，真实失败关闭路径及正常272次映射通过并精确撤销；不将−1改成0模拟成功。引擎上下文/POSIX/内存为显式后端，原库未写入；实际装载/权限/线程、AP联合调用、字体/整帧、CP和保存仍未验收。当前93项回归及完整审计命令通过，[第十一批详细记录](../specs/001-fixed-custom-filters/ui-access.md)。

15. `native/af_document.*`、`af_sha256.*`：AFD1完整字节载荷，保存名称、基底、初始/保存八项参数、完整成像字节、摘要、转换版本与误差元数据；UTF-8、预算、未来格式/未知schema和成像摘要均校验。误差只对初始值适用，`af_document_report_applies`在调参后返回不适用。支持规范化墓碑。没有为实际ISP分配已批准schema，也没有计算拟合误差。
16. `native/af_store.*`、`af_posix.*`：显式后端、双副本完整语义恢复、过期目录保护、暂存→同步关闭→发布→目录同步→回读事务。发布后不确定结果冻结写入，必须显式恢复。本地适配器只使用调用者传入的普通私有目录fd，拒绝符号链接/非普通文件，不自动选择设备或机内路径。真实POSIX短写/EINTR、ENOSPC、同步/关闭失败已注入验证；不是机身掉电验收。
17. `native/af_persist.*`：连接同一个编辑目录与完整存储，提供加载、显式替换、保存、另存和清空；保存期间继续调参只更新对应保存快照，工作值继续为未保存。另存保留源初始值和报告基准，源工作值作为目标保存值。C20的八项UI分流和真实临时目录联验通过；两种目标指令集分别完成20槽内存后端闭环，未接实际AP菜单或CP。
18. `native/af_versions.*`：三个有界不可变银行与最多64个独立引用，待应用版本有唯一令牌；成功确认才切换，失败保持旧版，在用银行不覆写，重复/过期确认和释放拒绝。仅单次初始化生命周期，跨进程/重启需另行会话握手；没有实际CP回执或帧完成信号。`a7filters.cp_updates`额外统计真实CP的状态/上下文候选引用，完整计数、按类限制窗口，不当作实时消费证据。
19. `native/af_cp406.*`、`a7filters.target_cp406`：12种原厂基底与八项值的4.06纯参数前缀适配；原AP转换参考、新ARMv7指令编码、原CP构造/颜色/锐度消费窗口通过。其他前缀字节保持，非法/重叠/短缓冲和LUT明确拒绝；字段匹配不是应用确认，前缀不是完整帧根，未安装CP挂钩。
20. `a7filters.cp_machine`、`cp_realtime`：锁定CP原代码RX、RAM预算和隔离执行器，执行运行期有锁复制、四消费者、13身份完成、掩码、队列拒绝、工作尾部和JPEG回调/部分退役。原锁拒绝仍可能返回0，拒绝排队也清标记，C4浅复制会读到新共享根；不可据此确认成像成功或释放银行。取景/JPG流身份及真正帧释放仍未证明，详见[CP接入证据](../specs/001-fixed-custom-filters/cp-access.md)。
21. `a7filters.ap_cp_messages`：从同包读取并锁定`libosal_uipc.so`，执行原AP封装/分配/来源/ioctl封装与原CP任务/表分派，9条消息进入原快照及颜色/锐度派生；物理ioctl与搬运为隔离后端。中途快照、发送失败仍有输出0、高光/阴影/褪色额外标记均已验证，不能直接把9条命令当作预设事务。
22. `a7filters.cp_frame_stages`：原LiveView阶段类型/对象绑定，8组颜色/锐度银行独立发布和5组JPEG最后请求/持有/归还路径。请求计数+0x28与持有+0x6c独立；即使请求为0仍可能有引用。原类型名称不证明EVF身份，资源归还不证明整帧释放，详见[消息与帧接入](../specs/001-fixed-custom-filters/communication-frame-access.md)。
23. `native/af_apply.*`、`af_apply_wire.c`：128字节纯参数研究包、源AP/CP身份/会话/64位版本检查；三组银行集合，生成前预留全部独立范围、显式启动、全部成功统一发布，失败排空后回收。未启动可立即取消；每帧最多64租约，全部输出和拥有者双重退役后解引用。实际消费者/输出身份及transport没有绑定，不提供设备确认。
24. `native/af_cp406_state.*`、`a7filters.cp_atomic`：新ARMv7有锁整组输入与额外更新标记；原CP快照的首/中/末3组交错，以及无锁混合快照反例通过。`--cp-atomic-adapter`仅在隔离CP执行，不能用于安装；原消息任务已持锁时只能接叶函数。
25. `a7filters.cp_release`、`cp_reply`、`cp_display`：执行原资源守卫到缓冲归还请求的成功/失败两组、5组原回复发送/失败/过滤、原EVF执行器/输出命令初始化与通知入口。错误路径也可能返回0或归还节点，不能据此确认版本生效或最后帧释放。详见[整预设与帧接入契约](../specs/001-fixed-custom-filters/atomic-bank-access.md)。
26. `native/af_handshake.*`、`af_hs_ap406.*`、`af_hs_cp406.*`及`a7filters.native_handshake`：私有128字节HELLO在原收发入口的双端匿名分支接入。成功、迟到、损坏、CP回复发送失败4组通过，原释放/委派和PRESET无写拒绝保持；AP通用/SIMD/NZCV/FPCR/FPSR保存恢复。仅兼容确认；后续运行时接入见第28项，不开放成像；参数成对提供，见[消息与握手接入](../specs/001-fixed-custom-filters/handshake-ingress.md)。
27. `a7filters.ap_request`、`cp_message_pool`、`cp_notifications`：原AP完整单向包装器/C++回收、原带回复futex前停止，原CP完整任务/消息池/引用归还，以及EVF通知低16位碰撞与缓冲标志查询。消息最后引用不等同图像帧最后引用，未发起宿主syscall或硬件服务。
28. `native/af_runtime.*`、`af_runtime_ap406.c`及`a7filters.native_runtime`：原通信任务启动、8字节非零随机会话、CLOCK_MONOTONIC毫秒值、50毫秒有界接收/1000毫秒截止、空消息分流和异常退避；CP只初始化未配置状态，不重置已绑定会话。原AP注册器和15组双端运行场景通过；新接收跳板保持完整寄存器状态。原系统服务均为显式后端，物理驱动/完整TLS/安全重建及发送失败缓冲所有权仍未验收。原缓冲占用/归还还验证了同句柄旧归还及全局标志覆盖反例，不能当作帧版本；见[运行时接入](../specs/001-fixed-custom-filters/runtime-access.md)。
29. `native/af_grid.h/.c`、`af_grid_fit.c`及`a7filters.native_grid`：CUBE到5×9×9七位三通道网格的有界拟合、量化、取消与独立留出误差。工作区499436字节，最多4096样本、256迭代，无动态分配或目标libm；报告ΔE76及RGB RMSE。公开paired响应模型已按E-223纠正为PT固定参数来源，原捕获摘要默认拒绝，数值夹具仅用于数学实验；来源及许可见[参考说明](REFERENCE.md)。AArch64实际拟合及原CP `0x231654`完整函数共9组打包对照通过；与上游实际数学实现10000点最大通道差约5.4×10⁻⁷。只证明模型数学和本包布局，未连接SD菜单、机内存储或成像应用；不能保证任意LUT或12基底效果。详见[转换实现与误差](../specs/001-fixed-custom-filters/lut-conversion-18.md)，`--grid-adapter`仅接受独立研究ELF、只在匿名内存执行。
30. `a7filters.cp_grid_route`：从原`0x230da8`完整控制器进入，执行现有六款选择/校验、更新判断、打包和原缓冲指针发布。原厂/未知身份及坏头/FNV回退保持，空查询句柄模式仍阻断。AArch64拟合产物在匿名首表替换后，未失效会保留旧打包；原索引0单段失效可重打包并恢复缓存复用。两种来源分类的强度更新条件分开验证，不伪造查询返回，不安装新槽选择或失效写入器；见[原控制器接线](../specs/001-fixed-custom-filters/grid-route-19.md)。
31. `native/af_joint.*`、`af_joint_fit.c`及`a7filters.native_joint`：129点18位Gamma、三端点矩阵/CC1增量和网格的约束与共同整数搜索，有限预算、整组合量化选优和取消/失败不发布。矩阵6→9项展开、Gamma记录和原CP 5组Gamma/2组端点增量窗口核对通过。AArch64合成耦合后端1871检查、四组件均接受改进；工作区11824字节。该后端验证搜索契约，不是本机像素模型；实际基底/域/端点/完整组合预测与联合留出误差仍待接入。`--joint-adapter`只执行研究ELF，见[联合核心与模型边界](../specs/001-fixed-custom-filters/joint-conversion-20.md)。
32. `native/af_gamma406.*`、`a7filters.cp_gamma406`：原576字节记录的非均匀129点轴、原整数区间定位和完整候选替换。原选择0xaa8688/构造0x41363c共126组，与新AArch64轴一致；8组ST/PT/FL2/FL3完整候选消费及1组旧六款tone继续处理边界通过。扩展复用`--joint-adapter`并兼容旧模块；不假定硬件插值或sRGB桥，不安装实际曲线应用，见[Gamma真实参数域](../specs/001-fixed-custom-filters/gamma-domain-21.md)。
33. `native/af_joint_asset.*`、`af_joint_report.*`、`af_import.*`：1943字节小端研究配方、同一完整预测的独立留出误差、CUBE候选事务与恢复后配方核验。无默认颜色后端；参考模型和基底/参数/seed须由调用方明确绑定。取消/失败不发布候选，最终Gamma不作为旧tone增量，报告为8位sRGB/D65 ΔE76千分之一单位。转换工作区146948字节，最大CUBE暂存431244字节；这些不是机身资源测量。`af_persist_rename/export`联接重命名、保存/工作双导出和完整副本恢复；本地目录与AArch64内存夹具分列，尚未接实际AP菜单/SD/机内存储/CP。详见[导入与管理事务](../specs/001-fixed-custom-filters/import-transaction-22.md)。
34. `native/af_color406.*`、`a7filters.cp_color406`：当前CP完整矩阵、CC1主/第二域的半字重建、构造后增量和常规两级Q8插值。186组矩阵、66组主域、134组第二域（112完整/22诊断停止）、18组旧六款门控和180组原插值与独立参考及AArch64一致。普通属性/校准/阈值为显式数值夹具，本包内嵌FL2/FL3系数来源独立；不把参数构造当作像素模型，不开放原诊断拒绝的第二域。原Gamma、导入与旧接入结果保持，见[原颜色构造与消费](../specs/001-fixed-custom-filters/color-parameters-23.md)。
35. `a7filters.cp_color_consumption406`及新增校准/矩阵混合算子：6组完整动态/回退/禁用修正、24组主域/24次第二域、72组完整矩阵共1152扇区，与独立参考及AArch64一致，保留首扇区状态副本和源。原`0x719ef6`选择→CC1→矩阵前缀在网格前停止，固化ST/FL2/FL3双profile字段反例；整包装器缺少原网格对象的失败另存。时间平滑/额外变换关闭，实际上游生产器、像素/EVF/JPG未验证，见[原颜色消费与身份约束](../specs/001-fixed-custom-filters/color-consumption-24.md)。

原生核心要求单一事件线程串行调用；保存请求通过令牌确认。它不是跨线程锁，版本核心也尚未接实际CP帧协议。结构仅作内存ABI，不直接序列化填充字节。实际机内存储、原厂成像应用及必要引用寿命仍待T02/T03/T04b2。第二十四批247项回归、ASan/UBSan的20000次含动态字节/矩阵插值探测及目标事务联验通过。原生目标执行和本地文件结果均不代替整机验收。

## 在仓库根运行

使用现有 `.venv`。如根环境没有numpy/Cryptodome，可显式使用已有桌面捆绑目录；不要安装系统依赖或启动桌面客户端。

```sh
mkdir -p .local/fixed-custom-filters
PYTHONPATH=a7r5-desktop/prepared/engine/site:a7r5-firmware-features/custom-filters \
  ./.venv/bin/python -B -m a7filters.baseline \
  /Users/wenruli/Desktop/索尼/BODYDATA.DAT \
  --investigate --report .local/fixed-custom-filters/new-baseline-audit.json

./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests
```

回执必须是新路径，已存在则拒绝。无 `apply`、`pack`、设备/SSH、私钥参数或放宽前像选项。

界面联验先构建独立测试ELF，使用仓库已有LLVM链接器，不安装依赖；测试链接地址只存在于模拟器，不能用于机身部署：

```sh
clang --target=aarch64-none-elf -std=c11 -ffreestanding -fno-builtin -Wall -Wextra -Werror -O2 \
  -c a7r5-firmware-features/custom-filters/native/af_ui.c \
  -o .local/fixed-custom-filters/af_ui-aarch64-11.o
clang --target=aarch64-none-elf -std=c11 -ffreestanding -fno-builtin -Wall -Wextra -Werror -O2 \
  -c a7r5-firmware-features/custom-filters/native/af_slots.c \
  -o .local/fixed-custom-filters/af_slots-aarch64-11.o
/opt/homebrew/opt/lld/bin/ld.lld -m aarch64elf -Ttext=0x92000000 --entry=af_ui_step --build-id=none \
  .local/fixed-custom-filters/af_ui-aarch64-11.o \
  .local/fixed-custom-filters/af_slots-aarch64-11.o \
  -o .local/fixed-custom-filters/ui-adapter-11.elf
PYTHONPATH=a7r5-desktop/prepared/engine/site:a7r5-firmware-features/custom-filters \
  ./.venv/bin/python -B -m a7filters.baseline \
  /Users/wenruli/Desktop/索尼/BODYDATA.DAT \
  --investigate-ui --ui-adapter .local/fixed-custom-filters/ui-adapter-11.elf \
  --report .local/fixed-custom-filters/new-ui-audit.json
```

实际AP分支联验再构建研究模块（重跑请换新后缀保留旧回执，不修改QEMU清单）：

```sh
clang --target=aarch64-none-elf -std=c11 -ffreestanding -fno-builtin -Wall -Wextra -Werror -O2 \
  -c a7r5-firmware-features/custom-filters/native/af_ap_ui.c \
  -o .local/fixed-custom-filters/af_ap_ui-aarch64-11.o
clang --target=aarch64-none-elf -c a7r5-firmware-features/custom-filters/native/af_ap_ui.S \
  -o .local/fixed-custom-filters/af_ap_ui-trampolines-11.o
/opt/homebrew/opt/lld/bin/ld.lld -m aarch64elf \
  -T a7r5-firmware-features/custom-filters/native/af_ap_ui.ld --build-id=none \
  .local/fixed-custom-filters/af_ui-aarch64-11.o \
  .local/fixed-custom-filters/af_slots-aarch64-11.o \
  .local/fixed-custom-filters/af_ap_ui-aarch64-11.o \
  .local/fixed-custom-filters/af_ap_ui-trampolines-11.o \
  -o .local/fixed-custom-filters/ap-ui-hooks-11.elf
PYTHONPATH=a7r5-desktop/prepared/engine/site:a7r5-firmware-features/custom-filters \
  ./.venv/bin/python -B -m a7filters.baseline \
  /Users/wenruli/Desktop/索尼/BODYDATA.DAT --investigate-ui \
  --ui-adapter .local/fixed-custom-filters/ui-adapter-11.elf \
  --ap-ui-module .local/fixed-custom-filters/ap-ui-hooks-11.elf \
  --report .local/fixed-custom-filters/new-ap-ui-audit.json
```

保护汇编另作独立测试产物，不能用于机身；运行字节与此产物由回归核对：

```sh
clang --target=aarch64-none-elf -c a7r5-firmware-features/custom-filters/native/af_resource_guard.S \
  -o .local/fixed-custom-filters/af_resource_guard-aarch64-11.o
/opt/homebrew/opt/lld/bin/ld.lld -m aarch64elf -Ttext=0x300000 --entry=af_resource_map_guard \
  --defsym=af_resource_map_failed=0x11846c --defsym=af_resource_map_ready=0x118484 --build-id=none \
  .local/fixed-custom-filters/af_resource_guard-aarch64-11.o \
  -o .local/fixed-custom-filters/resource-guard-11.elf
```

```sh
clang --target=aarch64-none-elf -std=c11 -ffreestanding -Wall -Wextra -Werror -O2 \
  -c a7r5-firmware-features/custom-filters/native/af_slots.c \
  -o .local/fixed-custom-filters/af_slots-aarch64.o
clang --target=armv7a-none-eabi -mthumb -std=c11 -ffreestanding -Wall -Wextra -Werror -O2 \
  -c a7r5-firmware-features/custom-filters/native/af_slots.c \
  -o .local/fixed-custom-filters/af_slots-thumb.o
clang --target=aarch64-none-elf -std=c11 -ffreestanding -Wall -Wextra -Werror -O2 \
  -c a7r5-firmware-features/custom-filters/native/af_cube.c \
  -o .local/fixed-custom-filters/af_cube-aarch64.o
clang --target=aarch64-none-elf -std=c11 -ffreestanding -Wall -Wextra -Werror -O2 \
  -c a7r5-firmware-features/custom-filters/native/af_record.c \
  -o .local/fixed-custom-filters/af_record-aarch64-03.o
clang --target=armv7a-none-eabi -mthumb -std=c11 -ffreestanding -Wall -Wextra -Werror -O2 \
  -c a7r5-firmware-features/custom-filters/native/af_record.c \
  -o .local/fixed-custom-filters/af_record-thumb-03.o

clang -std=c11 -Wall -Wextra -Werror -O1 -g -fsanitize=address,undefined \
  -fno-omit-frame-pointer \
  a7r5-firmware-features/custom-filters/native/af_slots.c \
  a7r5-firmware-features/custom-filters/native/af_cube.c \
  a7r5-firmware-features/custom-filters/native/af_record.c \
  a7r5-firmware-features/custom-filters/native/af_ui.c \
  a7r5-firmware-features/custom-filters/native/af_sha256.c \
  a7r5-firmware-features/custom-filters/native/af_document.c \
  a7r5-firmware-features/custom-filters/native/af_store.c \
  a7r5-firmware-features/custom-filters/native/af_persist.c \
  a7r5-firmware-features/custom-filters/native/af_versions.c \
  a7r5-firmware-features/custom-filters/native/af_cp406.c \
  a7r5-firmware-features/custom-filters/tests/native_pipeline.c \
  a7r5-firmware-features/custom-filters/tests/native_sanitizer.c \
  -o .local/fixed-custom-filters/native-sanitizer-04
.local/fixed-custom-filters/native-sanitizer-04
```

原记录/解析核心的交叉编译仅证明可编译；新增界面适配器另已链接成测试ELF并由Unicorn执行。两者均未链接或安装进实际AP/CP。主机库测试、ASan/UBSan、原厂窗口与目标适配器的证据范围分别记录。

## 后续入口

规格与状态见 `../specs/001-fixed-custom-filters/`。T03e/T04b2c/T04b2d完成限定离线范围，T03/T04/T07整体未完成；后续补齐必要消费者及EVF/JPG版本路由、最后图像帧、发送失败缓冲所有权和安全重建，再接实际机内存储、LUT拟合与菜单。完整线程和系统服务验收单列。命令、产物指纹和入口见[第十七批交付](../specs/001-fixed-custom-filters/continuation-17.md)。没有真实路径和时序证据前，不能把普通目录或内存后端当作已安装的相机滤镜功能。
