# 第36批：核心输入修复、实际绑定与完整功能阻塞

本批没有完成完整自定义LUT功能。实际修改了CP配方版本的锁内提交、原UI成像发送器的登记与就绪后绑定，并完成当前代码的相关回归和准备镜像组合。原消息入口安装、完整1943B配方传输、同次原生消费／同步以及照片颜色模型仍未闭合；产品继续关闭，不把源码接线称为相机可用。

## 已实施的核心改动

| 落点 | 实际行为 |
|---|---|
| [af_cp_override406.c](../../custom-filters/native/af_cp_override406.c)／[头文件](../../custom-filters/native/af_cp_override406.h) | 私有对象增加64位version；prepare／release与叶发布接口显式接收版本，在原0x24锁内与mode、slot和完整预设提交；拥有者独立拒绝零、重复和回退版本，不依赖解锁后的诊断变量 |
| [af_hs_cp406.c](../../custom-filters/native/af_hs_cp406.c) | 将既有128B包的version传到上述接口；已有会话状态时configure返回BUSY，禁止无排空证明地清会话和版本。包长、ID、能力位及原消息委派保持 |
| [af_ap_ui.c](../../custom-filters/native/af_ap_ui.c)／[头文件](../../custom-filters/native/af_ap_ui.h) | 新provider只原子发布驻留metadata；既有原refresh拥有者核manager／启用／选槽／重入后，等待真实HELLO能力并调用现有af_ap_imaging_bind一次。非BUSY错误终止自动尝试，不补发先前选择 |
| [af_bootstrap406.c](../../custom-filters/experiments/packaging406/loader/af_bootstrap406.c) | 产品publish末尾登记provider；回调先核installed和admission，再解析已验证requests模块中的af_imaging406_binding。installed采用release／acquire，重复publish拒绝。没有设置admission成功或安装3554d90／3554d38 |
| [CP配对构建](../../custom-filters/experiments/packaging406/cp_bootstrap/build_paired.py)及同目录guard／gates／memory_plan | 实际新模块RX3352B、RW288B；phase移到RW新尾1a3ac60，BSS扩展292B且原页表根不移动；生成C／汇编共同常量，并核实际phase字和CRC。旧phase1a3ac50会落入新RW，不能沿用 |

原厂12项／FL2／FL3、原六槽委派及固定32槽数量保持；没有修改原DAT、CPIO、USR或写出CP分区候选。私有版本进入输入拥有者，不等于已经进入原C4、参数银行或图像帧。

## 已执行验证

- [版本回归](../../../.local/fixed-custom-filters/continuation36-core/version-regression.json)：旧实现实际接受重复版本，契约先失败；新实现拒绝重复／回退，原厂退出消费同一版本序列，覆盖大于32位和UINT64_MAX边界。相关原厂回切、UI事件及接收端契约纳入最终回归。
- [当前统一软件结果](../../../.local/fixed-custom-filters/continuation36-final-software/verification.json)：289 passed in28.36s，当前源码与fixture无漂移；动态UI126312B、仓库112696B、固定AP、AP／CP请求与适配器目标编译链接通过。5项provider定向结果包含在289中，不另累加。
- [CP模块](../../../.local/fixed-custom-filters/continuation36-cp-final-module/verification.json)／[配对引导](../../../.local/fixed-custom-filters/continuation36-cp-final-bootstrap/verification.json)：原408B尾仍精确容纳；RX CRC为44b0e57f，实际literal在偏移168；实际phase字在befb68，值1a3ac60，位于RW之后。没有执行ARM／MMU／缓存指令。
- [CP仅内存计划](../../../.local/fixed-custom-filters/continuation36-cp-final-memory/verification.json)／[宿主控制契约](../../../.local/fixed-custom-filters/continuation36-cp-final-host/verification.json)：9窗口应用／逆转逐字一致、错源拒绝、旧六源及旧包装器前缀保持；5组宿主边界通过。生成头遮蔽／实际descriptor及phase另2项0.09秒通过。没有写CP文件。
- [准备镜像](../../../.local/fixed-custom-filters/continuation36-full-unsigned-usr/verification.json)／[实际回读](../../../.local/fixed-custom-filters/continuation36-core/image-readback.json)：7AP窗口＋70资源＋4DSO，410652672B，SHA`37e0a25b2a1207a0ea7aaa655e49742c06435958535c5f5898ca4162e6defd47`；1043原项及无关元数据保持，新增后1047项，e2fsck0，全部74组件及AP逆窗口回原摘要通过。启动库80464B／26f9377a…ba81。7项启动宿主1.93秒通过；这是未签名USR准备文件，CP未更新、UI未发布、不可安装。

