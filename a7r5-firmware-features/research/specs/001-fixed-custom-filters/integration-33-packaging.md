# 第三十三批：快照顺序修复与打包接线

- 输入：既有修改版4.06，DAT SHA-256 `3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2`。
- 状态：`UNSIGNED_USR_STAGED_NOT_INSTALLABLE`。本批未操作相机、真实SD、签名私钥或硬件模拟器，未修改输入DAT。
- 范围：继续既定32槽和四组件目标，不把软件归档标为完整固件。

## 原厂消息与私有预设分开保存

`native/af_cp_override406.*`由原0x24互斥保护独立纯参数对象。原九条消息仍写原`0x157aa10`，私有PRESET不再覆盖这些原状态。新挂钩位于原`0x89856c`：成功加锁且完成`memcpy(dst,0x157aa10,0xdbc)`后，仅改目的副本的基底和八值，然后回放原两条MOVW/MOVT，返回`0x898575`继续原结构转移、解锁和后处理。

挂钩前像8字节为`4bf2d070c0f25710`。最终gate地址必须从最终ELF取得，不能照抄研究映射`0x92000000`。就绪检查比较整个118字节原函数（只允许这8字节变化），并探测原锁；未安装、锁忙或失败时不协商新能力。代码编译成功不会自动安装挂钩。

用户槽持续覆盖快照；slot0完整原厂快照暂时覆盖，原九值追齐才退出。私有处理不写回原厂FL2/FL3及旧六槽数据。`FactoryPending`不是消息队列排空或照片完成证明。

## 明确退出及连续事件修复

继续既有128字节A7P1，新增独立能力`0x20000`与`operation=3 NATIVE`。NATIVE要求空预设、slot0、非零版本，与PRESET共用会话和单调版本序列；不增加第14个消费者。旧端拒绝新能力，CP在原快照gate未就绪时拒绝配置此能力。AP界面绑定版本升为2，要求完整factory和snapshot-overlay能力及退出回调；默认无绑定。

独立审查实际复现并修复两处原厂回退滞留：

1. C07→FL2的完整PRESET刚发送后立即选FL3，原实现提前清除`requested`，CP可能永久覆盖FL2。现在factory发送后保留状态，后续原厂事件继续更新完整pending。
2. 回到原厂后立即调参，原厂工作值已经变动，旧pending无法追齐。现在原厂八项步进、直接赋值事件、重置、基底切换明确退出覆盖，沿原状态继续消费。其他直接事件的原返回值保持。

旧失败见[审查反例](../../../.local/fixed-custom-filters/continuation33-review/factory-pending-receipt.json)；实际UI C与CP覆盖叶联合回归覆盖连续切换、步进、直接赋值、非赋值事件、重置和基底切换。显示／getter／刷新不承担自动重发。全部实际模式切换和CP成像回执仍未关闭。

## 网格原表接入的限定实现

`native/af_grid406_source.*`校验完整AJR1及其摘要，按同次C4/root身份深拷贝配方，并核对实际驻留1215字节网格源。`operation=*root`的`+4`保存C4，`grid_state=*(pipe+8)`的`+4`却是source_class；两个对象严格分开，不能混用。

当前仅适配有依据的mode0/profile0/index0，写原`grid_state+0x184/+0x188/+0x189`及缓存`context+0x54`，其他字节保持。原查询分类不是银行index；查询缺失、未知域、陈旧身份、同地址内容替换及输出别名拒绝。原选择器与`0x230f0c`分派仍须成对接通，本批叶适配未安装它们。

原packer返回后仍保留1215源指针；结束本次token不能释放原表。真正clone伴随身份、原选择器替换旧引用及最后重包条件仍待接线。未借用旧六marker，未注册完整sRGB模型；两个参考项目的临时PC网格方程不能授予本机像素语义。具体源指令和不可替代的域证据见[网格边界](../../../.local/continuation33-color/README.md)。

## 已执行验证

命令：

```sh
.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/software31/verify.py --output .local/fixed-custom-filters/continuation33-software
```

[统一回执](../../../.local/fixed-custom-filters/continuation33-software/verification.json)：**202 passed in 28.02s**，源码无漂移；动态／固定UI、AArch64/glibc2.25文件后端及AP/ARMv7配对模块编译链接通过。CP使用软浮点并禁自动向量化，避免快照窄挂钩引入未保存的浮点寄存器写入。原锁及gate只作静态来源核对，不执行目标指令。

| 产物 | 字节 | SHA-256 |
|---|---:|---|
| 动态UI | 112352 | `a26a96f97552e260443d3f5e8790f9fd0f6f518734645595aaa1cb3a3fee571b` |
| 固定研究UI | 152392 | `9971581566138426d996f4d9996a51cd62ce34cbaf5353d1ad828ba484424933` |
| 仓库后端 | 110832 | `27efd4d74bd49147114eee7d2f0fa3daa764fffbc2fd6918bea24f7d208d43ce` |
| 固定研究AP请求 | 82632 | `3e4a18664a4f0948e9fd191e2ca09ba7a576b117a0861b26214f19b4f866094b` |
| 固定研究CP请求 | 76536 | `410c569ee92083a4b6da90604627c27f5cbbbbef1345c73e2d9d3b9db907cf9a` |

这些ELF不是已装入相机的模块。仓库产物与上一批逐字相同，可复用未变更的文件事务证据；不重新声称真实机内耐久通过。

## 打包仍须满足

