# A7R5固件功能研究成果

**当前主线为 [4.17 整合版](native24-combined/README.md)。** 从原厂 4.00 重建组件、复现升级包、执行离线验证及定位功能源码，请从[实施与复现手册](native24-combined/实施与复现手册.md)开始。三个目录的依赖和归档范围见[目录归并清单](native24-combined/目录归并清单.md)。

[4.17 升级包](native24-combined/releases/4.17/BODYDATA.DAT) · [十二款正式配方](native24-combined/releases/4.17/R5NATIVE.BIN) · [发布校验](native24-combined/releases/4.17/verification.json)

## 历史版本与早期研究

**019 QEMU补验：部分通过，未封新包。** 已补接调参页独立原生事件入口；新AP重新通过95项相关CPU回归、独立重建及107次Qt短窗口导航／原帧检查，列表与调参页均观察到自然心跳。长空闲曾在原生关机流程崩溃，调参画面还存在数值滞后疑点；两项未解决，原E4与成像也未验收。当前仍NOT_VERIFIED，未连接相机，4.15未包含新修复。见[本轮分析](specs/019-native-preview-completion/QEMU补验与调参页接入修复.md)与[验证／截图](specs/019-native-preview-completion/QEMU补验验证记录.md)。以下均为首轮及原包历史记录。

**019首轮历史（已由补验修订）：** 用户确认4.15切Tab不再重启，但上下浏览时等待／未完成且状态滞后，尚未测试中键确认。已修复原E4逐项发送完成判定、D9／DA原生空闲事件推进与重绘，以及迟到回执跨事务污染；95项完整相关CPU回归、8项定向和独立重建通过，8项包含在95项内。仅AP变化，CP和图标保持；原4.15的117项内容校验一致。见[分析](specs/019-native-preview-completion/离线分析与修复.md)、[验证](specs/019-native-preview-completion/verification.md)和[审查组件](native24-combined/verification/2026-11-04-preview-completion-01/README.md)。新候选尚未重跑QEMU菜单或连接相机，无自然空闲刷新、实际成像或机身修复验收；整体仍NOT_VERIFIED。以下为原包与历史验证记录。

**4.15 分块修复历史。** 4096＋1504 字节分块和原封包的 51 项测试、736841 帧、独立回读及验签见 [018 验证](specs/018-native24-update415/verification.md)。

**2026-11-04更新：** 用户确认4.14仍在切自定义Tab时重启，旧包暂停推荐。已完成新增图标4KiB分块的离线修复及QEMU门禁补齐：23项定向回归、2项身份测试、103幅原帧与独立重建通过。仅两份图标资源改变，AP／CP保持；未连接相机、未生成新DAT，整机修复仍待验收。见[017分析与证据](specs/017-icon-page-boundary/离线分析与修复.md)和[新审查材料](native24-combined/verification/2026-11-04-icon-pages-01/README.md)。下文4.14为封包当时的历史记录。

**4.14 封包历史。** 新增图标 F0 编码、同步导航保护和当时的离线结果见 [016 验证](specs/016-native24-update414/verification.md)。用户后来确认切换自定义 Tab 仍会重启。

**4.13实机故障记录：** F01长0F图标流导致LDEC解压失败；SSH替换在空间检查阶段停止，原固件文件未替换。旧4.13包仍暂停推荐，见[分析与修复](specs/015-tabs-device-reboot/故障分析与修复.md)与[替换前检查](specs/015-tabs-device-reboot/实机替换前检查.md)。

**4.13 封包历史。** 24 槽分组、八项调参、后台恢复及旧版封包记录见 [014 验证](specs/014-native24-update413/verification.md)和[当时的操作截图](native24-combined/Tab分组交互说明.md)。

以下保留**研究版4.11历史记录**：远端固定4.36的十二滤镜／Fn／颜色参数路线，加本地FL2／FL3自包含修复、指定NTSC提示关闭、电子快门声音选择器、照片2.35:1标记菜单及中文字体修复。旧4.10保留。下面4.11记录不包含后续统一入口、24槽、八项调参与Tab修订。

