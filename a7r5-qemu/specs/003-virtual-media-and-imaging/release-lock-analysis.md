# 0x403d 完成回调与后续媒体前置分析

> 历史批次记录，以下候选、阻塞点和回复内容保留当时结果。后续已实现 14 组连接，并核对出本接口回复状态应为 `0xf000`；这里的零状态回复只证明 future 被兑现，不能证明原厂消费者判定成功。当前结论见 [连接握手分析](connection-handshake-analysis.md)与[验证记录](verification.md)。

## 结论与边界

`0x403d` 完成回调已在独立候选中打通，原厂公共序列已越过该等待。后续限定配置、两个 pin 的自身身份查询也已推进；当前停在未实现的 Dataflow 连接握手。应用回放仍显示无卡，不能验收照片显示或切换。

本批只修改模拟载荷、研究入口、测试与文档。默认 Qt 包和运行清单未切换；原始分区镜像、相机和 SD 卡未操作。候选保留原客体 1226 个条目的内容及元数据，只增加既定的五个模拟条目。

最终候选：`build/media-5ed77r5j/receipt.json`。应用现场：`runs/native-media-m7qrlo1o/`。独立 Fsys 回归：`runs/native-media-o8ywcjys/`。

## 锁回调证据链

1. 原厂 `sequence_set_release_lock` 经 `AppFw+0x355c510` 构造请求，`+0x355882c` 注册 future、发送并等待。
2. 实际目标 `0x90040193`、OSAL 来源 `0x80020002`，请求为 16 字节：`05003d40020000800080000001000000`。
3. 本次参数为掩码 `0x8000`、布尔值 1，即置位锁配置。不能将它称为已实际解除快门锁；清位只通过了模型测试。
4. 原厂 `IWrapperImaging` 接收循环 `+0x3554cf8` 校验来源；`+0x3554d90` 支持 `0x11` 头，从 `+4` 读取命令号并匹配等待项，经 `+0x35548b0` 兑现原厂 future。
5. 候选仅对已核对的来源、长度、头部、两种掩码和布尔值建模，回复 `110000003d40000000000000`。只有回复交付成功才提交虚拟锁状态并释放请求；失败保留调用者所有权。
6. 实际收据 `MEDIA_IMAGING_RECEIVED queue=0x80020002 source=0x90040193 bytes=12 callback=0x11 command=0x403d` 证明原厂线程收到了回调。随后原厂发送 `0x40a5` 并继续配置流程；该命令在原厂构造器中不要求回复。

证据：`logs/virtual-media/release-lock-contract.json`、`release-lock-static-evidence.txt`，最终现场 `media-imaging.log`。这里证明 AP 接收契约与模拟状态有效，未证明实体 CP 生产端或真实快门硬件行为。

## 后续配置为何没有一并跳过

锁回调后，原厂顺序执行面板、HDMI 和 ADF 配置。候选按原厂请求构造和接收代码逐项限定支持：

| 接口 | 支持范围 |
| --- | --- |
| BB `0x118/0x119` | 固定配置；`0x118` 输出选择仅 0/1/2，保留原厂完成事件 |
| HDMI `0x101` | 已观察到的关闭输出 / preset 6 |
| HDMI `0x10a` | 原厂定义枚举 0…3 |
| HDMI `0x117` | 两路相同配置，首枚举 0…4，帧率枚举 0…6 / 0x11 |
| BB `0x149/0x110` | 原厂构造器的 0/1/15 与 0/1 参数 |
| ADF `0x321/0x334/0x32b` | 本次固定路径、输入通道及零输出掩码配置 |

这些是虚拟配置状态，不能证明预览、真实 HDMI、成像或视频输出。没有启用旧通用就绪事件注入，也没有写 AP 的就绪字段。

## Dataflow 查询与当前缺口

原厂随后进入 `pin_manager.cpp → connect_infra_pin → get_infra_pin → DataflowInfraReceiver::ReceiveASync`。最初的查询有 24 字节传输封装和 24 字节内部消息，共 48 字节；内部为 `0x1000/0x0000`。

