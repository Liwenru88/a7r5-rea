# 首批验证记录

> 最新按键扩展已交付：19 项有条件开放，独立包 127 次 Qt 操作、128 帧独立核对、72 项定向回归和正常退出通过，旧版保留。操作与完整限制见 [按键扩展说明](button-expansion.md)，总收据为 `logs/function-expansion/button-expansion-summary.json`。下文的旧运行清单和交付路径属于历史批次。

> 本文首批内容是历史批次快照。Fn / DISP / 空介质回放的后续结果以 `fn-disp-playback.md` 和 `logs/key-dispatch/` 为准；下文“未通过”的旧结论不代表当前版本。

2026-10-20。目标是完善真实菜单、输入与代表性设置；整机全部功能尚未完成。范围仅桌面原生模拟环境，无相机、SD 卡或原始分区镜像操作。

## 已实现与修复

- `tools/input_context.py`、`config/controls.json`：识别选项弹层并开放已知 C4 帮助往返；缺少页面依据、未知上下文或错误返回帧保持拒绝。
- `tools/headless_osd_capture.py`：限定内核日志清理提前到快照边界解析前；保留原始容器、序列、长度、FNV/SHA 和 PNG 校验。
- `tools/backup_snapshot.py`、`research-input-map.py`：只读解析当前模拟副本的 BK4 设置与输入分发表，核对 ELF 副本后生成候选；不依赖旧研究目录运行。
- `tools/function_batch.py`：固定候选诊断，与客户端正式白名单分离。Fn、DISP、回放暂不启用。
- `tests/accept-functions.py`：真实 Qt 设置/帮助/分类导航验收，逐次保存原始帧和点击耗时。

## 实际证据

| 检查 | 本次结果 | 记录 |
| --- | --- | --- |
| 定向回归 | 12 个测试入口、42 个测试通过 | `logs/function-expansion/regression.json` 与同目录 `test-*.log`；注册表配置最终修改后另行通过 |
| HTTP 契约 | 5 个测试通过 | `logs/function-expansion/http-contract.log` |
| 新菜单/设置 Qt 流程 | 33 次真实点击、34 张原始帧/PNG 通过 | `logs/function-expansion/qt-functions.json`；`runs/native-app-b3w_ez9j` |
| 原有 Qt 导航 | 16 次点击、17 张原始帧/PNG 通过 | `logs/function-expansion/qt-navigation.json`；`runs/native-app-r9zxgkuv` |
| 网页回退 | 一帧与正常退出通过 | `logs/desktop-implementation/web-smoke.json`、`logs/function-expansion/web-smoke.log` |
| 快照故障重放 | 保存的实际失败响应重新解析成功 | `logs/function-expansion/framing-replay.json`；先失败、后通过日志 `framing-before.log` / `framing-after.log` |
| 研究帧独立核验 | 四个研究会话，39 帧通过 | `logs/function-expansion/research-frame-verification.json` |
| 独立应用构建及冒烟 | 构建通过；包内初始菜单、MENU 关闭及 QMP 退出通过，2 帧独立核对 | `logs/function-expansion/package-build.json`、`package-smoke.json`、`package-delivery.json` |
| 固定客体不变 | 运行清单与全部固定输入摘要未变化 | `logs/function-expansion/runtime-unchanged.json` |

设置测试：初始 My Menu 下五次 DOWN→ENTER，Off 选项→C4 原厂帮助→ENTER 回到同一选项→UP 选 On→ENTER 提交→重进确认为 On→DOWN 选 Off→ENTER→重进 Off。还原的 Off 选项像素 SHA-256 为 `1f1e6f4d09729d71079ce9d7090b58cd8a22b76d3e0531ec4a12a1f3896042ce`，与修改前一致。随后 MENU 关闭弹层、四轮顶层开关，再遍历八个菜单分类。所有预期来自单独检查过的原厂帧；未用替代图像绘制菜单。

新流程点击至 Qt 显示：中位 427.753 ms，最大 566.492 ms。原有 16 次流程中位 454.480 ms，最大 600.024 ms；这不是持续取景帧率。两个 Qt 会话与网页会话都获得 `qmp-quit / exit_code=0`，源码 Qt 同时核对工作进程退出。42 个定向测试和 HTTP 5 个测试的假会话不作为固件功能证据。

## 交付与回退

当前应用为 `dist/A7R5 Emulator.app`，旧的性能优化版保留为 `build/desktop-pre-functions-20261020.app`。构建收据核对全部 `client/`、`tools/` 源码摘要与最终注册表；包内自带 Python/Qt/QEMU，不需要开发环境。回退时退出所有模拟器，再单独启动保留的旧应用。

