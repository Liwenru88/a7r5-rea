# 本批验证结果

> 后续按键扩展已单独更新默认模拟观察库与 Qt 客户端，最新运行输入以 `runtime/manifest.json` 为准；下文是本媒体研究批次的快照。媒体候选未并入默认包，挂载/照片回放结论仍未通过。当前客户端验收见 `../002-camera-function-expansion/button-expansion.md`。

本轮已修复合并后的开发环境入口，并用原厂 SDK 完成 14 组 Dataflow 双端连接。**应用媒体挂载、照片显示及照片切换仍未完成。** 深入候选已进入通知模式开启分支，但尚未实现参数通知，按明确拒绝停止。详细链路见[连接分析](connection-handshake-analysis.md)与[通知契约](notification-mode-analysis.md)。

## 本轮当前证据

| 验证对象 | 实际结果与现场 |
| --- | --- |
| 合并路径 | 29 个开发工具入口、5 个激活脚本修复；原入口及摘要保存于 `logs/relocation-222rzy8t/receipt.json` |
| 原厂双端连接 | 原始 SDK 的 14 组 `RequestConnect → Connect → ConnectComp`，状态 `2 → 0 → 0`；独立核对为 `logs/virtual-media/connect-final-handshake-verification.json` |
| 可用研究候选 | `build/media-yphpmwby`，现场 `runs/native-media-xpw__xpe/`；无卡返回、两轮 MENU 开关及 QMP 退出通过，照片字段明确为 false |
| 研究画面 | 上述现场 19 个完整容器校验、全部 PNG 像素独立一致，收据 `connect-final-frame-verification.json` |
| 深入候选停止 | `build/media-ibpllssv`，现场 `runs/native-media-cjfxd8eq/`；`0x3012` 已推进，`0x4073` 开启请求被模型拒绝，原厂报错；未冒充成功 |
| 原厂 Fsys | 深入候选的独立 Fsys 现场 `runs/native-media-mmv0lr3j/`：4096 字节写入、重挂读取、两张 JPEG、完整 4 MiB 文件镜像独立解析与 `fsck_msdos -n` 均通过，QMP 退出 0 |
| 真实 Qt 源码入口 | `logs/virtual-media/relocated-qt-acceptance.json`：16 次按钮操作（含帮助往返、4 轮 MENU、方向导航）、17 帧对照、5 秒空闲稳定与 QMP 正常退出 |
| 定向回归 | `connect-reviewed-python-regression.json`：11 个测试文件、42 项通过；C 模型 ASan/UBSan 回归见 `aux-3012-green.log`，含断开/重连、畸形消息、所有权和传输失败停止 |
| 固定输入与归档 | `connect-delivery-input-verification.json`：默认 5 项输入、包内 5 项输入和 4 个动态库核对通过；候选原 1226 项内容与元数据完全相同，仅既定 5 项模拟文件新增 |

这里的 Qt 验收使用保留的默认客体，并未把媒体研究候选装进交付应用。研究候选的 QMP 退出成功，也不等同于完成原厂关机或设备恢复流程。原厂 SDK 原生断开/重连、应用挂载和图形照片回放仍待独立验证。

Fsys 本轮第一次启动曾被占用锁拒绝，未进入客体。保留失败收据，没有删除或绕过锁；确认无运行实例后，新会话通过。最后回归曾因测试夹具没有包含新增的协议拒绝保留记录而失败，修正期望后全批通过，失败日志原样保留。

当模型明确拒绝协议、发生内部传输失败或固件异常时，宿主现在先核对完整控制台，再停止后续客体请求并结束 QEMU；即使表面先报图像解码错误也不会为了诊断恢复客体。迟到释放回执只通过有界读取原日志补齐，不重发按键。对应失败路径及保存现场重放均已验证。

## 前批历史记录

以下保留前批文件链与旧等待点；其中“当前连接缺口”和零状态锁回调结论已由本轮结果推进或更正，不作为当前验收。

## 已验证的文件链

- 基线为 `runtime/manifest.json` 的固定客体，仍是 `menu-daf0f137f7a3230d.cpio`，未切换默认清单。
- 独立候选保留原来的 1226 个条目内容和元数据，仅增加模拟配置库、Fsys 测试、4 MiB FAT16、寄存器与内存只读诊断程序。每次构建与启动均核对基线、候选摘要和归档条目。
- 原厂 `libInfraFsys.so`、`libInfraMediaCommon.so`、原厂 DMM/stream/OSAL 完成创建目录、写入 4096 字节、刷新、关闭、卸载；第二进程重新挂载读取并核对内容。
- 第三进程通过原厂 Fsys 读出两张 1280×960 测试 JPEG，长度分别为 60113、60108 字节；逐字节 FNV-1a 与主机生成源一致。JPEG 写有虚拟测试文字与 `A7R5 virtual input` 元数据，未使用用户照片。
- QMP 导出完整 4 MiB 普通文件镜像，主客体摘要一致；独立 FAT 解析核对双 FAT、簇链、目录、文件集合和内容，`fsck_msdos -n` 通过。无物理介质、无主机目录共享。
- 首次挂载失败 `0x80000000` 在补齐原厂 DMM/stream 依赖后消失；不能把它归因于 FAT 已损坏。更早的后台 shell `&;` 封装错误也保留为失败证据。

