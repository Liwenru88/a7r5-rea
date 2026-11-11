# 二十四槽创意外观研究候选

**4.18 研究升级包已完成离线校验。** 原厂组内置六款、独立二十四槽和十档照片纵横比已合入同一包，并修复从新增比例直接返回 3:2 时的状态残留。101 项运行时回归、29 项封装测试及 736841 帧校验通过，机身验收待完成。[4.18 更新包](releases/4.18/BODYDATA.DAT) · [闭环与稳定性审计](4.18闭环与稳定性审计.md) · [封装回执](releases/4.18/verification.json)

**2026-11-05 八项参数改为相对偏移，已封装 4.17。** 自定义页八项默认和重置均显示 0，发送时按“本次原生参数＋配方偏移”计算并限制在原厂合法范围，归零保留上游原消息。微调仍按配方身份保存，兼容读取旧绝对值记录。原厂外观保持原有参数逻辑。规则和离线证据见[相对偏移调参说明](相对偏移调参说明.md)；参数来源见[上游核对](上游八项参数核对.md)。

**4.17 相对偏移更新包历史。** 纳入八项偏移及原有左键切组、两组成功选择记忆和首款回退。复用同源码及四组件身份的 31 项相关 CPU 回归和上游 48 次 E4／432 条消息比对；本次执行 44 项封装测试、736841 帧校验、独立解包与四组件回读、OpenSSL 验签，均通过。DAT SHA-256 为 `49ec00bd5c179fc0f784bf8c64e5025877fde5b50c3ce48fe05dd3d51a24dcda`。本轮没有运行 QEMU 或连接相机，同版更新准入和实机效果待核验。[交付说明](releases/4.17/README.md) · [离线校验](releases/4.17/verification.json) · [4.17 候选身份](current-candidate.json)

- [实施与复现手册](实施与复现手册.md)涵盖功能、源码落点、原厂基线、两次独立构建、验证和复现封包。
- [目录归并清单](目录归并清单.md)列出两套迁入依赖、历史归档及旧路径对应关系。
- [A7M4 功能移植记录](A7M4功能移植记录.md)记录可选的第三方镜头 AF 补丁，以及真实照片裁切在 A7R5 上已核对的入口。

## 原厂组 C1–C6 六款固定滤镜

本次离线组件将 4.06 的六款固定滤镜接回原厂创意外观组的 C1–C6，保留原厂槽位和调参流程。左键切到自定义组后，仍使用 `R5NATIVE.BIN` 的独立 24 槽。六款无需 SD 卡配方。

| 原厂槽位 | 名称 | AP→CP |
| --- | --- | --- |
| C1 | Classic Neg. | 249 |
| C2 | Classic Chrome | 250 |
| C3 | Nostalgic Neg. | 251 |
| C4 | Astia | 252 |
| C5 | GR Positive Film | 253 |
| C6 | GR Negative Film | 254 |

构建逐字节核对历史六款的 1215 字节原生色表和 108 字节联合增量。CP 继续在原厂 ST 照片处理的输出上叠加 Gamma、矩阵和两套色度增量。Gamma 私有行 75–86 与 SD 库的 51–74 分开，原厂与 SD 色表分支重放原指令。C1–C6 固定对应上述配方，已有槽位微调仍由原厂流程读取。完整联合参数的适用范围沿用旧版照片路径。

