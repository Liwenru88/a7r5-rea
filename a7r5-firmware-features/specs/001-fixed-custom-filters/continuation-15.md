# 第十五批：整预设原子输入、银行集合与双重帧屏障

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-26`
- Status: `OFFLINE_ATOMIC_INPUT_AND_CONTRACTS_VERIFIED_NOT_INSTALLABLE`

## 本轮交付

本轮完成T03d、T04b2b、T07c、T07d的限定离线范围。整预设、银行集合、版本包及帧引用核心已经实现并执行；原CP输入快照、资源守卫、回复和EVF显示入口已联合验证。**实际AP/CP入口、统一银行消费者和最后帧回收仍未安装；整套32槽功能未完成。**

| 文件 | 实际变化 |
|---|---|
| `native/af_apply.h/.c` | 整预设暂存、三组银行、全部输出范围先预留再启动、全成功统一发布；失败等待全部退役、启动前取消；20槽/64帧租约及拥有者屏障 |
| `native/af_apply_wire.c` | 128字节纯参数研究包；版本、父AP/CP身份、会话、消费者掩码、保留字段及CRC验证；失败不发布输出 |
| `native/af_cp406_state.h/.c/.S` | 九个CP输入字段及原额外更新标记，在原`0x24`互斥内准备；带锁入口和已持锁调用者使用的叶函数分开 |
| `a7filters/cp_atomic.py` | 新ARMv7和原CP有锁快照交错执行，首/中/末写点验证及无锁混合快照反例 |
| `a7filters/cp_release.py` | 原成对资源守卫、使用/持有退役、节点回收与真实缓冲归还函数；成功/驱动失败分列 |
| `a7filters/cp_reply.py` | 原CP回复封装、来源写入及ARM memcpy；成功、分配失败、发送失败回收、两类过滤 |
| `a7filters/cp_display.py` | 原EVF执行器和输出命令RTTI/虚表、初始化及通知入口；不认定颜色银行已接入 |
| `a7filters/baseline.py` | 正式审计自动运行新增原CP证据；可选`--cp-atomic-adapter`，保持身份/普通文件/128KiB预算和只读边界 |
| `tests/native_apply.c`、`test_native_apply.py` | 实际C业务契约、独立Python字节/CRC核对、合法CRC的语义拒绝及AArch64/ARMv7实际指令执行 |
| `tests/native_sanitizer.c`、`native_memory.c`、边界测试 | 新协议/CP状态失败无写探测，目标内存ABI辅助，错误CP在ELF/CPU之前拒绝 |

地址、接口、协议偏移、失败语义与实际接入清单见[整预设与帧引用](atomic-bank-access.md)。原AP挂钩、UI适配器、前缀适配器及既有核心逻辑保持；新增目标内存助手的`memmove`只供测试ELF，不替代原CP成像处理。

## 关键结果

1. 原子输入有可执行证据。持锁写入中，竞争原快照不改变目标；解锁后读到全部新值。不加锁的反例读到`[-3,4,-5,0,0,0,3,0]`混合值。仅表示输入准备完成，尚未统一发布原颜色/锐度银行。
2. 银行核心先检查所有输出范围，再允许生成；同一集合收集同会话/版本的必要消费者。任一失败保留旧活动版本，并等待全部已启动消费者退役。三组都被帧引用时拒绝新生成，避免覆盖。
3. 每帧声明全部输出，并自动增加拥有者屏障。输出全部结束但拥有者仍在，或拥有者结束而输出未退役，都不复用银行；重复/过期令牌拒绝。
4. 原JPEG守卫在驱动失败后仍可摘链、归还节点和发起缓冲归还。使用计数仍为1，证明守卫返回不能作为最后帧释放。后续缓冲管理器和DMA结束仍未观察。
5. 原回复存在“不发送也返回0”的过滤路径。找到原EVF显示对象及端点`0x9059081a`，但尚未关联照片颜色/锐度银行，因此物理握手和EVF/JPG同版使用仍不能声称完成。

## 实际验证

| 证据 | 结果 |
|---|---|
| [pytest回执](../../../.local/fixed-custom-filters/pytest-15-final.json) | 156项通过，测试输出2.83秒，命令3.066秒；两种目标ISA各执行20槽整预设/13消费者/三组银行/64帧契约 |
| [消毒器回执](../../../.local/fixed-custom-filters/native-sanitizer-15-final.json) | ASan+UBSan编译0.973秒、执行0.113秒、退出0；20000次输入/记录/UI/文档/CP前缀/整包及新CP状态探测，另有完整业务状态机 |
| [完整审计回执](../../../.local/fixed-custom-filters/cp-ui-access-406-15-final.json) | 修改4.06重新验签、736841帧/147成员/71目标、同包库和103资源；新原子输入/资源/回复/EVF入口通过 |
| [审计命令](../../../.local/fixed-custom-filters/audit-command-15-final.json) | 45.741秒，退出0；命令执行期间源码/测试指纹不变 |
| 原AP保持 | 24分支、1218刷新查询、864快照消费；旧六款/12原厂种子和资源查找保持 |
| [ARMv7构建回执](../../../.local/fixed-custom-filters/build-15-final/commands.json) | 独立研究ELF66984字节，SHA-256 `58a1b8fbbd07e7edeceedea5bebeb7aeda04be2dc824bffc52c858038199aa0b`；含写后`dmb sy` |

最初ARM目标测试缺`memmove`，补齐测试ABI后执行通过。最初CRC正确的拒绝测试将消费者掩码低字节清零，结果`0x1f00`仍是合法子集；纠正为超13位掩码后通过。该失败是测试期望错误，未将合法子集禁止。记录见[test-probe-15-correction.json](../../../.local/fixed-custom-filters/test-probe-15-correction.json)，早期研究ELF/探测回执保持，不覆盖成最终成功。

最终源码/文档/回执/产物/输入指纹和链接核对见[verification-continuation-15.json](../../../.local/fixed-custom-filters/verification-continuation-15.json)。新增代码已重新执行验证，不复用旧消毒器代替本轮结果。

## 复算

仓库根目录运行，报告必须使用新的路径。沿用既有未改UI/AP/纯参数研究ELF，以及本批独立原子输入研究ELF。不会生成安装包。

```sh
PYTHONPATH=a7r5-desktop/prepared/engine/site:a7r5-firmware-features/custom-filters \
  ./.venv/bin/python -B -m a7filters.baseline \
  /Users/wenruli/Desktop/索尼/BODYDATA.DAT --investigate-ui \
  --ui-adapter .local/fixed-custom-filters/build-12/ui-adapter.elf \
  --ap-ui-module .local/fixed-custom-filters/build-12/ap-ui-hooks.elf \
  --cp-parameter-adapter .local/fixed-custom-filters/build-13-verified/cp-parameters.elf \
  --cp-atomic-adapter .local/fixed-custom-filters/build-15-final/cp-atomic.elf \
  --report .local/fixed-custom-filters/next-atomic-frame-audit.json

./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short
```

构建用的完整编译/链接参数由`build-15-final/commands.json`记录；重建请使用新目录，避免覆盖旧产物和回执。`0x92000000`仅供隔离器，不能当作机身可用地址。

## 未完成项及原因

实际CP/硬件接入仍缺合法整包消息入口、AP future/CP消息生命周期、模式所需消费者、EVF/JPG到银行的版本关联、最后帧拥有者和缓冲管理器完成证据。这些是尚未解出的调用与寿命关系，不只是少一次实机测试；本轮没有用模拟回执填补。

LUT拟合仍缺真实ISP格式、色彩域、各基底模型和量化行为；不能用通用RGB插值冒充机内原生转换或生成可信色差。实际菜单还缺上述成像回执、合法机内保存位置、完整4.06 AP/Qt客体和真实SD事件。因此本轮保留解析/保存核心，补齐具体接线约束，未将T08/T09勾选完成。

总体`NOT_VERIFIED`。未操作相机、USB、SSH或真实SD，未读私钥，输入修改版4.06未改，未生成可安装固件，未暂存、提交或推送。
