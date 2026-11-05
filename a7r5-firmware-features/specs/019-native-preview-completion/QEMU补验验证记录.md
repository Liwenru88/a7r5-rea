# 019补验验证记录

2026-11-04。新增DA真实事件入口已修复并验证，新AP为`401c16fe99a047f1440c2a9d1b7c5a48a9e5c380db5e57eed150d1604074f21f`。**整体为部分通过：长空闲关机崩溃尚未归因，调参画面数值存在滞后疑点，原E4及成像未验收。** 没有新DAT，没有本轮相机I/O。

最终审查根目录为`a7r5-firmware-features/native24-combined/verification/2026-11-04-preview-qemu-01/`；以下相对证据路径均以此为基准。

| 项目 | 实际结果 |
|---|---|
| 旧实例退出 | PID89176身份重新核对，用户授权后通过专属QMP退出，确认进程结束；`evidence/old-instance-close.json`。 |
| DA真实入口先失败 | 从原表项取得`0x1a6df54`，首轮AP `3cc55b…`上2项预期失败、D9的2项通过；`evidence/before-da-entry.xml`。 |
| 新AP定向回归 | 8项通过，78.58秒；真实DA入口、原E4、回执与自然事件处理，`evidence/targeted-final.xml`。 |
| 新AP完整相关回归 | 三组37＋18＋40＝95项全部通过，耗时152.45／511.78／572.78秒。源码57份、构建收据及AP／CP身份一致，完整实际收集集合与XML逐项核对，零遗漏／重复／失败／跳过；`evidence/regression-final/complete-result.json`。8项定向包含在95项内。 |
| 独立重建 | 构建13／14的四组件逐字节一致，仅AP相对首轮019变化；`evidence/compatibility.json`、`evidence/build/build.json`和`evidence/rebuild/build.json`。 |
| QEMU身份门禁 | 2项通过，0.195秒；拒绝旧AP、旧长度及错误图标／配方身份；`evidence/identity-tests-02.log`。 |
| 短窗口导航与原帧 | 107次真实Qt操作、107幅原始BIN／PNG核对通过；正式十二款、ST／FL2／FL3、Tab只浏览、中键返回、右键调参、八项工作值／重置及四轮MENU。Qt、工作进程、AP、CP退出码全部0；`evidence/qemu-proof.json`和`qemu/validation-driver.json`。 |
| 长空闲 | 失败。进入原生`0x316`关机页后，AP `0x34e620c`空指针读取`0x3cc`。未归因、未修复，不能确认与补丁无关；`evidence/long-idle-failed-source/failure.json`和`evidence/failed-runs/native-native12-410-skwpnr9t/console.log`。 |
| 像素数值一致性 | 未验收。`qemu/research-084-IDLE_LONG.png`清晰度显示1，而同次`qemu/research-actions.json`内AP工作值为2；原帧与PNG一致不能替代画面与模型一致。 |
| 旧交付保全 | 上一轮019的188项及4.15的117项内容校验一致；`evidence/previous-archives-preserved.json`。 |

## 停手观察

短窗口为1／5秒。下表数字是同次观察前后的计数差；空闲操作没有导航输入，也没有直接调用刷新协调器。

| 位置 | 自然心跳 | 输入 | 重绘请求／绘制调用 | 后台状态 |
|---|---:|---:|---:|---|
| Tab只浏览 | 78 | 0 | 0／0 | 0→0，未触发应用 |
| 首次自定义预览 | 284 | 0 | 1／1 | 1→5，仍受原E4在途保护 |
| 列表末次目标 | 284 | 0 | 0／0 | 5→5，保持等待 |
| 调参页 | 290 | 0 | 0／0 | 5→5，已收到自然事件，工作值尚未完成应用 |

四处像素均没有变化；首次预览的后台状态虽变化，恢复仍未结束，标题继续显示“切换中”。因此证明了自然事件接入及一次重绘调用，**没有证明可见成功／失败终态会自动更新**。详情见`qemu/idle-validation.json`。

## 复现与边界

在`a7r5-qemu`目录使用已有`.venv`、`PYTHONPATH=tools`与`experiments/native24-preview-idle/`的入口。固定清单为`build/native24-preview-idle-20261104-02/manifest.json`，成功短窗口运行目录为`runs/native-native12-410-veph2xqu`。新AP的CPU测试使用根目录`.venv`与`.local/native24-preview-fix-20261104-13`；实际命令在对应会话与驱动回执内。

观察库只透明包装事件与绘制入口，严格校验四个序言；原生状态、发送结果与E4完成不被改写。QEMU的CP侧车、系统服务、未完成的原E4和CP合成仍是边界，CPU机器码回归同样保留明确夹具。没有通过关闭保护、补造完成或修改关机原函数来制造通过。

第一次完整路线因DA未接入而失败；集中观察的“像素必须变化”判断过强；第二次较长空闲实际崩溃。三场均保留并且不计为通过；成功数量仅指最后短窗口场景。详细分析见[补验与接入修复](QEMU补验与调参页接入修复.md)。新组件只能审查，不能直接作为升级包安装。
