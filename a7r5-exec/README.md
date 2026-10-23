# A7R5 快速执行工具

> GitHub 源码发布说明：当前研究签名公私钥经授权随源码保留；完整固件、其他私钥、SDK 二进制、真实操作包和历史验证现场仅留本地；旧链接可能指向未入库材料。环境与输入要求以 [根目录构建说明](../docs/build-inputs.md) 为准，本轮验证见 [验证记录](../docs/verification.md)。

2026-10-23 删除研究目录后的修复：离线客体验收现在从 `../a7r5-libjit/src/guest-loader*` 构建加载夹具，无须原 `analysis/`。当前源码资源由 `TOOL.json` 和 `check-tool` 校验；历史 `MANIFEST.sha256` 含早期运行目录快照，部分旧文件已不存在，保留用于追溯，不作为当前安装校验入口。工具资源变化后应重新准备会话，旧批准和旧操作包不重绑定。修复结果见 [验证记录](verification/analysis-removal-20261023/修复与验证.md)。

把本地命令或shell脚本封存为机内任务，提供libJit与kit两条入口。**`libjit.sh` 默认准备后直接执行，会访问相机**；每次调用生成新会话，无需逐次批准、永久尝试锁、待恢复解除或屏幕确认。`--prepare-only`、`prepare`、`check` 和 `status` 只操作本机。kit保留原有批准与恢复流程。

本工具不是交互终端，也不是固件刷写或恢复工具。脚本以root在真实挂载视图执行，可修改相机；超时与输出限制不构成安全沙箱。当前只交付离线验证，未用新工具访问相机。

## 两条路径的选择

| 项目 | libJit | kit root |
|---|---|---|
| 触发 | 上传精确 `/tmp/jiritsu/libJit.so` 即加载 | 临时预加载指向随机路径库，再一次DEBUG |
| 主机固定写入 | 新会话票据和固定库各一次 | 随机路径库、临时预加载各一次 |
| 预加载基线 | 精确512换行或已知boot.so指针，前后不变 | **只接受精确512换行**，机内中和至512换行 |
| DEBUG | 无 | 一次 |
| 载荷监督 | 实机已验证原版的原始系统调用监督者 | 复用kit监督者，复制件增加SIGXFSZ忽略处理 |
| 当前证据 | 原02包固定任务实机通过；新工具两种示例均QEMU通过 | 触发链有历史实机证据，新工具适配仅离线及QEMU通过 |

**当前优先使用libJit。** 历史实机记录的预加载是61字节boot.so指针；kit会拒绝它，不能把libJit能够执行视为kit也能够执行。工具不会删除或暂存这个自启指针，不提供强制覆盖、自动中和或放宽基线的选项。若需要改变基线，须另外准备并确认方案。即使kit拒绝，也可能已进入服务身份，不能认为它是对相机无影响的探测。

## libJit：一条命令执行

在本工程根目录执行：

```sh
# 直接执行并显示输出；需要时在当前终端输入sudo密码
./a7r5-exec/libjit.sh --command '/bin/cat /version.txt'

# 直接执行脚本；默认任务时限15秒，允许1至60秒
./a7r5-exec/libjit.sh --script ./a7r5-exec/examples/root-info.sh --timeout 15

# 仅本机准备：不提权、不查询设备、不执行任务
./a7r5-exec/libjit.sh --command '/bin/cat /version.txt' --prepare-only

# kit对应的离线准备入口
./a7r5-exec/kit-root.sh --script ./a7r5-exec/examples/root-info.sh --timeout 15
```

每次调用libJit都生成新的 `runs/<随机会话号>/`，记录目录写到标准错误，成功后的任务输出写到标准输出；失败返回非零退出码，日志留在本次目录。可以反复运行同一条命令，每次使用新票据和会话号，不复用机内claim。仅准备时输出材料目录和风险；只有kit输出 `ACCEPT-...` 短语。

脚本须1至8192字节UTF-8，无NUL/CR。构建前用 `/bin/sh -n` 检查语法，不在Mac执行用户脚本。命令和脚本互斥。不要直接改生成的配置或库：实际脚本已嵌入载荷，材料变化会使校验失败。修改任务后重新调用libjit.sh。libJit入口不接受 `--engine`，不能借此切换到kit。

libJit不需要 `approve`、`terminal` 或 `confirm-screen`。也可以双击生成的 `run-once.command`；libJit启动文件每次重新准备新会话再执行。底层 `execute --run` 仅消费指定的新会话；已有结果时应重新调用libjit.sh，不覆盖旧结果。

## kit：原有批准与执行流程

kit仍需先审阅本次 `task.sh`、`wrapped-task.sh`、`config.json`、`operation.json` 和风险，再执行：

```sh
RUN_DIR="/prepare输出的完整路径"
./a7r5-exec/a7r5-exec.sh check --run "$RUN_DIR"

# 将短语替换为本次check输出；批准命令本身不访问设备
./a7r5-exec/a7r5-exec.sh approve --run "$RUN_DIR" --accept ACCEPT-本次摘要

# 打开一次专用Terminal；只在本机窗口完成sudo认证
./a7r5-exec/a7r5-exec.sh terminal --run "$RUN_DIR"
```

