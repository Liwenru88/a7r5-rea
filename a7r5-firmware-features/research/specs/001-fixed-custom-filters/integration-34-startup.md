# 自然启动、机内父目录和安全装载

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-30`
- Overall status: `NOT_VERIFIED`

本批继续唯一修改版4.06，输入DAT、原USR及CPIO保持。未访问相机、USB、SSH、真实SD、实际`/setting`、设备节点或运行期`/proc`；未执行目标指令或恢复硬件模拟。本文区分已实施代码、宿主行为、交叉链接和仍未成立的真实接入。

## 已实施的接线

### 原厂自然登记

原登记`16f6610→1c91e94`发生在`.init_array[104]`的`16fbfc0→16f6550`构造器内，早于导出`Application_System_Init=17feac0`。构造器先清空原树；从晚入口重放5591项不能代替自然登记。

新增[af_ap_ctor406.S](../../custom-filters/native/af_ap_ctor406.S)与[af_ap_lifecycle.c](../../custom-filters/native/af_ap_lifecycle.c)：早入口只验证身份、映射和原BL，安装观察后尾调原构造器一次；观察回调先委派原登记，返回后才核对5591项并形成单次回执。GOT`5915b80`的原RELATIVE指向`base+7545f20`，早期只检查指针及RW映射，不假定树已初始化。重复、错范围、重入和陈旧计数拒绝回执。

晚入口恢复自身初始化首字及观察BL，再消费回执并准备UI／requests。新增`af_ap_after_original_registration`只追加14个身份，原19行描述符保持，直到未来完整发布准入后才启用32槽。实际发布表排除已完成的构造器BL，56项；57项研究声明和132项原前像保持。

两个垫片共796字节（396＋400），位于原末页`500fc70..500ff8c`，7个文件窗口，不新增页面、不合并其他aspect补丁。实际候选AP摘要`3c588cc1b317774dc58052878e7584d447b99535c05765253a2914d51e313a2d`。写入后第一次RX恢复失败会回滚原opcode并再恢复；再次失败必须硬停，不能声称NX页仍可安全继续。

证据：[冻结自然时序](../../../.local/fixed-custom-filters/continuation34-ap-lifecycle/handoff.md)、[当前AP预检](../../../.local/fixed-custom-filters/continuation34-media-package/verification.json)。当前实际启动未执行，完整准入生产者仍未实现，`publish`默认BUSY。

### 机内存储父目录

新增[af_storage406.c](../../custom-filters/native/af_storage406.c)。同包fstab将`/dev/nflasha2→/setting`列为可写VFAT，只作为候选来源。运行期必须用打开fd的`mnt_id`关联本AP的`mountinfo`，核对root、挂载点、源、类型、rw及设备号；同时检查原uid／目录模式、容量和二次身份。最低可用空间为1,311,071字节。

资格函数只返回fd，不创建文件、不改权限、不扫描其他目录。新增`af_bootstrap406_bind_native_storage`在产品未发布时直接BUSY，获准后才交给既有仓库。独立审查复现发布后关闭parent失败导致“失败但服务已绑定”，现将parent与context成对驻留；无context才关闭，关闭失败也保留并阻止重试，六项原函数抽取回归通过。实际目录权限、空间、VFAT同步和掉电仍未验收，SD原生供应者后续已接入源代码，实际调用仍未验收，见[媒体接线](integration-34-media.md)。

证据：[四组宿主资格与同包glibc链接](../../../.local/continuation34-storage-parent/verification.json)、[驻留回归](../../../.local/fixed-custom-filters/continuation34-integration/storage-binding-green.json)、[最终COW](../../../.local/fixed-custom-filters/continuation34-integration/host-loader-final.json)。测试仅用临时目录和明确元数据替身，不当作机身挂载结果。

### CP紧凑构建与启动重试

[build_cp_compact.py](../../custom-filters/experiments/packaging406/build_cp_compact.py)支持分置试链接、PIC和固定单页合并。原64位变量移位在Oz下引入未提供的helper，已改为两个32位累积，保持2／4／8字节小端语义；独立高位／最大64位包校验保持。

最新状态为RX3204字节、RW272字节；RW载荷显式包含零初始化尾，不能指望原bzero覆盖新增区。拟议页`1a3b000`尚未准入，链接成功不授予所有权或执行许可。

另修复`af_hs_cp406.c`的一次性启动问题：trylock暂忙会让首次start失败、state保持0。现在仅在原消息拥有者收到消息且state=0时重试；普通消息继续委派，已建立session／version／fault不重置。新增宿主回归先红后绿；完整原锁和真实任务时序仍单列。

实际成对模块用原尾快照入口`befb35`作为严格118B预期值，保留周围前像和原trylock；不再错误期待新页直接入口。已新增[CP启动源码与可重复命令](../../custom-filters/experiments/packaging406/cp_bootstrap/README.md)：408B原尾保留完整启动资格／CRC、原extraMap接线、原D＋I缓存及三处原指令回退；RW272＋phase4以BSS声明明确保留，原页表及栈地址保持。

原拟用`11d4000`与旧六槽启动FNV源重叠，已作废；实际源为`11d2000..11d2c84`，原`11d3000..11d4900`及包装器前缀逐字保持，FNV仍`8855bcca`。source prefix排除和phase同页RW前提只针对原完整loader入口，不能解释成任意MMU状态都可安全调用。9处内存补丁与逆转一致、错源拒绝，未写CP文件。 extraMap现同时接受准备和已发布两种非零阶段；只执行阶段2的gate保持。已静态确认正常路径由主核进入原mapper，但未证明所有恢复路径都不会重入，更不将此修复称为并发热unmap安全。

另发现隔离旧源码邻接`image_constants.h`会遮蔽生成头，使目标码仍用旧CRC。旧隔离paired-v2不作为当前配对证据。canonical构建改为在新目录编译精确C／S副本，并直接检查目标码偏移168的literal；故意错误邻接头的回归先红后绿，当前实际CRC与RX均为MSB/init0的`e20078b4`。

证据：[当前成对模块](../../../.local/fixed-custom-filters/continuation34-cp-paired/verification.json)、[目标码绑定](../../../.local/fixed-custom-filters/continuation34-cp-bootstrap-final-v3/verification.json)、[仅内存往返](../../../.local/fixed-custom-filters/continuation34-cp-memory-final-v3/verification.json)、[五组宿主资格](../../../.local/fixed-custom-filters/continuation34-cp-host-final-v3/verification.json)。宿主仅适配MRC、地址和原服务边界，未执行ARM、MMU或cache指令；这些不是实际CP装载或成像证据。

## 未签名组合与当前门槛

打包工具新增schema2，只接纳固定7个AP窗口，错误长度、越界、重复、构造指针和RX边界均拒绝；保留旧4窗口兼容。新增[freeze_staging_manifest.py](../../custom-filters/experiments/packaging406/freeze_staging_manifest.py)，由软件、预检和启动库回执冻结70资源与4个DSO的实际摘要。

第一版34准备镜像已生成，410652672字节，SHA`4c33544b53ce7d6a5e1f1546d6a3b524198ea956a4e7fc18977b9d9a1df18687`；原1043项inode和无关内容保持，新增后1047项，e2fsck退出0。独立审查从实际镜像读回74组件、7窗口及启动库内嵌摘要，全部配对。这是默认关闭的USR准备镜像，不含CP更新，不是可安装DAT。

存储所有权修复后重新构建的最终版本为`continuation34-full-unsigned-usr-v2`，SHA`2300d1805539b6991b8951909801560807d6a1ce8c246e2b532939121e1c9e0e`，e2fsck0；启动库62480B／`e8e612298d02a513d5939c6f7222e263a79caa4a8f1ad5dafbf8090cdbd7d5d0`。当前统一软件回归210项、绑定6项及最终COW1项通过；未变化的schema11项及存储资格复用，不为每条验收重复运行。

当前主要阻塞：

1. CP有界启动源码和永久回退已成对实施，仍缺实际装载、AP通信发布准入、完整启动会话及原映射生命周期执行证据；内存计划不等于已安装。
2. 完整sRGB／非零网格四组件模型、同源C4应用、取景／JPG消费及最终帧仍未闭环。最新参考项目的配方工具仍声明专用Edit输入域和未获相机准入，不能当作当前4.06完整照片模型。
3. 原SD文件接口使用私有Fsys句柄，不能当作POSIX目录fd。已定位关键Find布局和完整64位活动文件token，原模型供应者及读入适配后续已实施；原真实调用、热拔退役及未证编码仍须验证，见媒体接线。
4. 原六槽仍委派原实现，完整继承和全部模式退出未完成。原厂12项包括FL2／FL3继续保护。

T11a只完成限定未签名准备，T11b、M1～M4及总功能保持未完成；T12仍未授权。不能将本批交叉链接、宿主回归或文件系统检查合并成真实启动、照片和介质验收。
