# 第57批：ST单基底连续软件链路与发布门禁

日期：2026-11-02。完成T03st57限定的离线软件范围。没有扩展其他基底、特殊2B或Gamma格式，没有连接相机、SSH、USB或真实SD，没有CP／ISP硬件模型。设备启动、真实存储和取景／JPG像素仍未验收。

## 本轮补齐了什么

此前默认参考转换／保存、AP发送、CP原生银行及主／Capture组件分别有测试，缺少同一份真实默认转换结果的连续联验。现新增[ST连续驱动](../../custom-filters/tests/st_lut_pipeline406.c)及[定向测试](../../custom-filters/tests/test_st_lut_pipeline406.py)，让实际默认转换产生的AJR2通过同一进程内的存储、通信及两个组件域，不再用手工配方替代中间结果。

实际跑通的参数链为：

```text
本地普通目录ST.cube（非恒等LUT）
 → 默认reference/context4四组件联合转换
 → 真实Repository事务保存C07
 → 删除测试源文件、关闭服务、清空目录状态、重开恢复
 → 八项工作参数编辑、显式保存、重开恢复
 → 标准AFD1/.a7filter导出回导（不重新拟合）
 → 实际af_imaging406绑定／AP发送器
 → 实际握手协议、28帧传输、CP接收拥有者／ACK
 → 原生银行深副本、九字段投影、E70输入复制
 → 主Gamma＋矩阵／CC1／网格组件
 → Gamma shadow／Capture生命期及独立颜色缓存
 → 普通Capture的双通道Gamma与mode11／mode6颜色组件
```

这条线在软件参数层连通；原任务调度、原构造和图像后端的端口范围见下文，不能将箭头直接解读成已观察到真实EVF或JPG像素。

随后把第二份非恒等CUBE装入同一C07，将八项工作值设成与第一次相同：配方和通信版本仍正确更新；第一次Capture继续使用自己的旧配方，第二次Capture使用新配方。切回原厂后，已存在的Capture按原生命周期完成；新主域恢复原Gamma／矩阵／CC1／网格，原A复用时也清除已跟踪的旧packed。没有新增图像帧租约或整配方原子发布机制。

取消初次导入不会产生槽记录；坏CUBE替换不会覆盖原有槽，重开后旧值保持；CP消费者明确拒绝时负ACK保留，不能记为已接受配方。原厂分组更新／回退约定保持。

## 新增发布约束

[software31/verify.py](../../custom-filters/experiments/software31/verify.py)在启用完整配方时强制执行上述ST测试，全部通过才发布`ST_photo_chain_software_verified=true`。测试缺失原始CP输入会直接失败，不能跳过后发通过回执。

[release406/build_candidate.py](../../custom-filters/experiments/release406/build_candidate.py)拒绝缺失或未通过这项证据的旧软件回执，且在创建输出目录或启动封装前拒绝。已实际使用旧第56批回执复现该拒绝；没有创建DAT或输出目录。

本轮没有更改AP／CP运行期生产源码。不是发现新成像挂钩后重新实现，而是补齐此前缺少的连续验证和打包门禁。较早测试探索失败分别来自驱动把DBC缓冲误用于E70、未提供原厂id2任务资格和mode6测试设置被重置；这些测试夹具已修正，失败目录保留，没有把它们称为产品故障复现。

## 实际验证与来源

| Evidence | 命令／回执 | 已取得结果 |
|---|---|---|
| E-405 | `.venv/bin/python -B .local/fixed-custom-filters/integration57-verify.py`；[验证回执](../../../.local/fixed-custom-filters/integration57-validation/verification.json) | 24个相关测试文件，445 passed／10旧配置skip，56.94秒、exit0；完整命令与输出在同目录commands.json |
| E-406 | 同一驱动ASan／UBSan四场景及7次原CP纯软件构表 | 成功、取消、损坏替换、CP拒绝四程序exit0；7个实际产品候选进入锁定CP的`41363C`，129点结果逐字节相同，输出保护区保持 |
| E-407 | `software31/verify.py --recipe-bridge --capture-copies --bootstrap-only`；[带门禁构建](../../../.local/fixed-custom-filters/integration57-software-gated/verification.json)及[旧回执拒绝](../../../.local/fixed-custom-filters/integration57-gate-rejection.json) | 70 passed，20.88秒、exit0；当前401项来源冻结；旧回执按预期非零退出，未创建输出 |
| E-408 | 当前AP预检／启动库链接、现有CP严格内存计划；[最终审计](../../../.local/fixed-custom-filters/integration57-final/verification.json) | 132前像／57 UI挂钩、AP及75项USR内容与现有DAT一致；CP51挂点／69窗口精确正逆，RX39280／40960、静态RW48744；361／401／113／29项来源分别核对当前摘要 |