kit也可以在批准后双击本次 `run-once.command`。不要从普通聊天传入密码。已有sudo缓存时，执行可能立即开始。

## 保留的设备与退出检查

执行前要求：唯一A7R5、同物理端口、普通USB身份、完整媒体和驱动均与封存配置一致；稳定独立供电，屏幕正常，期间不移动卡或拔线。默认绑定此前验证的 `locationID=0x00100000`、bus0/port1，版本及加载库摘要均须匹配；不提供运行时换端口或换端点。

程序取得工具级并发锁后观察主机、正常卸载相机卷、接管USB并两阶段认证/START；锁在进程结束时自动释放。libJit不创建永久尝试锁或待恢复标记，kit仍创建。先读版本和加载库，严格处理32KiB块间空包，完整SHA-256通过后才继续。主机只读写本次封存的有限路径和字节；`0x10000006`只记录stat失败，不声称文件不存在。

脚本运行门槛1至60秒，输出最多32KiB，超时后还有有界终止/收割等待。用户脚本运行在包装器的子shell，非零退出、超时、输出不符、状态变化、未知预加载或协议异常均不开放STOP。后台脱离、持久化、交互输入及内核阻塞不属于可靠完成范围。不要向本工具提交需要交互确认或持续驻留的任务。

完整成功终态、UID/EUID=0、输出长度及本次标记、前后预加载/中和、重复终态全部通过后，仅一次STOP。libJit还须包含解除加载文件和无活动后代回执；kit保留其原进程组检查，不能据此声称无所有逃逸后代。STOP即使Pipe error也不重发，之后只用主机元数据观察45秒内普通USB、完整媒体和驱动连续两次匹配。

## 结果与异常处理

```sh
# 只读本机结果，不查询相机
./a7r5-exec/a7r5-exec.sh status --run "$RUN_DIR"

# 仅kit需要：任务、USB及媒体全部通过且人工看到屏幕正常后执行
./a7r5-exec/a7r5-exec.sh confirm-screen --run "$RUN_DIR" --screen-normal
```

libJit成功后不需要人工确认命令，失败后也不留下阻止下一次调用的本机标记。历史 `PENDING_RECOVERY.json`、尝试锁和日志不会被删除；libJit忽略这些旧门禁，kit仍受它们约束。允许再次调用不等于相机已经恢复：普通USB身份、端口、媒体、驱动、版本、加载库、预加载或固定文件检查不通过时，本次仍会停止。

kit的 `confirm-screen` 只保存本机人工回执并解除对应待确认标记，保留永久尝试锁和日志；不能把任务失败改成成功。kit异常恢复及其门禁解除仍须另行审查。

异常后查看本次日志及相机屏幕，确认状态后再决定下一次调用。**本工具不自动重试、不补写中和、不重新认证、不补发STOP、不拔插或断电。** 非零退出、超时及协议异常仍保留原有STOP限制。

成功并不保证恢复覆盖前的原文件或拍摄功能。libJit写入精确路径时仍存在不可读既有文件被O_TRUNC覆盖的风险；库、票据、claim、状态及输出可能持久残留。kit载荷保留在随机路径，预加载只中和到512换行。不得盲删研究文件或为重试自动清理空间。

## 文件与依赖

- `exec.py`、三个 `.sh`：用户入口；`core.py`：准备、依赖和材料绑定；`controller.py`：设备执行、并发互斥与kit恢复门槛。
- `runtime/`：已验证的分块通道、接口指纹/主机观察器，以及两种操作适配。
- `payload/`：两种载荷源码；`sdk/`：目标libc和仅供摘要比较的加载库，不含整机分区镜像。
- `runs/<run>/`：用户脚本、包装脚本、配置、载荷、构建日志及Terminal脚本，实机后新增 `result/`。批准模板和永久锁仅用于kit。
- `result/session/events.jsonl`：认证、原始响应头、片段长度和边界；另有读取副本、状态、输出及失败部分响应。`result/result.json`和独立主机恢复记录是当前工具的判定依据，通用引擎摘要里的历史默认字段不能替代它们。
- `verification/`：来源、历史libJit实机回执、离线测试、新工具QEMU记录及旧材料保留核验。历史回执不代表本次新工具实机验收。

当前Mac复用工程 `.venv`、已安装的LLVM/lld/libusb，不安装依赖。脚本默认使用父目录 `.venv/bin/python`，其他位置可显式设置 `A7R5_PYTHON=/解释器路径`。准备时绑定其真实路径和摘要；已准备会话不能换解释器、工具链或目录。把工具复制到新位置后应重新prepare，不能沿用示例会话或原批准。

仅核对工具或运行离线测试：

```sh
./a7r5-exec/a7r5-exec.sh check-tool
.venv/bin/python -B ./a7r5-exec/run_offline_tests.py
```

CLI退出码：0表示本机动作或执行门槛通过；2表示拒绝或启动前错误；3表示设备尝试已停止且未全部通过。libJit会透传sudo启动失败的非零退出码。屏幕确认仅用于kit；程序不会自动判断相机屏幕或拍摄功能是否正常。
