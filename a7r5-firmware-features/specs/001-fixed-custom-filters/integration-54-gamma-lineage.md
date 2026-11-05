# 第54批：特殊2B的A／Q来源与Gamma银行关联

日期：2026-11-02。基于现有修改版4.06，只做离线原CPU软件窗口与宿主验证；没有连接相机、SSH、USB或物理SD，没有建立CP／ISP硬件模型。

## 结论与实际改动

本批补齐了A到固定Q、原owner、两通道Gamma参数地址，以及三类2B生产入口的可执行来源证据。新增[原指令审计实现](../../custom-filters/a7filters/cp_gamma_lineage406.py)、[可重复入口](../../custom-filters/experiments/photo-routes406/lineage.py)和[定向测试](../../custom-filters/tests/test_cp_gamma_lineage406.py)。不是只根据函数名或反汇编片段作判断。

**尚未补齐Gamma银行从构造完成到特殊2B消费时的版本归属，因而本批不修改产品AP／CP、不增加特殊Gamma补发、不生成新的升级包。** 这是成像接线的实现缺口，不能写成“只剩上机验收”。T03f2d与T03f2继续未完成，T03f2d1仅关闭下述来源窗口的离线子范围。

最终回执：[54个原软件窗口及错误CP拒绝](../../../.local/fixed-custom-filters/integration54-lineage-final/verification.json)；[47项相关测试](../../../.local/fixed-custom-filters/integration54-tests-final/verification.json)；[来源与交付核对](../../../.local/fixed-custom-filters/integration54-final/verification.json)。

## 已执行的来源链

固定CP原像SHA256为`18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97`。执行器逐次核完整身份，原代码映射只读；RAM、调用帧、计数器和描述符为显式夹具。到系统、寄存器或图像后端前停止，不给缺失服务返回“成功”。原memset属于实际执行的CPU内存操作。

| 环节 | 原地址及实际结果 | 能证明什么／不能证明什么 |
|---|---|---|
| 固定Q取得 | `AE3A70`：参数0返回`190BA9C`，非0返回`190C630` | 是固定资源getter，不是每张照片新分配的Q |
| owner生成 | `AE2D14`生成低16位；`462F16..32`拼接计数并推进；`FFFF`后回到1 | owner会复用；不能替代Capture birth、B epoch或滤镜version。计数窗口之外的RTOS锁未执行 |
| A绑定Q | `46BFD0..46C096`成功尾实际写`A+5A98=Q`、`A+5A9C=owner`、`A+BB0=Q+140`、`A+BB4=Q+7B8` | 两个不同A可得到相同BB0／BB4。申请资源本身及锁服务未执行 |
| Q内owner查找 | `462036..5C`在`Q+11C`链表查`node+8` | 原比较是32位owner相等，不含私有配方版本；节点为夹具，不能冒充生产持锁准入 |
| 首Gamma准备 | `AEC71A→AAC91A→AA7332→AA7FA8→AA86D0`，实际到`755B80`之前停止 | 同A的BB0决定目标描述符；参数包来自固定`1F6FF74`；这段没有读`A+5A9C`或私有版本 |
| 双通道构造准备 | `845DB8→AA7186`选择formatter；独立`AA7208→AA7F6C`窗口到`413DF0`之前停止 | formatter为`1F6DFDC／1F6E390`，构造输出为`1F6FF74／1F709F4`，mode1。原formatter与曲线core在此审计中没有执行，不能称完整构造成功 |
| 次Gamma准备 | `AAC94A→AA72C6→AA7FA8→AA86D0`，同样停在`755B80`之前 | root来自`A+BB8`，参数包来自`1F709F4`；没有证明每种2B计划都会走到此入口 |
| 次资源来源片段 | `AE3A4C→47D85C`取`19097E0`，`47D8F0／47D9A4`按原栈字段存／取pair，`47D9BA..CA`写BB8／BBC | 补齐一条原分配成功尾的来源；中间资源申请及完整任务未执行，不能把该固定Q推广到全部计划 |
| 次资源转移 | `47914E..84`把`5A58／5A5C`和`BB8／BBC`转移到另一个A并清源；`481042..62`仅复制BB0～BBC，不清源 | 转移与共享复制是两类事件。指针复制本身不带私有Capture版本，不能自动继承资格 |
| 初始化失效 | 原`AA6412`及实际memset清零主域和Capture区，停在`40FDAC`之前 | `1F6FF74／1F709F4`两个`0x466`字节包均被清零；不能把后续重新构造视作已完成 |

54是执行阶段数量，包含同一原窗口的不同输入，不是54个完整函数或54条完整成像链。所有阶段、实际写地址和原窗口摘要均在回执中。

### 2B生产入口不是一条路径

原`470A4A..54`先从`A+5A98`保存Q，`470AA8..470B16`构造元数据，`470BE6..470C00`计算`A+667C`，`470C22..2E`读backend child。随后实际执行分派窗口，分别在下列生产入口之前停止：

| 原调用帧条件 | 入口 | 实际准备的来源 |
|---|---|---|
| backend=0，child=0 | `463BB8`，调用点`470C9C` | r1=Q，r2=`[A+5A9C]`，r3=`A+220` |
| backend=1，child=0 | `463CD4`，调用点`47105A` | 同Q／owner／A+220 |
| backend=1，child=1 | `463DB4`，调用点`471CF0` | 同Q／owner，r3为该child输出描述符；使用相应回调对 |
| backend=1，child=2 | `463DB4`，调用点`471CF0` | 同Q／owner，描述符及回调对随child变化 |