第一组照片读取证据：`runs/native-media-i5otwvtw/media-result.json`、`console.log`、`fsck.txt`。本批在最终候选上重新完成文件级读写、两次挂载、两张 JPEG 读取和独立 FAT 校验，证据为 `runs/native-media-o8ywcjys/media-result.json`、`fsck.txt`。当前摘要见 `logs/virtual-media/summary.json`。

## 媒体服务：已验证部分与缺口

静态确认 A7R5 原厂参数表 `0x6c638` 的 `0x69=EXISTMEDIADRIVER`、`0xf9=DBG_DRV_DUMMY_OMIT_WRITE`。配置库在实际写参数前再次调用原厂按名称查 ID 接口校验；保留真实写入，不开启省略写入模式。表证据见 `logs/virtual-media/a7r5-parameter-table.json`。

原厂媒体检测查询 `0x80d9016e` 返回队列未启用，导致没有后续 MediaRM 请求。新增受显式研究开关控制的 MediaRM 模型，使用原厂 OSAL 分配、发送和释放消息，限定支持配置查询 9、通知注册 3；未知请求拒绝。对分配/发送失败、消息所有权、畸形请求均有宿主 C 测试。该模型是模拟实现，不是原厂 CP MediaRM 在运行。

从原厂检测对象实测，当前有效媒体为 `0x1010 → /nondev/rm2`、`0x1000 → /nondev/rm3`。修正三端口配置掩码后，7 字节虚拟状态通知被原厂回调和 `ParseInternalMessage(0x80000005)` 实际解析，`0x1010` 的内部状态从 3 变为 1。原厂应用尚未观察到 `StartInOut` 或下游插拔通知，回放仍是“No memory card inserted / Slot 1”。这里没有证明实体槽位映射，也没有证明热插拔闭环。

候选证据：`runs/native-media-8p5a0o3z/`、`runs/native-media-y1dqbobh/`。首版 rm1 掩码错误的实验单独保留，不能列为成功。

## 前批等待点与本批推进

限定线程取样显示，公共序列队列曾停在：

`sequence_set_touch_panel → AppFw+0x350190c → +0x3522a2c → +0x352135c → osal_rcv_msg_tmo`

原厂请求为 `{frame=0x200d, property=0x146, bytes=10, flags=0x8001}`，原厂消费者读取 12 字节响应的 `+8` 状态。受限候选只为这个虚拟配置建模，严格核对头、长度及 0/1 参数，记录本次虚拟触摸启用状态，不提供实体触摸输入。`MEDIA_TOUCH_MODEL` 收据和后续调用栈证明已越过此等待点。

随后公共队列停在：

`sequence_set_release_lock → AppFw+0x350cffc → +0x355c74c → +0x355c510 → +0x355882c → shared-future wait`

调用向成像端点 `0x90040193` 发送 `0x403d` 命令，等待原厂成像回调。对应源文件字符串为 `infra_wrapper_imaging_ipsx_gl_branch.cpp`。前批尚未实现该回应；本批已按 AP 接收器契约实现受限虚拟锁模型，原厂接收与后续执行均已留证。完整成像生命周期仍未实现，不能据此宣称媒体可用，也不构成相互等待或死锁证明。

证据：`runs/native-media-f1ne8wn2/media-regs-308.log`（修复前）、`runs/native-media-i3ml8o1f/media-regs-307.log`（修复后）、各自 `media-app-tasks.log` 和 `media-app-dispatch.log`。辅助程序只读客体内存；寄存器取样短暂暂停后分离，栈取样不等同完整因果证明。

本批回复为原厂 AP 支持的 12 字节 `0x11` 头，命令位于 `+4`、状态位于 `+8`；消息来源为 `0x90040193`，经 `0x80020002` 原厂线程接收。原始请求、本地状态、回调收据与 SDK 查询详见 `logs/virtual-media/release-lock-contract.json`、`dataflow-pin-contract.json`。

## 前批连接缺口（本轮已推进）

两个固定 pin 的自身身份和初始状态由原厂 SDK 查询、封装、发送，AP 身份断言保持启用。随后原厂发送 `0x1000/0x0001`、40 字节内部载荷、64 字节传输消息，请求将 `0x90050004 / 0,2,1` 连接到 `0x9284074a / 0,1,1`。紧随其后的内核记录为 `No snd_msg registered. Skip snd to 0x4`。本批没有给这条连接请求回成功；持续状态和连接完成通知仍需实现。

最终应用现场：`runs/native-media-m7qrlo1o/`。`media-playback-check.json` 明确标记 `no-card-only`、照片回放及切换为 false；无卡返回和两轮 MENU 开关通过。`logs/virtual-media/release-frame-verification.json` 独立核对 19 个原始容器和 PNG 全部像素一致。CLI 与 QMP 均正常结束。此为研究入口验收，未进行新版 Qt 应用交付验收。

## 尚未验收

1. 应用层媒体状态订阅与插入/移除往返。
2. 原厂 DCIM 索引、JPEG 解码、照片上一张/下一张/退出。
3. 虚拟帧经原厂预览消费者读取与显示。
4. 原厂拍照成像、编码、写图、录像与音频。

默认 Qt 应用、原厂镜像、相机、SD 卡均未改动。当前研究候选不加入交付客户端，也不将文件级 JPEG 读取算作图形回放。
