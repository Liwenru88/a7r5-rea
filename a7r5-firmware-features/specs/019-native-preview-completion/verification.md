# 019离线验证记录

**后续QEMU补验更新：** 实际调参页使用独立事件入口，首轮遗漏已修复；最新AP为`401c16fe…`，重新执行95项相关CPU回归与107次Qt短窗口导航／原帧检查通过。长空闲关机崩溃、调参画面滞后疑点与原E4／成像仍未验收，整体为部分通过。当前结论见[QEMU补验验证记录](QEMU补验验证记录.md)。下文保留首轮AP `3cc55b…`及当时未运行QEMU的历史记录。

2026-11-04。95项完整相关CPU回归及独立重建通过；整体保持`NOT_VERIFIED`，新候选QEMU与机身验收未完成。新候选AP为`3cc55b4048c658ef9146e11bed236853ac439efc6dc25edc11e8021e35b89bd1`，CP为`35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300`。仅AP相对4.15变化，未生成新DAT，未连接相机。

## 已执行证据

表内`evidence/`相对于最终归档根目录`a7r5-firmware-features/native24-combined/verification/2026-11-04-preview-completion-01/`；`.local/`路径相对于仓库根目录。

| 验证 | 结果与证据 |
|---|---|
| 4.15先失败 | `evidence/before-03.xml`：2项预期失败，20.01秒；逐项E4结束后状态为失败，停止按键后的最后目标不推进。`evidence/before/session-result.json`绑定实际4.15 AP与源码摘要。 |
| 单修值通知的缺口 | `evidence/before-heartbeat.xml`：空闲心跳仍2项预期失败，值通知2项通过；最终覆盖两种事件。 |
| 高层发送器ABI | `evidence/before-native-send-abi.xml`：实际高层清理返回非零时，中间候选误判失败；最终在真正OSAL返回点观察，不依赖高层返回值。 |
| 回执并发注入先失败 | `evidence/before-race.xml`：1项预期失败，20.20秒；旧回执跨越新prepare后将未发送的新事务误标完成。该中间候选的源码与构建收据另存`evidence/intermediate-before-race/`。 |
| 最终定向集 | `evidence/receipt-targeted.xml`及同名目录：8项通过，79.50秒，绑定最终源码与AP／CP；含真实E4逐项发送、发送失败回退、属性完整性、回执并发隔离及两种事件的列表／调参页重绘。 |
| 完整相关回归 | 37＋18＋40＝95项全部通过，各组耗时147.42／508.96／573.00秒。实际收集集合、XML、57份源码摘要、组件及构建收据身份核对通过，零遗漏／重复／失败／跳过／错误；证明见`evidence/regression-receipts-final/complete-result.json`。 |
| 独立重建与预算 | `.local/native24-preview-fix-20261104-09`与`-10`四组件字节一致；构建与重建收据、`evidence/compatibility.json`齐备。AP BSS 290520字节，CP堆947000字节、代码7544字节；已知AP调用链静态栈和1376字节，保留65536字节外部预留；没有测量机身栈水位。 |
| 旧包保全 | 4.15的117项`CONTENTS.sha256`内容全部核对一致，清单自身SHA256为`78df550b3584d5218d06281a2983b7bfcfc91787b5a5676cabd7ce173fa71d1f`；未覆盖原包、签名或回执。 |
| 新候选QEMU | 未验证。检索到既有QEMU会话PID89176，未获结束其未保存模拟状态的答复；本轮未终止该会话或启动新菜单会话。无新截图，不复用旧画面宣称本轮成功。 |
| 机身／实际成像 | 未验证，无本轮设备I/O；用户仅报告4.15不再重启及浏览等待／刷新滞后，尚未测试中键确认。 |

最初`before-native-e4.log`曾因夹具递归出现Unicorn异常，未列为产品缺陷证据。中途被停止的多轮回归和已被替换的候选均不计入最终成功数量。

## 完整集合门禁与复现

三个分组各自的`full_related_suite`为假，不能篡改成单进程全套。集合门禁以一次实际收集的95项为准：各组零失败／跳过／错误，源码期间不变，57份测试相关源摘要一致，AP／CP及构建收据一致，三组无重复且并集严格等于收集集合。XML与会话报告逐项核对，使用`verify-complete-regression.py`生成独立完整性证明。

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B \
  a7r5-firmware-features/native24-combined/build.py \
  --output .local/native24-preview-rebuild-new

PYTHONDONTWRITEBYTECODE=1 \
A7R5_NATIVE24_BUILD="$PWD/.local/native24-preview-rebuild-new" \
A7R5_NATIVE24_EVIDENCE="$PWD/.local/native24-preview-rebuild-new/tests" \
.venv/bin/python -B -m pytest -x -q -p no:cacheprovider \
  a7r5-firmware-features/native24-combined/tests \
  --junitxml=.local/native24-preview-rebuild-new/tests/results.xml
```

本轮实际分组命令及参数在各`session-result.json`的`argv`中；收集结果在`expected.json`，并保留原日志。8项定向测试属于95项完整集合，不能累加为103个不同用例。

## 证据适用范围

执行真实AP／CP机器码；新增原E4用例执行原九次分派、消息分配复制、发送调用点及CP属性任务窗口。对象构造、OSAL、队列、时钟、文件和UI边界仍为明确夹具；其他旧回归保留自身E4夹具。原`0x402f`的CP消费、完整成像和真实帧元数据没有执行。失败注入让原错误处理返回，只验证私有回退，不能证明机身OSAL失败时不会终止。

原生事件回归通过不等于自然投递与屏幕刷新通过；QEMU已有原E4初始化边界仍需保留。后续分别验证无按键自然刷新、浏览与确认、快速切换、调参保存／重启恢复和实际成像，不能关闭发送／E4门禁以制造成功状态。

本轮交付范围为源码、固定审查组件、分析和离线证据；整体保持`NOT_VERIFIED`，不能作为机身可安装固件。原4.15升级包没有包含019修复。
