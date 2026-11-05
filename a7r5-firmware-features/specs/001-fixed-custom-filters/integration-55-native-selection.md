# 第55批：用户槽配方接回原厂构造与选表

日期：2026-11-02。继续基于修改版4.06，不操作相机，不做CP／ISP硬件模拟。按最新授权，把主线收敛到既有用户槽、参数快照和原厂构造／选表；不继续无依据扩展特殊2B研究。

## 本批实际修复

在[af_cp_components406.c](../../custom-filters/native/af_cp_components406.c)修复了主Gamma与Capture Gamma共用的选表来源检查。原先只接受`BF0000..107F000`范围，修改版4.06继承的FL2／FL3曲线却在范围之外；因此即使用户配方、原厂选表和同步来源均有效，也会回退原曲线，未施加LUT拟合的Gamma增量。

这次只有一个产品C文件改变：新增共用`gamma_record_source()`，两入口调用它。保留旧RO策略，额外仅接受原表已证route／column对应的四个精确位置：

| 原基底wire | Gamma route | column0～5 | column6 |
|---|---|---|---|
| FL2：19 | 47 | `1195080` | `1A39DBC` |
| FL3：20 | 48 | `BEFB80` | `BEFDC0` |

仍从原表读取指针，复制原576字节记录，只修改129点曲线及原末点字段；附属参数和后处理保持。没有修改原厂FL2／FL3曲线、没有改表项或把新Gamma送到任意RAM，没有新增成像路径、银行调度、帧租约或整组原子发布。矩阵、CC1和网格继续使用既有原构造／packer，本批不重写它们。

原厂外观、无用户配方、来源失效、读记录失败和非法地址仍委派原厂。`2B`的Gamma mask和生产入口未改；历史证据保留，尚未验证的特殊场景不因此被称为已支持。

## 按用户槽到构造入口连续验证

新增[定向集成测试](../../custom-filters/tests/test_cp_native_gamma_selection406.py)，复用现有Capture驱动的原调用端口，在一个C进程内实际运行产品代码：

```text
用户槽C07／C20安装、读取
 → 原生配方校验及驻留副本接收
 → 原参数快照复制与九字段投影
 → 原E70输入复制／输入版本
 → 对应原生配方借用
 → 主Gamma或Capture Gamma构表入口
 → 候选576字节原生记录
```

并将该候选交给固定4.06的实际CPU代码`41363C`：先执行原曲线构造作对照，再仅在隔离RAM的Gamma表中切换候选指针，执行原构造。15组ST／FL2／FL3、普通列／第6列、主mode0／Capture mode1的输出曲线均逐字节等于产品候选，原采样轴不变，写入限于输出与工作栈。

这里实际执行的是原CPU的软件构造函数；没有执行新ARM模块、完整RTOS worker或寄存器上传。原worker视图、调用帧、formatter／shadow、系统调用及部分原函数是明确的宿主端口／RAM夹具，不能冒充真实线程、相机曝光条件或ISP像素。库中带`_locked`的API在宿主串行调用，未模拟RTOS锁。Capture后处理的宿主标记仅核调用顺序和不被覆盖，不是完整原`413DF0`后处理执行回执。

定向测试还覆盖：同样基底和八项值、LUT版本7→9时主域重新构表；旧Capture保持按值快照；退出私有来源后恢复原曲线；错route、错column、偏移4字节、任意RAM、原helper／声音区地址不取得新增资格。完整原厂切回／AP发送／请求副本／Capture颜色缓存及矩阵、CC1、网格则复用现有生产模块并重新运行相关回归。

## 实际验证结果

| 证据 | 结果 | 范围 |
|---|---|---|
| [修复前原实现回放](../../../.local/fixed-custom-filters/integration55-red-replay/verification.json) | 当前最终驱动配旧产品C：ST对照通过，FL2／FL3四个选表案例按预期失败 | 明确复现原Gamma回退，旧源码副本及编译命令保留 |
| [最终定向模块回归](../../../.local/fixed-custom-filters/integration55-tests-final/verification.json) | 310 passed，10 skipped，17.74秒，exit0 | 13个相关测试文件；10项为旧配置不绑定Capture，不是失败隐藏；非全仓库测试 |
| [ASan／UBSan](../../../.local/fixed-custom-filters/integration55-sanitizers/verification.json) | 36场景通过 | 15个有效组合及21个错配回退；保存实际原记录及候选字节 |
| [原CPU构造独立回读](../../../.local/fixed-custom-filters/integration55-native-vectors/verification.json) | 15组通过 | 候选由产品C生成；原构造实际读取，轴和输出保护区保持；不是像素精度对照 |
| [当前ARM链接](../../../.local/fixed-custom-filters/integration55-native/verification.json) | RX39280／40960，较前批增加88B；静态RW48744保持，驻留49152含408B bootstrap；51挂点、1280B合同保持 | 没有增加静态状态、堆工作区、近门或更改页数 |
| [严格内存正逆](../../../.local/fixed-custom-filters/integration55-memory/verification.json) | 69窗口精确反向还原，错误原像拒绝；原FL2／FL3四曲线及原载荷保持 | 候选CP仅在内存中生成，SHA为`ef616a6581dac99106380a4f56da9d88093680cf524f72b0eb0b502cea58fc99`；未写CP或DAT |

最终来源、输入与交付核对见[本批总回执](../../../.local/fixed-custom-filters/integration55-final/verification.json)。原修改版4.06 DAT保持，原厂／旧六款及非目标产品源文件保持。

## 完成边界

T03native55a／b完成：本批实际修复了原厂选表入口的漏项，并闭合用户槽原生配方到原Gamma构造的软件验证。T03native55整体和T03f2不在本批升级为全部照片取景／JPG完成；完整原AP／CP照片任务联合运行及真实像素没有在本环境执行，T12仍未验收。

本修复不增加全12基底的标定模型，不扩大AJR2／AJR3或完整Gamma格式，也不证明任意LUT实拍误差。原厂分组更新／失败回退保持，未新增所有组件必须同版的要求。

新目标ELF位于`integration55-native/cp-carve-OFFLINE-ONLY.elf`，可供后续当前源组合构建。**现有第53批4.10研究DAT尚未包含本修复**；本批未生成或批准新的升级包，不能把新ELF当作可直接安装文件。