4.11已重新封包，101项回归、研究签名及OpenSSL、全部736841帧、独立解包和文件系统检查通过。十二配置读取、持久化、CP封存及名称显示已有[QEMU截图与证据](native24-combined/dependencies/native12-combined/verification/2026-11-02-qemu-native12-loading/README.md)，包内AP／CP与该客体身份一致。本轮没有另跑4.11客体，也没有连接相机或探测设备。

**已知问题仍保留：** QEMU中原生E4刷新未完成，滤镜成功应用尚未验收；`Portra400`左列简称仍裁切，右栏全名可见。实际成像、出声、照片标记叠加、机身准入、启动与恢复也未实机验收。详见[交付说明](native24-combined/dependencies/native12-combined/releases/4.11/README.md)和[中文显示／加载复验](specs/003-native12-menu-loading-fix/verification.md)。

- [十二槽历史版本说明与复现](native24-combined/dependencies/native12-combined/README.md)
- [4.11升级包](native24-combined/dependencies/native12-combined/releases/4.11/BODYDATA.DAT)、[十二款滤镜](native24-combined/dependencies/native12-combined/releases/4.11/R5NATIVE.BIN)
- [归档说明](native24-combined/dependencies/native12-combined/releases/4.11/README.md)、[校验值](native24-combined/dependencies/native12-combined/releases/4.11/SHA256SUMS)、[封包回执](native24-combined/dependencies/native12-combined/releases/4.11/verification.json)
- [冻结4.10及历史验证](native24-combined/dependencies/native12-combined/releases/4.10/README.md)
- [整合需求、设计、任务和验证记录](specs/002-native12-combined-firmware/requirements.md)

| 目录／材料 | 用途与范围 |
|---|---|
| [native24-combined](native24-combined/README.md) | 4.17 主线，统一实施入口、运行时、验证、升级包 |
| [native12-combined](native24-combined/dependencies/native12-combined/README.md) | 4.17 使用的固定上游、基线构建和补丁依赖，另有 4.10／4.11 历史交付 |
| [24 槽格式依赖](native24-combined/dependencies/native24-format/README.md) | 4.17 使用的格式转换与测试夹具，另有独立容量原型 |
| [01 FL2／FL3](01_FL2和FL3启用实施细节.md)、[02 六款滤镜](02_六款自定义滤镜实施细节.md)、[03 NTSC](03_关闭NTSC提示实施细节.md)、[04 声音](04_电子快门声音启用实施细节.md) | 早期4.06固定配方及实施材料；其中六款滤镜属于历史方案，不是当前十二配置BIN |
| [照片标记研究](aspect-guide406/README.md)、[固件集成说明](aspect-guide406/integration.md) | 照片菜单与标记参数的原始研究，相关代码已按新布局合入当前整合版 |
| [custom-filters](custom-filters/README.md) | 独立32槽／机内CUBE研究路线，保留原状，不进入当前整合版 |
| `materials/` | 固定参数、来源、离线复现材料；保留原有各自校验范围 |

**照片标记 4.07 实验包（2026-10-26）。** 基于研究版 4.06，仅加入照片标记菜单的 AP 文件增量。历史 `BODYDATA.DAT` 大小为 754,525,608 字节，SHA-256 为 `6a64b584f5548af15abf4e253ed3758a61cdd88288e0c97687c5f0c5d0fb7f50`，当前工作区缺少该交付包。原厂菜单操作、2.35:1 参数读回、105 帧校验、四轮 MENU 往返、DAT 验签、独立解密和重新解包核对均通过。照片页标记叠加尚未通过验证，实机升级与拍摄未验收。

4.11 的历史交付使用本项目原有研究签名身份，随包提供公钥。原始官方固件、签名私钥和开发环境由工作区单独提供。
