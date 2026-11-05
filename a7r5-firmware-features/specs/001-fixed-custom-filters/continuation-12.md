# 第十二批：完整保存事务与目标架构闭环

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-26`
- Status: `OFFLINE_PERSISTENCE_AND_VERSION_CORE_VERIFIED_NOT_INSTALLABLE`

## 本轮交付

本轮把原先不透明的记录外壳推进到“八项调参→完整预设保存→回读→新目录恢复”，并完成另存、清空和有界版本引用核心。完成的是T04b2a、T05a、T06c、T07a的限定离线范围；未完成整套机身功能。输入仍为指定修改版4.06，未修改DAT、原厂库、冻结材料、QEMU清单或相机。

| 代码 | 已实现行为 | 实际证据 |
|---|---|---|
| `native/af_document.*`, `af_sha256.*` | 完整基底、初始/保存八项值、UTF-8名称、完整成像字节与SHA、转换版本及模型误差元数据；未来格式拒绝；调参后报告不再适用 | 独立Python字节/摘要对照、最大256KiB成像载荷及损坏拒绝 |
| `native/af_store.*`, `af_posix.*` | 双副本语义恢复；暂存、同步关闭、发布、目录同步、回读；发布后不确定状态冻结；坏槽不初始化 | 真实临时普通目录，短写/EINTR、ENOSPC、fsync、close、发布、回读及未来格式/冲突注入 |
| `native/af_persist.*`, `af_slots.*` | 保存/重载、另存、显式替换、清空墓碑；保存快照不吞后续调参；恢复保留创建值 | 同一个C UI目录与真实普通目录联验，重建目录后恢复 |
| `native/af_versions.*` | 三个不可变银行、64独立引用；失败保持旧版，在用不覆写，过期确认和重复释放拒绝 | 真实C状态核心；确认和引用来自显式测试驱动 |
| `tests/native_pipeline.c` | 20槽八项UI路由、保存/重启模拟、失败、另存、清空及版本引用完整执行 | AArch64和ARMv7分别执行实际机器码，最终序列化摘要与独立构造相同 |

保存成功和成像生效仍是两个独立结果。这里没有真实CP生效确认；“重启”是重建原生目录并从本地文件/内存后端恢复，不是机身重启。另存保留源创建值作为重置/误差基准，源工作值成为目标保存值。

两种目标架构的20槽闭环使用纯参数文档及内存文件后端；完整LUT字节容器另由主机C/普通目录验证。没有把存取LUT字节当成机内转换或目标ISP消费，也没有测出实际机身峰值内存。

## 本轮验证

- `pytest-12-final.json`：134项通过，4.04秒；编译并执行真实C，含28项完整载荷/事务/编辑联验、2组版本核心、2种目标架构及9项CP扫描器契约测试。
- `native-sanitizer-12-final.json`：ASan+UBSan下2万次解析/目录/记录/UI/完整文档探测，以及20槽保存/版本闭环通过。
- `ui-access-406-12-verified.json`：重新验签、736841帧、147归档成员、71目标及同包辅助库通过；24处AP分支、1218刷新查询、864快照消费及原资源加载保持。
- 新AP研究ELF为82904字节，SHA-256 `d9ff98a27eb6e7dc74026aea28020937bbf320f7f7e5ef0eb371d7af819167d6`。原AP挂钩C/S/链接脚本未变，槽位源新增恢复函数后重新链接并联验；此ELF只供离线研究，不可安装。
- `verification-continuation-12.json`记录最终源码、文档、命令回执、产物和输入指纹。不读私钥、不连接相机、USB、SSH或真实SD。

可复用命令（仓库根目录；回执使用新路径）：

```sh
./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short

PYTHONPATH=a7r5-desktop/prepared/engine/site:a7r5-firmware-features/custom-filters \
  ./.venv/bin/python -B -m a7filters.baseline \
  /Users/wenruli/Desktop/索尼/BODYDATA.DAT --investigate-ui \
  --ui-adapter .local/fixed-custom-filters/build-12/ui-adapter.elf \
  --ap-ui-module .local/fixed-custom-filters/build-12/ap-ui-hooks.elf \
  --report .local/fixed-custom-filters/next-ui-audit.json