最终目录中的应用包另经原生窗口点击验证：五次 DOWN→ENTER→C4→ENTER，帮助返回相同选项页，9 张原始帧/PNG 独立核对通过，应用进程退出 0 且 QMP 退出 0。见 `logs/function-expansion/package-manual.json`。

验收工具曾在冒烟结束后额外重开旧候选；移动候选前未识别这一实例，旧路径下的注册表随后不存在，该额外启动失败。该会话 QMP 退出 0、工作进程退出 1，已明确排除，失败窗口按其“保留未确认记录”流程关闭。见 `logs/function-expansion/extra-launch-incident.json`。最终目录的独立人工验收发生在此后，不使用这次失败启动作通过证据。

## 仍未验证/未实现

仅证明八类菜单可达及一个代表性设置的当前会话回读，未逐项验收所有菜单子页、拍摄参数或跨启动保存。C1/C2/C3、拨轮、Fn、DISP、实际回放未通过。取景、拍照、录像和完整 CP/镜头/传感器依赖仍缺失；后续虚拟图像方案尚未实施。详细状态与下一步见 `capabilities.md`。

## 2026-10-20 Fn / DISP / 空介质回放续批

- 原厂初始设置、Fn 导航与提示返回、Fn 反复开关、五种 DISP 布局、两次空介质回放往返、条目层和分类层各四轮 MENU：最终 53 次真实 Qt 操作及 54 张原始帧/PNG 通过，见 `logs/key-dispatch/qt-function-keys.json`。首次 37 次流程的证据和验收器修正仍保留；逐像素校验说明见 `fn-disp-playback.md`。
- 原有 Qt 六键/C4/四轮 MENU：16 次操作、17 帧通过，`qt-navigation.json`；设置/帮助/八分类：33 次操作、34 帧通过，首次为 `qt-settings-regression.json`，MENU 分类层修复后为 `qt-settings-final.json`。文件均位于 `logs/key-dispatch/`，取得 worker 0 / QMP quit 0。
- 46 项输入、帧、初始化、会话、沙箱及窗口回归通过；另外固定协议 2 项、资源 4 项、包定时器 1 项、HTTP 5 项通过。输入跟踪与固定隐私入口的 C 契约编译运行通过。日志均在 `logs/key-dispatch/`。
- 40 张诊断会话原始帧独立核对通过：`research-verification.json`。附加释放和固定等待未解除原厂过滤；不再用增加等待规避状态问题。
- 原厂归档 1226 项仅模拟库不同，指纹重新绑定并逐项核对；原厂 ELF、资源、库、内核保持不变：`runtime-rebind.json`。当前归档 `menu-daf0f137f7a3230d.cpio`。
- 新版自包含包构建通过，源码摘要、注册表和唯一固件归档核对通过；冻结入口从 `/private/tmp` 启动，真实菜单、MENU 和正常退出冒烟通过，2 张原始帧核对通过。见 `package-build.json`、`package-source-audit.json`、`package-smoke.json`、`package-smoke-frames.json`。
- 网页回退的一帧与正常退出通过，`web-smoke.log`。网页没有新增功能面板；功能按钮在 Qt 客户端验收。

MENU 分类层修复后，受影响的 27 项定向回归通过，固定冻结包测试的 2 项定时器/提前退出检查通过。见 `menu-group-regression.log`、`function-acceptance-timer.log`。未修改的模块复用此前成功证据，没有重复全套测试。

窗口捕捉服务在解锁后仍报 ScreenCaptureKit `-3811`，桌面自动化人工复核未完成；失败工具会话单列在 `menu-group-incident.json`、`package-capture-tool-failure.json`，不作为正常窗口证据。独立包的完整 Qt 固定功能模式记录在 `package-functions.json`，最终交付记录在 `package-delivery.json`；相应通过收据不存在时不视为通过。实际照片回放、传感器输入、拍摄、录像和跨启动保存仍未实现。

最终交付已完成：独立包固定 Qt 模式 53 次操作、54 张原始帧与 PNG 通过，GUI 0、worker 0、QMP quit 0，见 `package-functions.json`、`package-function-frames.json`。将旧版完整移至 `build/desktop-pre-input-keys-20261020.app` 后，新版位于 `dist/A7R5 Emulator.app`；该最终路径从 `/private/tmp` 启动、真实菜单/MENU 和正常退出冒烟通过，见 `delivery-smoke.json`。同一状态下源码功能流程中位点击延迟 375.57 ms，包内流程为 381.65 ms，不能视为持续视频帧率或物理显示扫描延迟。
