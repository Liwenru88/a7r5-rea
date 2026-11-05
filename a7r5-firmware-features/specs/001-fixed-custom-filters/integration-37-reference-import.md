# 两参考项目的实际转换和导入实施

日期：2026-10-31。固定修改版4.06基线不变，未操作相机、真实SD或恢复硬件模拟。

## 已接通的AP软件链

本轮已把参考算法从独立研究接口接到实际导入服务：固定公开数值资产装配、可达颜色采样、完整近似预测、17维受约束联合求解、完整AJR1及误差、文件保存恢复、独立发送副本与分片接收。启动器现在在捕获菜单服务能力之前调用默认参考绑定，成功才具有IMPORT能力；失败保留持久化菜单并单独记录转换绑定错误。

这不是完整机身功能已完成：原32槽发布、实际AP/CP消息安装和四组件原生同代应用仍受准入关闭保护。新CP传输模块已链接，但未接到真实handler或原图像消费者；软件提交ACK不能称为照片生效。

## 主要代码

| 模块 | 本轮实际实现 |
|---|---|
| [af_joint_basis](../../custom-filters/native/af_joint_basis.c) | 3项明暗、6项共享矩阵、8项共享色度加网格的整数交替搜索；Gamma从固定seed重建，分批、取消及原子输出 |
| [af_import](../../custom-filters/native/af_import.c) | `AF_JOINT_BASIS406`构建路径使用新求解器，保留完整配方、保存格式及旧构建兼容 |
| [af_reference_assets](../../custom-filters/native/af_reference_assets.c) | 校验并装配377304字节最小固定数值资产，完整参考构表与旧来源逐字节一致 |
| [af_reference_joint](../../custom-filters/native/af_reference_joint.c) | 实际Gamma／矩阵／CC1候选构表和像素消费，零增量校正、原R5网格、来源／上下文身份及研究模型适配 |
| [af_reference_domain](../../custom-filters/native/af_reference_domain.c) | 有来源的上游预览输出解释与有界代表解反求；反解误差真实报告，不作为默认全域映射 |
| [af_reference_samples](../../custom-filters/native/af_reference_samples.c) | 实际原生前向生成可达配对点，schema2精确查询；颜色区域独立分组与代理色组 |
| [af_reference_import](../../custom-filters/native/af_reference_import.c) | 进程内唯一常驻默认ST近似模型、采样／转换工作区和实际IMPORT服务绑定，服务关闭解除借用 |
| [af_bootstrap406](../../custom-filters/experiments/packaging406/loader/af_bootstrap406.c) | 原存储启动在`caps→UI bind`前调用`af_reference_import_bind`；独立reference状态，不硬加能力位 |
| [af_joint_asset](../../custom-filters/native/af_joint_asset.c) | 新增驻留解码工作区，接收路径不在消息栈展开完整1943字节副本和解码对象 |
| [af_recipe_transport](../../custom-filters/native/af_recipe_transport.c) | BEGIN＋26 DATA＋END，全部128字节；完整预设深拷贝、CRC/SHA、版本／会话、软件提交／失败ACK和唯一借用保护 |
| [af_repository_recipe](../../custom-filters/native/af_repository_recipe.c) | 重读并核保存代号／银行／摘要，捕获未保存八值到独立发送对象；不改catalog、dirty或原store |

数值资产及来源在[reference-context4.json](../../custom-filters/assets/reference-context4.json)。它是公开参考软件的数值上下文，不是从当前机身取得的运行快照。

## 域问题的实际解决范围

固定上游`photo_preview.py`明确将原生输出`q/16383`作为sRGB显示；当前采用该明确约定作为参考预览近似，未称为当前机身ICC标定。不能仅因其他输出也是14位就套用该约定。

实测全RGB逆表存在多值代表解和明显插值误差，5³和17³回执均保留在[域来源与数值记录](../../../.local/fixed-custom-filters/implementation37-domain-source/README.md)。默认导入改为：

1. 在明确的原生整数采样范围调用真实参考前向链，得到可达源颜色。
2. 保留源颜色与原生输入的成对关系，去重并排序。
3. 预测只精确查询这些固定点，未知点拒绝，不通过最近点或逆插值伪造输入。
4. 目标是`LUT(source)`；拟合及独立报告均使用完整量化配方。

默认9³原生网格加灰阶／暖色输入代理共859次前向，689个唯一配对点，512训练色及43验证色；验证含5个灰阶代理和9个暖色代理。覆盖45/64个源RGB区域，训练与验证区域不交叉。代理标签不是实拍肤色，有限样本范围不保证所有照片颜色。

此路径不要求整个RGB立方可逆；拍摄也不运行该预测器。默认模型仍是固定ST参考上下文与固定PT经验网格的显式组合近似，其他基底没有因此获得精度保证。模型信息保持`research_only=1`、`camera_apply_allowed=0`，报告是模型内误差。

## 已实际执行的验证