```

当前编译参数和实际输出见[构建命令](../../../.local/fixed-custom-filters/build-12/commands.json)，最终消毒器使用同一命令换新输出路径，见[消毒器回执](../../../.local/fixed-custom-filters/native-sanitizer-12-final.json)。pytest保留的独立ELF/主机库在`.local/fixed-custom-filters/pytest-12-final/`。运行测试本身不会选择任何设备或现有用户目录。

## CP补证及下一处具体入口

`a7filters/cp_updates.py`对已锁定CP扫描直接调用、PC相对加载和经独立反汇编核对的MOVW/MOVT配对。发现12个直接调用候选，以及466个状态/上下文立即数候选：通知状态345、master 78、参数快照2、原上下文9、已安装上下文3、另一路上下文候选29。按类最多32个详细窗口，保留107份；完整数量仍保留。半字线性扫描含数据区域，所有结果都是静态候选，不能当成执行到达或全部写入者。

原`0x4baa9e`仍将master复制到`0x1653c68`。该全局快照另一个完整地址候选`0xafdbb2`主要涉及后续字段清零，不能据此认作八项实时更新。原上下文`0x192b070`在`0x4babaa`构造后，分别送入`0x887162`、`0x964af0`、`0x88c3ca`、`0x7195d6`、`0x9071cc`、`0xabbc0e`、`0x89b6ca`、`0xb08aa8`等路径；这些分派窗口带条件标记和回调结构，须继续确认完成语义，不能只替换一个全局指针。

额外构造调用`0x4bbb9a`、`0x4bc124`将结果放到`0x165d820`，与原`0x192b070`不是同一地址；选择辅助窗口`0xafc7d4`在`0x165d758`和`0x165d820`之间选择。后续需要沿该上下文的拍摄操作和完成/释放回调追踪，判断是否能为新版本银行提供真实帧寿命保证。当前未证明实时取景/JPG，T03/T07不勾选。

首次真实扫描超过固定详细窗口上限而中止，保留[失败记录](../../../.local/fixed-custom-filters/cp-update-budget-12-red.json)；随后改为精确计数和按类截取，并用300份合成候选验证有界行为，最终真实审计通过。未通过调整CP摘要门槛或扩大不透明运行内存绕过问题。

## 全量交付还缺什么

| 门槛 | 已有基础 | 仍需获得的证据/实现 |
|---|---|---|
| T01/T06完整32槽原厂界面 | 注册、名称、组件、输入、刷新窗口已有 | 匹配4.06完整AP/Qt客体、实际装载/权限/线程、真实按键/轮盘、字体/像素和页面寿命；现QEMU清单仍4.00且缺CPIO/DTB |
| T02/T04b/T05机内持久化 | 完整载荷及普通目录事务已实现 | 合法可写区、容量/保留内容、启动读取、机身文件系统同步与恢复；不能自行选择`nflasha30`或原厂Backup ID |
| T03/T04b/T07照片成像 | 参数来源链、静态分派候选、版本核心已有 | 实时更新、所有消费者、实际IPC/会话握手、帧/JPG完成信号和银行释放；新核心尚未接入这些入口 |
| T08机内LUT拟合 | 有界CUBE解析/求值、完整成像载荷容器已有 | 每个基底的真实ISP模型与域、色表/曲线/矩阵量化、误差计算、性能及输出验证；现六款联合包装器限ST照片profile0，不能直接套给FL2/FL3 |
| T09菜单闭环 | 原生替换/保存/另存/清空可调用 | SD浏览/装入、候选预览/取消、实际菜单动作、导出、存储/成像回执呈现和动态名称；不能把测试schema当可用滤镜 |
| T10/T11兼容与候选 | 输入及继承部分保持、离线核心回归通过 | 真实原六槽迁移、全链回归、增量白名单/反向还原和可安装候选门禁；T12真机验收另行授权 |

总体仍为`NOT_VERIFIED`。本轮没有生成可安装固件，也没有把普通目录结果或原生版本确认当作相机验收。
