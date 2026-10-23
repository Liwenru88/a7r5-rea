# M1、M2 实施与验收

后续 Qt 延迟优化已单独记录在 [latency-verification.md](latency-verification.md)。下述 M1/M2 构建收据和包验收属于原交付基线；当前优化的归档、应用包和计时请以 `logs/latency-optimization/` 为准。

范围：T001—T009。只修改模拟环境；没有连接相机、操作 SD 卡或读取桌面原始分区镜像。M3 的 T010—T012 未实施。

## 当前结果

客户端使用 Python 3.14、PySide6 Essentials 6.12 和 Nuitka 4.3.1。交付为 `dist/A7R5 Emulator.app`，自带 Python、Qt、QEMU 和运行依赖，显示原厂应用产生的真实快照。网页入口保留为显式回退。

机身注册表共 35 项。目前启用六个菜单动作，以及仅限菜单场景的 C4 机内帮助，共 7 项。其他 28 项保留限制说明并禁用。完整清单不等于整机硬件或全部按键功能已模拟。

## 验证矩阵

| 编号 | 结果 | 实际证据 |
| --- | --- | --- |
| V-001 | PASS | `tests/accept-desktop.py`：Qt 真实窗口事件、C4 帮助/确认返回、四轮 MENU、六键预期像素、17 张原始帧/PNG、5 秒空闲暂停；`logs/desktop-implementation/qt-acceptance.json` |
| V-002 | PASS | 会话、窗口、输入释放、忙时关闭、超时停止、异常工作进程退出码回归；`regression.json` 与各模块日志。正常退出同时要求工作进程退出码 0 和 QMP quit 0 |
| V-003 | PASS | `config/controls.json`；官方正面/顶部/背面布局；注册表与禁用输入契约；实际窗口的“全部机身控制”页核对 |
| V-004 | PASS（限定功能） | C4 接收端按下/释放、原厂帮助画面和返回同一菜单；`c4-evidence.json`、Qt 17 帧。旋转候选接收成功但未通过反向恢复门槛，保持禁用，见 `candidate-summary.json` |
| V-005 | PASS | 资源路径、符号链接、只读数据目录、依赖篡改、共享锁；实际 macOS 沙箱拒绝私有文件读取、外部写入与 TCP，允许本次输出与 Unix QMP；包内动态库使用更窄的读取规则 |
| V-006 | NOT_RUN | Linux/Windows 固件后端与应用包没有对应真实主机验收；当前能力探测拒绝在这些平台启动 |
| V-007 | PASS | `input-integrity.json`：QEMU、内核、GPE 不变；1226 个归档条目仅模拟观察库改变；DTB 仅归档结束地址增加 512 字节；没有检查或改写原始分区镜像 |
| V-008 | PASS | `package-manual-acceptance.json`、`package-smoke.json`、`package-final-audit.json`、`web-smoke.json`；下述回执齐备后才切换默认入口 |

`logs/desktop-implementation/regression.json` 记录 44 项通过的回归检查（包含 C 策略检查）。独立错误类别在主要测试层覆盖；未改动模块复用成功证据。会话退出码、上下文缺失门槛和包验收定时器修复后分别重跑对应模块，没有重复全部固件启动。

Qt 17 帧来自 `runs/native-app-7wrfzwek/`，采用与历史基线独立比对的像素预期。后续收紧的是缺失页面证据时的拒绝分支和工作进程退出码校验；正常导航/客体初始化链没有改变。最终包额外执行其实际冻结入口与退出链。

## 应用包与独立窗口

独立窗口通过桌面自动化查看原厂菜单、点击 MENU 关闭/重新打开并点击退出。该会话还记录到 DOWN/UP 导航，共验收 5 张原始帧/PNG，QEMU 正常退出且 GUI/worker/QEMU 均结束。截图为 `logs/desktop-implementation/package-window.png`。

当前包从含空格路径运行；应用包父进程启动包内同一可执行文件的 `--worker app` 模式。最终固定冒烟从 `/private/tmp` 启动，核对帧、MENU、窗口关闭、worker 退出码与 QMP 回执。包内只保留一份固件归档；QEMU 重定位后有独立摘要，没有覆盖源码开发二进制。