- 受约束求解器、独立端点／共享增量、完整量化输出、分批一致和取消回归。
- 参考域映射及实际参考整数消费者的单组件／混合组件预测；原paired-v2摘要保持，原`af_grid`准入门控不改。
- [同一配方的离线串联](../../custom-filters/tests/test_reference_to_receiver.py)：参考链→CUBE候选→AFD1→真实临时目录仓库→关闭并清空内存／删除输入→新仓库恢复→dirty调参→28帧→接收／软件ACK；载荷逐字节、模型摘要及八值核对。
- [默认服务测试](../../custom-filters/tests/test_reference_default_import.py)：不注入测试预测回调，服务自行装配资产、生成样本并绑定；中文CUBE实际转换／保存，删除源后重新打开恢复。
- [启动绑定测试](../../custom-filters/tests/test_loader_reference_binding.py)：真实抽取函数保持`open→library→reference→caps→UI`；失败／缺旧符号不误报IMPORT。旧存储绑定6项同时通过。
- 软件统一构建覆盖原厂界面、原AP/CP纯参数路径、文件服务、完整新模型及新增传输；最终为370项通过，57.20秒，退出0且构建前后源指纹一致，回执与完整命令见[当前软件验证](../../../.local/fixed-custom-filters/implementation37-delivery-software/verification.json)。仅编译链接目标文件，没有执行ARM、QEMU或Unicorn。
- 实际启动库按当前后端重新构建为80728字节，SHA256为`8e7f789863b713d775da4dc597b18dbaf42d739d4d57c305984b0d12be54bb54`；[加载器构建](../../../.local/fixed-custom-filters/implementation37-delivery-loader/verification.json)成功。身份、存储绑定、媒体绑定及Fsys编码映射的13项宿主检查通过，2.74秒，退出0。

当前后端`libaf_repository_media.so`为572552字节，SHA256为`1e99a97d9887d3092af7bc2eed93377f69992ae11d5e2a67e78840c619e53c79`；动态UI保持126312字节及原摘要。CP研究请求ELF81752字节是普通研究构建，不能据此推断实际私有执行区足够。

原DAT、CPIO和USR输入已重新计算SHA256，分别仍为`3cb87fd4…c24c2`、`c0194822…f1ed80`、`f7a23ecd…097bf`。没有生成或签名可安装DAT，也没有覆盖此前冻结产物。

## 当前未签名USR准备产物

已将本轮后端、启动库及匹配的UI／请求库组合为新的[USR准备镜像](../../../.local/fixed-custom-filters/implementation37-full-unsigned-usr/verification.json)。普通文件大小410652672字节，SHA256为`b38f63718e03d29f5762aa23d7a033f2e074eeaaf87692e1b6ec43f01a1df540`，7个AP启动窗口、70份资源及4个DSO，1043原项扩至1047；原inode与无关元数据保持，独立e2fsck退出0。CP没有更新，UI发布关闭，文件名明确为`UNINSTALLABLE-unsigned-USR.ext2`。

首次冻结正确拒绝旧第36批预检的`af_import.h`来源。随后以当前源码重跑[静态构建／组合预检](../../../.local/fixed-custom-filters/implementation37-package/verification.json)，重新冻结清单后才生成新镜像；未改摘要或放宽来源条件。最终另行重新打开已发布的镜像，逐项核对74个组件及AP七窗口反向还原，见[独立回读](../../../.local/fixed-custom-filters/implementation37-final/image-readback.json)。

## 尚不能安全安装的原生成像部分

[本轮静态接入审计](../../../.local/fixed-custom-filters/implementation37-native-routing/README.md)核对18份来源和7个完整指令窗口，识别出当前包的post-packed候选`719f12 / 8B`或`719f1a / 8B`；打包指针位于`S+20`，有效标记`S+24`。原快照还有独立条件和字段同步，不能照抄另一版root条件。

关键缺口不再是转换器空缺，而是原生身份与寿命：

1. 原源`1653c68`会在pending检查之前被更新。完整配方必须绑定本次真实快照／C4，不能用当前全局选择或排队时版本推断。
2. `719ef6`只同步覆盖CC1／矩阵／网格等；Gamma另经C4→shot→独立请求路径。局部一次view不等于四组件同代。
3. 控制器返回后选择已打包表可避开新raw持有，但packed仍须覆盖在途使用和原厂恢复；消息引用释放不等于图像最后引用。

上游各阶段也会重新acquire配置，不能只依据immutable注释就证明跨阶段一致。当前仍未安全安装上述挂钩，`admission_ready`不变。T03/T07/T08b2d5及T12不能勾选完成，旧六槽迁移和机身介质／取景／JPG验收也仍独立保留。

## 实际CP放置约束

[当前紧凑链接测量](../../../.local/fixed-custom-filters/implementation37-cp-space-v2/verification.json)以真实保留入口链接原CP核心与完整接收器，`-Oz`代码及只读节共7376字节；已核定私有RX区仅4096字节，原容量链接明确失败，超出3280字节。扩大region只用于生成测量ELF，没有获得额外内存。`__aeabi_llsr`及`__aeabi_uidivmod`依赖已通过等价32位编码和有界偏移检查消除，新增独立SHA边界及无helper链接回归；剩下的是空间／布局问题，不是缺运行库。

[参考项目的代码／数据放置审计](../../../.local/implementation37-cp-placement-reference/README.md)进一步确认：对方大数据通过原heap分配，代码固定在`1195270..1197000`并由原mapper映射；这一区域却覆盖本包A7L6和六款旧网格。当前从`1a3b000`扩到7376字节会进入`1a3c000`原L1页表，冷源从`11d2000`线性扩大也会进入旧六款FNV来源。原heap分配器没有授予可执行权限，不能用“分配成功”替代代码页映射证据。

因此本轮没有放宽链接／前像门槛、移动页表或覆盖旧六款。安装继续被阻断；后续需将必需核心压回已核区，或证明独立RX页、冷源、映射／缓存及回退，再补四组件真实快照身份和packed寿命。当前产物为可复核的软件源码与研究构建，未形成完整可安装更新包。