1. 实际启动bootstrap、非零AP导入与模块映射、原入口恢复及缓存／权限顺序。
2. CP载荷真实装载、可执行位置所有权和原快照挂钩安装，全部模式退出与原消费者关联。
3. 四组件同次C4实际应用、完整sRGB／非零网格模型和可复算误差；当前不能自动启用LUT导入成像。
4. 真实持久化父目录／SD目录来源、旧六槽完整继承；普通目录及USR镜像空闲空间不是机内运行位置证据。
5. 更新容器成员、继承资源与反向还原审计。新增DSO是本地镜像打包实现事项，不把尚未实现误称外部限制；最终签名和设备验收仍保持授权边界。

## 新增实际打包能力与准备镜像

`experiments/packaging406/`和`native/af_ap_requests_binding.*`新增以下实际实现：

- AP请求模块已改为ET_DYN，11项原函数经已核对的AP基址绑定，四个保存全状态的返回出口使用实际单B。产物26888字节，SHA-256 `8c7f3db5c85fb40bea3a45db05c3e8b923e75919c72762ac0d2b8b597eea3e00`。两种非零布局、132前像、57UI挂钩及组合冲突检查通过。
- 原RX末页放396字节PIC启动垫片，仅占`0x500fc70..0x500fdfc`；AP文件仍为97368304字节，不新增页。4个文件补丁只改本任务启动入口、垫片和两项RX长度字段，目标AP SHA为`fd5c151d32f90b4f2f6c052b0fb3b73cba07167719fa0ab5530c05e6c1f8fa3b`。aspect仅作兼容冲突对照，不自动加入其37个窗口。
- `loader/af_bootstrap406.*`实现Linux/glibc2.25准备：私有COW映射逆补丁验证原AP身份、恢复自己持有的RAM入口、mmap加载UI及请求模块、RELATIVE重定位、W^X和缓存处理、四返回出口与绑定。51,384字节DSO的SHA为`f2dff3b1a71a881e526d5e3f7eba185b6361be1d1f1a9cfa6de857a765f16888`；链接通过，实际宿主COW／坏文件拒绝／默认关闭测试通过。真实原注册时序未成立，因此不手调原注册器，不装57挂钩，不发布32槽／CP／存储，publish明确BUSY。
- `a7r5-dat-tool/a7r5dat/ext2_add.py`向新派生USR增加明确命名的DSO，13项定向测试通过；只用新inode，独立核对原文件、符号链接、inode、ACL、间接表和非目标目录字节。
- `ext2_image_append.py`仅放行同4.06的两项实际资源`image_00_23_IPSX.uxc`和`image_00_32_IPSX.uxc`，保留原inode及全部旧数据块地址。各增长78,764字节，4项间接块／分配失败测试通过；原图标前像、目标摘要及实际派生完整核验通过。不是假定的horizontal/vertical文件名。

完整串行命令：

```sh
PYTHONPATH=a7r5-desktop/prepared/engine/site .venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/packaging406/stage_unsigned_usr.py --manifest .local/fixed-custom-filters/continuation33-package/loader-staging-input-v1.json --manifest-sha256 1236a1a4a551d8cc6168c1db2bcd58eb8747d7e26a4cf722869c3b70a8384856 --output .local/fixed-custom-filters/continuation33-full-unsigned-usr-v2
```

[最终内容回执](../../../.local/fixed-custom-filters/continuation33-full-unsigned-usr-v2/verification.json)及[e2fsck完整输出](../../../.local/fixed-custom-filters/continuation33-full-unsigned-usr-v2/e2fsck.json)：派生USR为410652672字节，SHA-256 `3b53450ded1f228352f8f3fc17594037559220c5b4fc9f7fc422334786a86b92`；70份资源、4个AP补丁窗口、4个DSO全部回读；原1043项inode及无关内容／属性保持，仅新增4项；`e2fsck -f -n`退出0。

清单摘要与解析使用同一字节快照；内容回执先写入并同步，镜像以无覆盖硬链接最后发布，回执自身不单独宣称镜像存在。脚本返回`image_published=True`，最终V0另核实际文件摘要。第一版有效内容镜像保留；独立审查发现“镜像先发布而回执可能写失败”窗口，修复后重新运行得到上述v2。真实文件检查是新增集成证据，不将它当作运行相机功能或掉电耐久。

原USR源SHA仍为`f7a23ecdc4d4848a2b4a33398313d8def642bc4a2e9e007c42fb1fa1b48097bf`。虽读取路径位于既有aspect工作区archive，其内容经整分区及AP原像摘要核实属于当前修改4.06；没有换用4.07固件基线。

## 当前真正阻塞

[当前CP放置回执](../../../.local/fixed-custom-filters/continuation33-placement-integrated/placement.json)使用本批`410c569e…cf9a`模块，不沿用上一批大小。当前RX/RO需要**4348字节**，RW段对齐跨度268字节；已有曲线搬迁契约仅明确留下**408字节**RX。真实地址有界链接按预期拒绝。BSS的1216字节只是保持原页表／栈布局的算术上界，并非已分配或可执行内存。未知零区、原六helper、旧Gamma表和研究地址`0x92000000`都不获得放置许可。

因此不能在现有证据下安全安装CP模块。还需要有依据的执行区分配／映射及装载接线，而不是把链接地址改成某个零区。完整sRGB／非零网格预测和同次C4四组件应用也仍缺必要域依据。原注册发布、全部模式退出、媒体及机内目录来源、旧六继承仍未关闭，不能声称只剩真机验收。

本次生成的是明确命名为`UNINSTALLABLE-unsigned-USR.ext2`的准备镜像，**没有最终DAT、签名或安装候选**。M1～M4继续未完成；未为继续打包而放宽上述门槛。
