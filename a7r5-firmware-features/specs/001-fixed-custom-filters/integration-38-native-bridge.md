# 完整配方消息接入与CP独立四页

日期：2026-10-31。基线仍为现有修改版4.06；不执行目标、硬件模拟或设备，不覆盖原输入，不生成可安装DAT。

## 已实施的完整通信链

`af_runtime_ap406`新增实际完整配方发送和回执入口：原启动会话、与PRESET／NATIVE共用单调版本、独立完整深拷贝、28次128B发送、精确ACK及有界截止。等待决定时拒绝其他私有发送；坏包／错源／旧ACK不清等待，截止或发送失败关闭入口，不重发或猜测free。确认了“END分配期间超时后仍继续发送并返回成功”的原竞态，现分配后、逐帧前及END返回后均核关闭状态；已经进入驱动的迟提交明确保留未知结果。

`af_cp_recipe406`把驻留接收器／解码工作、完整校验、显式消费者待决与决定接入真正`af_cp_hs_receive`，与纯参数共享版本屏障。确定拒绝产生负ACK，未知IO固定拥有权并关闭后续输入，不假称回滚。源、长度及魔数以外消息保持原委派。单份堆拥有者12080B，实际消费者未提供时不能协商。

`AF_RECIPE_BRIDGE406`配对构建才允许A7P1能力`0x40000`；A7R1内部能力仍为1。软件、AP动态请求、加载器及冻结清单核同一开关，旧回执缺字段视关闭，混用或非布尔拒绝。

[同进程完整入口测试](../../custom-filters/tests/test_recipe_actual_ingress.py)从实际AP启动端口、发送器进入原CP入口，再由CP发送端口同步回到AP回执。原系统端口是明确宿主边界，HELLO使用同一状态函数绕开固定固件发送地址。完整拒绝、BUSY后显式决定、56个分片、两个ACK和纯参数共享1～5版本均已执行；没有把软件prepared改称图像生效。

## 容量阻塞已由新布局解决

旧4KiB方案与6540B最小测量保留历史。新[cp_carve406](../../custom-filters/experiments/packaging406/cp_carve406/README.md)沿原SOLID region的实际大小字段扣除尾部四页：

| 用途 | 位置 | 使用／容量 |
|---|---|---|
| 新代码及RO | `2afc000..2aff000` | 9164／12288B |
| 新全局状态RW/XN | `2aff000..2b00000` | 292／4096B |
| 永久准入及回退 | 原`bef9e8..befb80` | 408／408B |
| 冷源 | 原必清BSS的`11cf000` | 与旧六款源、原候选源分离 |

原L1、32KiB L2池及全部模式栈不移动。原SOLID尾扫描按新size计算，不会把新增映射当作free-tail为零；保留代价是原可分配RAM少16KiB。新页经原extraMap的type2显式物理映射建立，type1只改已有属性不能代替。

永久引导先核原冷MMU/section并复制；最终在原映射流程后重新核TTBCR精确0／TTBR0／SCTLR、原L2池coarse类型、三页RX和一页RW的实际PA及W^X、完整目标CRC，再执行原I维护和phase2。未知映射、坏载荷和复制损坏均保持原回退。为保持原尾容量，目标使用共享literal的Thumb，`guard.c`为宿主控制参考；静态指令核对与C参考执行分别记录，未伪称ARM执行。

start4B、消息6B、快照4B均覆盖完整原指令，快照保持原MOVT和完整118B其余字节。实际snapshot symbol与新条件校验器配对；10个窗口只在匿名内存正逆变换，旧六款表、FNV和旧包装器前缀保持。最新构建为[carve-link-v8](../../../.local/implementation38-placement/carve-link-v8/verification.json)，[独立复核](../../../.local/implementation38-carve-safety-review/audit.json)未确认P1。

## 当前验证与接入边界

### 已接入四个原厂复制调用

`af_cp_input406`用336B固定伴随记录保存canonical快照和两个E70副本的真实版本。写者在原写入前发布busy，原复制、九字段覆盖及校验结束后才发布偶数epoch；64位版本分成两个32位原子word，读者前后核同一epoch。相同九值的新版本也不会混为旧配方。没有每帧分配、等待或C4字段占用。

`AF_CP_CAPTURE_COPIES406`保留独立构建分支，四个完整原BLX都改成BL到同一个原尾跳板：