候选只为两个实际观察到的 pin 提供查询：

- `0x90050004 / Module 0 / Instance 2 / Pin 1`
- `0x9284074a / Module 0 / Instance 1 / Pin 1`

使用原厂 `DataflowInfraPin` 构造、`GetSelfPin`、`GetTargetPin`、`GetPinState`，以及原厂 `DataflowInfraMsg` / `DataflowInfraSender` 封装和发送。类大小从原厂代码核对为 0x40 / 0x198 / 8。查询结果为 SDK 初始状态 1、对端字段 `255,255,0,0`，没有宣称已建立连接。

两个布局必须分开：SDK `PIN_PROPERTY` 为 `Module,Instance,Pin,Node`；AP `ds_infra_pin` 为 `Node,Module,Instance,Pin`。32 字节查询完成载荷在 `+8/+12/+16` 放前三项、`+20` 放状态、`+24` 放 Node、`+28` 放结果。AP `+0x3542918..2940` 重排后，再由 `+0x3542b18` 检查自身身份一致。

首次候选错误地返回对端描述，原厂在 `infra_wrapper_dataflow.cpp:467` 断言。该失败保留在 `runs/native-media-7oh22uic/`。之后先加入按 AP 消费逻辑解码的回归断言，确认失败，再修正封装；同时用 SDK 发送代码核对 `PIN_PROPERTY` 的 Node 位于第四项，另作失败回归。没有绕过原厂身份断言。

最终原厂已通过两次查询，并发送下一条连接请求：

| 项目 | 实际值 |
| --- | --- |
| 内部消息 | `0x1000/0x0001`，40 字节 |
| 传输消息 | 64 字节 |
| 来源 pin | `0x90050004 / 0,2,1` |
| 目标 pin | `0x9284074a / 0,1,1` |
| 内核记录 | `No snd_msg registered. Skip snd to 0x4` |

此连接请求尚未被虚拟服务接收，未给它回成功。下一步需保留双端 pin 对象，以有界异步派发串接原厂 `RequestConnect/Connect/ConnectComp` 生命周期，核对断开及失败清理，再检查媒体初始化。当前每次查询创建初始对象的实现不具备持续连接状态，不能拿查询成功替代连接完成。

尚未取得应用层媒体订阅、挂载、扫描收据。未注册服务和单点等待并不构成相互等待或死锁证明。细节见 `logs/virtual-media/dataflow-pin-contract.json`、`dataflow-pin-static-evidence.txt`。

## 实际验证与未完成项

- 最终 AArch64 载荷已重建；候选摘要、设备树和全部原归档条目核对通过。
- 原厂首次设置通过真实输入事件完成；无卡回放返回拍摄信息页，两轮 MENU 开关通过。19 个客体原始快照及 PNG 经独立逐像素核对一致。证据：`media-playback-check.json`、`logs/virtual-media/release-frame-verification.json`。
- 最终 CLI 成功结束，QMP `quit`、进程退出码 0。未发生原厂异常监视器。此为研究入口验收，未发布新版 Qt 包。
- C 消息所有权、畸形包、SDK 分步失败、禁用路径测试通过；AddressSanitizer/UndefinedBehaviorSanitizer 通过。13 项 Python 定向测试通过，包含实际 macOS 沙箱边界与异常后停止发送的测试。
- 原厂 Fsys 独立回归重新完成读写、刷新、卸载、二次挂载、两张测试 JPEG 读取和独立 FAT 校验。仍属文件级验收。
- 照片显示与切换未执行：原厂回放目前仍无卡。原厂 JPEG 解码、相册索引、媒体热插拔、虚拟预览、拍照、录像均未完成。

研究入口曾出现初始化按键阻塞、诊断工具路径失效、增长日志读取超时和断言文本打断快照导出；失败现场保留。最终只收集有界传输记录与线程元数据，关闭 ptrace 取样。研究按键未结束或画面不符即停止后续按键，异常或串口超时后不再追加客体诊断请求。未放宽快照校验来接受受污染帧。