以上各组按各自范围报告，不将445项与70项相加冒充不重复测试数量。目标产品字节未变，既有QEMU菜单／中文显示与原Fsys软件卷证据仍可按原范围引用；本轮没有重新运行QEMU或真实Fsys卷，不把普通目录当真实SD或机身`/setting`。

第一次真实转换的结果包含三tone `[-32,3,-19]`、12个非零矩阵项、21个非零CC1项和1215个非零网格项；证明本次连续输入确实使用四组件，不是恒等配方或只传八参数。实测驱动完成56帧、2份接收、7次私有Gamma组件构造及14次网格构造调用。

## 误差报告和模型边界

[导出文件独立检查](../../../.local/fixed-custom-filters/integration57-validation/filter-inspection.json)确认本例仍绑定ST/context4参考模型，43个留出样本，裁切0；预测ΔE76的均值／P95／最大值／灰阶均值／肤色均值分别为4.101／6.694／12.879／3.373／3.851。这是本例参考模型预测，不是本机实拍色差，也不能推广为任意LUT精度或全照片域误差。

导入初始参数为`[0,0,0,0,0,0,3,0]`，八项编辑保存后为`[1,1,1,1,1,1,4,1]`。文件仍保留原拟合报告，但`report_applies_to_saved=false`；报告不冒充已经评估编辑后新外观。

## 软件替代边界

- 文件端实际调用生产Repository／POSIX双副本和恢复逻辑，输入输出均为本地普通目录；物理SD、原Fsys卷及真实`/setting`耐久性未在本轮执行。
- 通信实际调用`af_imaging406`、AP发送器、握手算法、CP配方接收拥有者和ACK处理；会话71、单调时钟、消息分配发送及原锁／调度为显式端口，不代表真实机身通信任务已运行。
- 银行、输入投影、复制、Gamma伴随、Capture生命期及颜色组件均使用生产C。Jobs视图由真实银行借用建立，原RTOS/C4、原formatter构造和R实际复制字段读取由驱动提供，不声称完整AP／CP原任务联合执行。
- 原matrix／CC1／packer回调只生成明确的参数输出，再核实际拟合增量和原packed格式；没有图像、传感器、DMA、寄存器或ISP模拟。
- `41363C`仅执行固定原CP的纯软件构表函数。候选记录仅在隔离RAM中选表，原CP文件不变；没有运行新ARM模块、CP系统或后处理硬件。

## 对现有候选的影响和剩余验收

当前AP、四DSO、70资源以及CP均核对与第56批完整DAT一致，因此没有仅为更新测试证据重复生成同内容升级包。候选仍为[研究4.10／integration56](../../../.local/fixed-custom-filters/integration56-release410/update410/BODYDATA.DAT)，754525608字节，SHA `3e3d7e5759e39a0c8018e055e6309292eeb7c5ea742dd186b35e388bc180c158`。签名、独立解密、全归档回读与60复杂图像载荷审计沿用该同内容包的有效证据；以后重新打包必须使用本轮带ST门禁的新软件回执。

当前结论是**ST参考模型下的连续软件参数链已通过**。T03native55、T03f2和T12的更广范围不因此关闭；真实启动／MENU／AP-CP任务、物理SD／机内保存及实际取景／JPG效果仍需后续受控实机验收。在“不操作相机、不做CP／ISP硬件模拟”的条件下，本轮不伪造这些结论，不再把全基底扩展列为首轮ST验收的前置。