前一批283项和USR v2保留历史身份，不作为本批CP接口修改后的完整回归。本批初次284项已由包含provider的当前289项替代，旧回执不覆盖。

## 为什么当前不能交付完整功能

### 照片颜色模型缺两项实际输入

[颜色专项审计](../../../.local/fixed-custom-filters/continuation36-color-model/README.md)核对15份固定来源和两份NPZ。已有解析、联合搜索、量化及误差报告，但predict还需要：

1. 本版照片sRGB与原生颜色阶段之间的输入／输出域桥，含校准和拍摄上下文。
2. 本CP非零1215网格的像素坐标、倍率、插值／舍入及相对其他组件的位置和交互。

参考Edit链的整数输入与14bit输出不自动等于本版照片sRGB；405字打包和SRAM布局也不能推出像素算子。A7C2的有限控制响应属于另一机型；固定PT的经验响应不能证明变化Gamma／矩阵／CC1后的联合模型。没有把合成模型摘要、另机型响应或除16383的归一化当成本版依据。

可解除该阻塞的最小输入是同一CP摘要下的完整照片前向算子来源／ISP定义，或足以约束上述两函数、带原生参数与域标签的阶段数值，且含非零网格和组件联合变化及独立留出组。不一定需要照片文件，但不能只有旧CP、SRAM字节或固定基底样本。本批同时只读检查上游训练仓迁移，固定源码及刷新材料保留在本地主线证据目录；不执行下载的脚本。

[迁移后有界刷新](../../../.local/fixed-custom-filters/continuation36-color-refresh/README.md)锁定公开ColorLab新仓8bd8564f…，读取12份固定文本；5份关键文件与旧缓存逐字相同。fit_anchor_native仍自标Edit整数域／14bit输出和camera_apply_allowed=False，PC补偿和成对经验响应也没有授予本CP照片四组件资格。只核相关段落／文件，未遍历全部训练和历史总结；对方已有转换工具和算法，不能把旧路径404说成算法缺失。已核的新来源没有补出本项目上述两函数，缺失输入结论仍成立。

### 完整配方传输仍是实际缺口

[传输审计](../../../.local/fixed-custom-filters/continuation36-lut-transport/report.md)确认UI、AP发送、wire和CP验证四层都拒kind1。现128B包只传基底／八值，没有1943B AJR1及按版本的提交ACK；原CP消息在处理后释放，不能跨任务借包内指针。新RW／phase后余量924B，单份1943B也放不下，必须另证原heap拥有权、接收和解码预算，再与同次配方／C4提交一起实现。没有用“放开kind开关”或额外包指针伪装完整传输。

### 原队列串行不等于输入稳定

[原拥有者专项](../../../.local/fixed-custom-filters/continuation36-cp-owner/README.md)确认原worker逐条同步处理28B消息，但其C4借用的大输入会在颜色pending判断前被刷新。因此把排队A版本附在消息上，仍可能对应稍后读到的B内容，不能作为实际成像版本。

已定位raw临时恢复共同出口2310de，必须完整覆盖10B，8B会截断指令；原packer返回太早，缓存命中也不经过packer。这提供一条复用原packed资源管理的更小方案，但仍须先证明源替换与消费的共同同步、其他C4分支及同grid_state无并发改写，当前没有安装此gate或新增空租约框架。原任务完成回调和pending清零也不等于图像完成，提交失败同样可能清pending。

## 当前交付边界

本批完成T07e3中的输入版本子范围及T07e的UI发送器登记子范围，父项保持未完成；T08b2d4／T08b2d5因上述颜色输入与真实消费者缺口保持未完成，T04b2／T09／T10／T11／T12也不标为完成。原六槽个人参数继承、机内真实容量／换卡重启／掉电、EVF／JPG与最终资源仍须各自验收。

没有操作相机、USB／SSH／SD，没有恢复硬件模拟、读取私钥、生成DAT或刷写。此结论是本轮实际无法全量完成的原因，不把更多宿主测试或准备镜像当作完整功能交付。