运行时 `lsof` 核对 GUI、worker、QEMU，没有开发 `.venv` 或 Homebrew 库。全部 Mach-O 依赖审计没有 `/Users/`、`/opt/` 的绝对依赖；包内代码采用本地临时签名，未做外部分发公证。

网页回退通过 `tests/smoke-web.py`：真实 HTTP 启动、一张原始帧/PNG、STOP 与 QMP 正常退出。HTTP 的 Host、Origin、会话令牌、请求长度与固定输入拒绝测试通过。

## M2 的证据与边界

- `0x1f8`：原厂消费者收到 `[1,0]`，在初始 Add Item 条目打开帮助；Enter 后像素恢复同一菜单。实体删除按钮对应 C4，菜单帮助行为见 Sony 手册第 82 页。只开放菜单帮助，不开放回放删除或自定义拍摄功能。
- `0x10000013` 与 `±0x400`：接收回执齐备，双向画面均改变，但反向未回到基线；且无法区分前拨轮、后拨轮 L/R 与控制轮实体来源。该候选停止，不穷举数值、不启用任何实体拨轮。
- Fn、播放、自定义键：在归档的只读提取副本发现控制器字符串，但没有可靠数字事件映射，未注入未知值。
- 快门两段、AF-ON、AEL、录像、触摸与模式选择未达到各自语义/硬件门槛。机械操作不虚构数字事件。
- 公共输入只有经验证的成对 tap。按下与释放都检查返回值，失败不能被后续 sleep 掩盖；窗口失焦不持有宿主按键。长按、独立 press/release、任意旋转量、原始键码与任意 shell 都拒绝。

## 构建与修复记录

保留 `package-build*.log` 与失败回归记录，不将中间失败候选当作已验收交付。

1. 编译缓存下载了 x86_64 程序，与 ARM 工具链不兼容：禁用该缓存；固定 Nuitka 4.3.1。
2. uv 虚拟环境缺少 libpython 构建链接：在本项目 `.venv/lib` 增加指向现有解释器动态库的构建链接；最终包内封装并重定位，不依赖该链接运行。
3. 冻结运行时的 `sys.executable` 指向 Python 占位路径：改用明确的包内 `A7R5Emulator`，补充回归。
4. 帮助弹层关闭不一定生成 manager apply：以本次真实帧与保存的菜单帧核对，不把最后打开日志当当前页面。缺少证据时禁用新增控制。
5. 退出验收补齐 worker 自身退出码；固定包验收定时器补充等待阶段回归。

## 复现入口与恢复

- 日常使用：双击 `dist/A7R5 Emulator.app` 或默认菜单启动器。
- 开发客户端：`启动A7R5桌面开发.command`。
- 显式网页回退：`启动A7R5网页回退.command`，不自动切换、不同时双开 VM。
- 重新构建：项目环境执行 `packaging/build-macos.py`。新构建先产生候选，不自动覆盖当前交付包。
- 客体异常或协议失败：停止新输入，回收本次拥有的 VM，保留证据；不自动重发、切换键码或启动其他后端。

官方资料：[机身背面](https://helpguide.sony.net/ilc/2230/v1/en/contents/TP1000669448.html)、[顶部](https://helpguide.sony.net/ilc/2230/v1/en/contents/TP1000669449.html)、[正面](https://helpguide.sony.net/ilc/2230/v1/en/contents/TP1000669447.html)、[A7R5 帮助指南](https://helpguide.sony.net/ilc/2230/v1/en/print.pdf#page=82)、[Qt 部署](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html)、[Nuitka 更新记录](https://nuitka.net/changelog/Changelog.html)。

最终包固定冒烟已通过：约 32 秒取得原厂菜单、MENU 关闭画面，窗口正常退出；`host-exit.json` 同时记录 worker 0 与 QMP quit 0。默认入口已切换；三个启动器 `bash -n` 通过。最终包审计记录 58 个 Mach-O，只有一份固件归档，包大小以 `package-final-audit.json` 为准。