backend和child是明确的原调用帧夹具；未执行中间日志、`45F6B4`、资源同步或完整生产函数。静态继续可见首类到`74077A→74793A`，另两类到`74083E`、`7408B2`；不能仅验证首类就宣布特殊2B整体完成。这些条件也不能冒充已经重新验证了历史“请求type4／type9”映射。

### 不能当作Gamma版本证据的另一入口

`872686`调用的`845BAC→AAC9FE→AA77DC`并非直接返回Gamma银行指针。原代码以`1F703F8`为参数委派`43BE3C`；后者读取回调并条件分派。审计实际停在`43BE3C`入口，没有预置回调或假定返回成功。因此`87268A`写入`[sl+C]`的返回值，目前不能命名为Gamma银行地址或版本号。

## 版本缺口由反例限定

本批实际执行三类反例，限定“来源已证明”的范围：

1. 不同A、不同owner、相同Q，到首Gamma上传边界时可得到完全相同的目标描述符和参数包地址。地址相等不能证明滤镜版本相等。
2. 原owner高16位计数回绕会产生相同owner。它可用于原资源登记，不能单独升级为不回绕的照片／配方代号。
3. 在明确保留A／Q的夹具中，执行原银行清零后，首Gamma准备仍可到寄存器helper前。**这不证明原调度允许该交错，也不证明机身存在此故障**；它证明上传准备函数本身不核银行是否已构造、属于哪个A或哪个滤镜版本。

现有产品`af_cp_components406_gamma_reset()`已在原reset前调用Capture失效；本批不是发现它漏掉清零。缺的是构造结束后到特殊consumer之间的完整覆盖／失效／串行化依据。现有`af_cp_capture406_scope_current()`仅核同步构造作用域，作用域结束后不能拿它给全局包永久背书。

## 接线的具体改动清单与门槛

下列是待实施接线，不是本批已完成内容；继续复用原厂分组更新／回退，不要求所有组件具有同一提交版本或整组原子回滚。

| 落点 | 必须补齐的语义 | 原来源与验证门槛 |
|---|---|---|
| `native/af_cp_capture406.c/.h` | 为实际Gamma构造事件关联A birth／B epoch／通道与该组件来源版本；A复用、资源转移、原厂重建和reset时撤销对应资格 | 不能从Q／owner／系数相等创建版本；旧组件允许保留，但其来源必须可解释 |
| `native/af_cp_components406.c`及原Gamma包装区 | 记录原完整参数包构造完成事件，不把`41363C` core返回等同`413DF0`全部后处理完成 | Capture直接分支`AA7222`和经`AA7280→AA6846→AA685C`的分支需一并覆盖；还要覆盖初始化／诊断写者和失败。不得直接添加一个未消费的银行标签就宣称接通 |
| `native/af_cp_capture_target406.c` | 把构造来源与真正提交时的A／Q／owner对应，区分`47914E`式转移与`481042`式共享复制 | 明确原锁／任务串行化的保护范围；不能跨原调用持私有锁或猜测原Q锁服务成功 |
| `experiments/packaging406/cp_carve406/capture_layout.py`及bootstrap | 仅在上述来源成立后登记实际近门／调用点与回退。候选关注`470C9C／47105A／471CF0`三类consumer及原Gamma完成边界 | 当前内存上限不能放宽：静态RW尾408B已归bootstrap，不是空闲区。新增代码／状态必须重新交叉链接、核预算、核原参数／LR／后处理、严格正逆 |
| Capture／组件定向测试 | 非零Gamma、同值换版本、不同A共享Q、owner回绕、reset、转移、并发及旧原厂回退 | 用来源事件驱动失败回归；没有来源资格仍完整委派原厂，不能以假ISP返回补齐 |

原`AA7F6C`的直接调用候选还包括`AA777C`，该处输出为栈内临时包；主域也经`AA685C`调用相同helper。必须区分输出范围，不能把所有mode1或同一helper的调用都登记成Capture持久银行发布。研究目录中的有界直接引用扫描只是候选清单，未穷尽间接调用或全对象别名。

因此当前仍缺两项核心证据：**两套固定包在生产提交前是否仍对应同一次构造，以及次Gamma stage是否覆盖这三类2B生产分支。** 只有确认这些语义或实施有来源的最小保护后才能新增产品接线；不能无条件给`0x2B`加`0x80`。

## 验证与交付边界

复跑命令（仓库根目录，输出必须为新的目录）：

```sh
.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/photo-routes406/lineage.py --output .local/fixed-custom-filters/integration54-lineage-final
.venv/bin/python -B -m pytest -q -p no:cacheprovider a7r5-firmware-features/custom-filters/tests/test_cp_gamma_lineage406.py a7r5-firmware-features/custom-filters/tests/test_cp_gamma_source406.py a7r5-firmware-features/custom-filters/tests/test_cp_capture406.py a7r5-firmware-features/custom-filters/tests/test_cp_capture_components406.py a7r5-firmware-features/custom-filters/tests/test_cp_capture_color406.py
```

定向回归47项通过，exit0。错误CP在CPU构造前拒绝；原代码／显式RAM写范围核验通过；系统／寄存器边界未执行。中间审计错误保留：最初混淆formatter的4字节头与正文，后按原`AA7F04／AA7F80`修正；另一次遗漏原`470C22`装载child，误带前窗口r5，现已执行真实装载窗口。最终回执只引用修正后的源，不把这些失败算作通过。

没有修改产品native、AP、CP或DAT，没有新增升级功能声明，也没有重跑未受影响的菜单／Fsys端到端。第53批4.10候选仍是原研究候选，不能因本批来源审计通过而认为特殊LUT生效、EVF／JPG像素已验收或允许安装。最终输入／产品来源核对另有回执；真实像素、介质及设备验收保持原任务状态。