| 原调用 | 原后续LR | 原逻辑输入／目的 | 原VD来源 |
|---|---|---|---|
| `898568` | `89856D` | `157AA10→164EEF0`，DBC | 没有VD；仍在原0x24锁内 |
| `4BAAB6` | `4BAABB` | `164EEF0→1653C68`，E70 | 原函数入口R0经`4B8D84`保存于原SP+B0 |
| `4BBA78` | `4BBA7D` | `164EEF0→16589E0`，E70 | 原`4BB206`保存于原SP+14 |
| `4BC002` | `4BC007` | 同上 | 同上，另一原控制分支 |

永久跳板在phase0直接尾调用原`5F51BC`，保持三参、SP和各自LR；phase2才转新RX入口。新入口push24B，按LR选择DBC或E70，原VD栈位相应为SP+C8／SP+2C，返回时pop24B／BX LR。不采用会在重启或CRC失败后遗留的运行期动态text补丁。输入模式与实际VD头分别保存；E70结束需源epoch、九值及目的DC0首word全部匹配，源刷新或坏VD仍完整复制一次，但不发布私有资格。

独立审查发现并复现了锁外故障窗口：prepare／release的unlock失败可在另一快照复制中途设置fault。现复制后再次核fault并撤销该目的raw资格；公开`af_cp_override406_read_input`读取前后再核全局fault，失败不写输出。原始伴随记录只证明复制历史，不能绕过公开入口取得成像资格。新增故障回归覆盖复制中与发布后两种故障，不通过重复原copy伪装回滚。

包含公开读取ABI的实际copy分支RX为12268／12288B、RW为628／4096B、原尾404／408B。四BL、真实LR、原栈偏移、所有分派、原厂回退及32位原子分别有主机行为或实际ELF静态证据；没有执行ARM或相机。剩余20B无法容纳完整组件应用，后续组件接入必须重新核算布局，不能静默越界。

这完成的是固定原复制入口的代码接线。三条伴随记录不锁住原E70缓冲，也不是参数bank或图像帧引用；原调用之后的其他写者、C4异步借用和四组件共同发布仍须独立闭合。当前FULL_RECIPE消费者、EVF／JPG与安装门禁保持原状态。

### 后续发布语义的关键待决项

[完整原发布审计](../../../.local/implementation39-native-owner-barrier/README.md)确认：Pre不提供全八项成功屏障，Post在某些超时／部分pending下仍会分组采用新银行或沿用旧字段；共同完成回调也不携带成功状态或配方版本。Gamma的flags0／2和color提前selector翻转独立于共同mask，因此仅给mask加0x4C不能实现整配方留旧。

当前严格AC-008要求与“完全沿用原厂分组失败行为”有实质实现差异。已向用户请求确定失败语义：沿用原厂机制，或额外实现整配方切换／整组留旧。答复前不降低现有AC，不编写绕过门禁的发布代码，不把复制、pending0或Post返回当成完整成像成功。已完成的T07e3a和431项证据不依赖此选择。

另有[永久门禁90B候选](../../../.local/fixed-custom-filters/implementation38-native-identity/BOOT-PERMANENT-GATES.md)与[Gamma真实outer复用](../../../.local/fixed-custom-filters/implementation38-native-identity/GAMMA-OUTER-REUSE.md)，目前仅独立.local材料，未改旧六生产包装器。Gamma现有AJR1仅保存绝对曲线，未保存basis三项明暗控制；不能将ST/column6的绝对曲线无条件覆盖其他column及八项调参。此为后续版本化保存及原生应用需要处理的明确缺口，不把静态候选称为已实现组件消费。

[最新统一回执](../../../.local/fixed-custom-filters/implementation38-copy-source-software/verification.json)：431项主机相关回归通过，68.02秒，退出0且334个源指纹前后一致；AArch64／Thumb编译链接通过。动态UI与转换后端字节保持，完整配方AP研究模块92128B，含copy入口的CP研究模块91848B；它们与实际有界carve模块分别记证。原402项／48.46秒是加入输入复制前的历史检查点。

真实原生成像消费者仍未绑定，FULL_RECIPE拒绝协商，原UI的kind1、32槽发布及安装准入保持关闭。空间不足已解决，不应继续把“CP只有4KiB”作为当前阻塞；后续主线是原VD请求／C4来源、原bank内四组件应用以及CPU输入借用退休。Gamma原bank内嵌数组支持复用原资源寿命，无需默认建立私有图像帧owner；E70外AE/WB／运行域与私有基底/LUT/八值的版本要求分开。

静态追踪正在核原VD_Pre／VD_Post、实际母C4到八类原完成入口、两套Gamma和其他Capture阶段；有据字段不等于完整流水线已验收。旧六迁移、其他基底拟合资格和真实介质／取景JPG继续保留原任务，父里程碑未关闭。