先按[十档纵横比复现步骤](../photo-aspect-ratios/src/README.md#离线复现)构建四项输入。AP 使用当前 4.17 构建前像 `eaf0b742…` 的比例组件，CP 支持该整合基底及镜头 AF 补丁的比例组件。从仓库根目录构建：

```sh
aspect_out=/path/to/aspect-output
combined_out=/path/to/new-output
.venv/bin/python -B a7r5-firmware-features/look-factory-six/src/build_legacy_six.py \
  --ap "$aspect_out/ap/appFw.aspect.NONINSTALLABLE.so" \
  --cp "$aspect_out/cp/cpapp-b.aspect.NONINSTALLABLE.bin" \
  --avcam "$aspect_out/avcam/AV-CAM.aspect.NONINSTALLABLE.BIN" \
  --resources "$aspect_out/resources" \
  --output "$combined_out"
```

输出包括 AP、CP、AVCAM、两套图标、68 份横竖文字资源及带摘要的 `build.json`。测试以 `A7R5_LEGACY_SIX_BUILD` 指向该目录，运行 `tests/test_legacy_six.py`。换机器时，`A7R5_LEGACY_SIX_RUNTIME` 指向 4.17 的原 AP 构建目录，`A7R5_LEGACY_SIX_STOCK_CP` 指向原厂 CP 文件，`A7R5_NATIVE24_BUILD` 指向现有测试夹具绑定的二十四槽构建。

QEMU 已逐项核对六款名称和左键双向切组。客体使用智能自动模式，中键确认受原厂拍摄模式限制。带镜头 AF 补丁的组合通过 27 项回放与资源测试，默认 CP 组合另通过 8 项六款专项测试。色表上传缓冲、曲线、矩阵和色度以 CPU 指令回放为证据，取景成像、成片与视频仍待机身验证。

## 历史版本与阶段记录

**此前同名 4.17 历史。** 原左键切组包 AP 为 `27bc6eb0…`，DAT 为 `7e686382…`，当时的 28 项 CPU、39 组 QEMU 和 51 项封装记录不作为当前相对偏移 AP 的验收证据。当前包版本号仍为 4.17，按完整 DAT 摘要区分，旧候选记录保存在 `current-candidate.json` 的 `previous_candidate` 中。

**4.16 研究更新包历史。** 纳入 019 的 E4 八项逐条发送完成判定，以及 020 的调参和切换状态刷新修复。用户随后报告实机可应用自定义滤镜，同时发现首次按下进入自定义列表时首款未预览。见[4.16 更新包](releases/4.16/BODYDATA.DAT)和[离线校验](releases/4.16/verification.json)。

**019 QEMU补验：部分通过，未封新包。** 已补接调参页独立原生事件入口；新AP重新通过95项相关CPU回归、独立重建及107次Qt短窗口导航／原帧检查，列表与调参页均观察到自然心跳。长空闲曾在原生关机流程崩溃，调参画面还存在数值滞后疑点；两项未解决，原E4与成像也未验收。当前仍NOT_VERIFIED，未连接相机，4.15未包含新修复。见[本轮分析](../specs/019-native-preview-completion/QEMU补验与调参页接入修复.md)与[验证／截图](../specs/019-native-preview-completion/QEMU补验验证记录.md)。以下均为首轮及原包历史记录。

**019首轮历史（已由补验修订）：** 用户确认4.15切Tab不再重启，但上下浏览时等待／未完成且状态滞后，尚未测试中键确认。已修复原E4逐项发送完成判定、D9／DA原生空闲事件推进与重绘，以及迟到回执跨事务污染；95项完整相关CPU回归、8项定向和独立重建通过，8项包含在95项内。仅AP变化，CP和图标保持；原4.15的117项内容校验一致。见[分析](../specs/019-native-preview-completion/离线分析与修复.md)、[验证](../specs/019-native-preview-completion/verification.md)和[审查组件](verification/2026-11-04-preview-completion-01/README.md)。新候选尚未重跑QEMU菜单或连接相机，无自然空闲刷新、实际成像或机身修复验收；整体仍NOT_VERIFIED。以下为原包与历史验证记录。

**4.15 分块修复包历史。** 51 项封装回归、全部 736841 帧、独立回读及 OpenSSL 验签通过。用户随后报告切入自定义 Tab 可浏览，预览显示「切换未完成」，中键确认无反应。见[018 验证](../specs/018-native24-update415/verification.md)和[实机反馈](../specs/019-native-preview-completion/离线分析与修复.md)。

**2026-11-04故障补记：** 用户确认4.14仍在切自定义Tab时重启，暂停推荐旧包。新离线修复将新增图标由单块5600字节改为原厂的4096＋1504独立块，并给QEMU补齐分块门禁；23项定向回归、2项身份测试、103次Qt／103原帧及独立重建通过。AP／CP保持4.14字节身份，未连接相机，未生成新DAT。见[017分析](../specs/017-icon-page-boundary/离线分析与修复.md)、[新审查组件](verification/2026-11-04-icon-pages-01/README.md)和[故障追查](../specs/015-tabs-device-reboot/故障分析与修复.md)。硬件与整机验收仍未完成。以下保留封包当时的历史记录。

**4.14封包历史：** 当时新增图标改用F0压缩并纳入同步导航保护，原82项相关回归、37项封装回归、三场景257帧QEMU和DAT离线结果见[016验证](../specs/016-native24-update414/verification.md)。后来用户确认该版仍重启。

**原4.13故障与SSH预检：** F01图标长0F流导致实机LDEC失败；持久替换因/usr空间不足在写入前停止。旧4.13包及015审查材料保持，详见[故障分析](../specs/015-tabs-device-reboot/故障分析与修复.md)与[预检记录](../specs/015-tabs-device-reboot/实机替换前检查.md)。下文013／014为原交付阶段的历史说明。

原013分组Tab候选曾封装为[研究版4.13更新包](../specs/014-native24-update413/verification.md)：顶部区分原厂外观／自定义滤镜，首项按上聚焦Tab，左右切组，下或中键进入列表；切Tab不应用，列表中键确认、右键调参保持。80项相关CPU回归、2项QEMU固定身份、满库115次／空库39次实际Qt操作及154原帧核对通过，四组件独立重建一致。见[操作说明与截图](Tab分组交互说明.md)、[当前组件身份](current-candidate.json)、[013验证](../specs/013-creative-look-tabs/verification.md)及[原研究组件归档](verification/2026-11-03-tabs-01/README.md)。保持012的身份微调、原BIN和011后台保护。4.13另通过35项封装测试、736841帧、完整独立回读及OpenSSL验签，见[014验证](../specs/014-native24-update413/verification.md)。整体仍为NOT_VERIFIED，未连接相机；原E4／成像和长列表抓帧顶部文字偶有缺失的边界保留。

## 012八项调参候选历史说明

012完成附加滤镜复用原调参页，微调按色彩配方SHA256独立保存；同配方重导入、改名和换槽保留，新内容使用独立初始值，不修改原BIN。保留011的原厂界面、后台恢复、未知状态保护及最后目标合并。当时70项相关CPU回归、80次原厂参数委派、2项QEMU固定身份、106次实际Qt操作与106原帧核对通过，四组件独立重建一致。见[八项调参说明与截图](八项调参交付说明.md)、[012验证](../specs/012-native24-parameters/verification.md)及[原研究归档](verification/2026-11-03-parameters-01/README.md)。现有BIN没有八项默认标量，新身份读取ST默认字段，不继承ST工作值。历史资料保持。

## 011后台恢复候选历史说明

011完成原厂正常标题和参数显示、后台有限同步与回退、移除“选择ST恢复”，以及56项回归和107帧验证。见[当时交互说明](后台恢复交互优化说明.md)、[011验证](../specs/011-background-look-recovery/verification.md)和[原封存](verification/2026-11-03-background-01/README.md)，历史资料保持。

## 010稳定性候选历史说明

010稳定性候选当时完成回退协调、R5SEL6及恢复日志、短读／幂等导入、双卡优先、旧库回退、启动终态、原E4在途保护、RAM诊断和构建门禁的离线验证。46项相关回归、2项QEMU固定身份检查通过，96原帧与PNG一致，独立重建四组件相同。详见[稳定性优化交付说明](稳定性优化交付说明.md)、[当时组件身份](verification/2026-11-03-stability-01/results.json)及[研究组件包](verification/2026-11-03-stability-01.tar.gz)。历史证据保持；其ST恢复交互已由011替代。

## 009初始候选历史说明

以下保留初始24槽候选的当时结论与复现背景，当前运行时以文首013说明为准，4.13封装身份以014和交付回执为准。

已将24槽接入真实AP／CP、原创意外观、配置持久化和启动／恢复链路，保留冷启动导入、ST／FL2／FL3、本地四项和最后目标合并。**当前为离线研究候选，未生成升级包，不能作为机身可安装固件。** 原十二槽候选、上游和旧4.10／4.11包保持不变。

2026-11-03验证结果：18项目标机器码／图标解码测试通过；QEMU固定身份检查2项通过；实际Qt遍历24款及ST／FL2／FL3，96幅原帧与PNG逐像素一致，四轮菜单开关／ST重入和三侧退出正常。完整记录见[本次验证](verification/2026-11-03-01/README.md)，任务及边界见[009规格](../specs/009-native24-runtime/verification.md)。

当前AP SHA256为`c4efcaa0ac1578a719f11f36d6a316c63ff1d76aa8fb145c78895005b723cda1`，CP为`31f85fa3d3015d3d553abb6540a98ae67e280631c0bff73cd4eada7fe02db0b2`。菜单原十九项＋二十四项共43行；24位mask、线协议、名称／状态、48个图标及947000字节CP布局同步迁移，旧v4十二槽文件保持可读。

必须保留的限制：真实共享堆余量未测量；QEMU中本次滤镜应用仍因原E4初始化缺口失败回退，不能用等待／应用中画面当成功；CPU的E4外部执行和原厂UI为明确夹具，实际色彩、完整启动和机身验收未完成。因此整体仍为`NOT_VERIFIED`。

**新增13～24号仅用合成数据验证容量，不是新增十二款成品滤镜。** 原十二款BIN可供新运行时读取，未配置的槽不会变成新配方；测试BIN不能拿来安装或作为色彩成品交付。新候选格式5和R5SEL5由本候选识别，旧固件不支持13～24号，也不承诺无损降级。

构建及测试以[当前实施手册](实施与复现手册.md)为准。早期 [4.13 封包入口](release413/README.md)和 [Tab 实验](../../a7r5-qemu/experiments/native24-tabs-menu/README.md)对应旧交互，用于回溯。
