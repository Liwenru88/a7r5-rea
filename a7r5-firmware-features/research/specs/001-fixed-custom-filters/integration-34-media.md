# 原厂 SD 服务与导入事务接线

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-30`
- Overall status: `NOT_VERIFIED`

仍以现有修改版4.06为唯一输入，不改DAT、原USR或CPIO，不访问相机、实际SD、USB、SSH、私钥或实际`/setting`，不运行目标指令、QEMU或硬件模型。本页记录真实接口对应的代码接线及宿主验证，不能解释为相机实测。

## 卡槽快照与原文件服务

[af_media_snapshot406.c](../../custom-filters/native/af_media_snapshot406.c)按原模型锁`2e7d208`→getter`28a3b60`→复制`0x150`→解锁`2e7cee4`工作，getter必须返回`base+7f0cf00`。固定AP完整来源和映射由外层先核验，函数再检查getter20B与两锁各16B前像。失败保持输出，错误getter仍解锁，不向外泄露原全局指针。副本含3×0x70记录，仅索引0/1已有物理卡槽语义。必须由原UI模型已就绪的同一线程调用，不用全零内存伪造就绪。

[af_fsys406.c](../../custom-filters/native/af_fsys406.c)复用同包`libInfraFsys.so`的`Fsys_Open/Read/Close/FindFirst/FindNext`。文件token保持完整64位；Find结果为原0xc28私有游标，每次调用释放原服务锁，没有虚构FindClose。类型3使用`/Private/Sony/PRO/LUT`，类型9使用`/Sony/PRO/LUT`；这是原生卷内路径，不是Linux挂载目录。

列表最多64个文件、检查4096目录项；原生条目的device/inode/mtime字段为0，表示不适用，不产生伪POSIX身份或物理换卡代号。提供者私有缓存选槽完整记录、原Find日期/属性和同代完整列表。每次读取前后重核快照与精确Find信息，两次独立Open/Read/Close逐字节复核，并比较首遍及末次进度回调后的SHA。负读数、超请求读数、短EOF、关闭失败、列表/卡槽变化、取消和源缓冲变化均不发布读取成功。

当前仅接受安全ASCII的`.cube`文件名，拒绝路径、通配符和未证编码。中文滤镜名称沿用既有名称模块；不能据此承诺中文SD文件名。卡模型快照一致与原Fsys的活动token核验不能代替真实热拔卡或ABA场景的设备验收。

## 浏览、转换与机内保存

`AfMediaProvider`与原目录fd后端并存；[af_ap_media.c](../../custom-filters/native/af_ap_media.c)将原生context传给浏览和显式导入器，[af_repository_service.c](../../custom-filters/native/af_repository_service.c)复制同代选择、摘要和函数表，任务再复制一次绑定并重新读取。原生输入的directory必须为-1；从不将Fsys句柄缩窄为fd。

提供者、函数和源缓冲由同一UI拥有者保持到任务结束；浏览或实际转换期间重绑拒绝。两种导入器都拒绝context起始字节落入源缓冲；重绑也在调用cancel前核对新缓冲与既有context。完整context的大小和外部寿命仍由可信调用者负责，不猜其布局。

机内body仓库继续使用独立父fd及既有双副本事务。原生body绑定成功后，启动库准备slot0提供者，原UI确认才开始扫描；另有显式slot1重绑接口，尚未增加双卡选择界面。库文件完整摘要、五个导出的动态库归属/偏移、前像及RX权限均须核对。两个卡槽context及一份4MiB源缓冲驻留，8MiB是两遍文件I/O上限。媒体绑定失败不改变body已绑定的成功回执；部分媒体绑定失败也不能用后续重绑伪装成功。

只有完整颜色模型显式绑定后，才可从稳定读取进入目标槽、转换及持久化。当前没有默认替代模型；READ_READY不是Imported，文件保存不是取景/JPG完成。产品发布准入仍关闭，所以新增绑定代码不构成实际启动证据。

## 验证与产物

原快照有ASAN/UBSAN锁顺序、输出独立、坏前像及错误getter测试；Fsys有19项宿主边界测试，另有原生提供者到真实临时目录转换/保存/重开的集成测试。复核发现的进度回调改源及context别名均先复现再修复。统一构建240项宿主回归（33.81秒）、7项启动库定向检查（1.84秒）及AArch64／ARM交叉链接通过。当前动态UI116704B，repo112160B，启动库74488B。旧USR v2仍按其冻结组件核验，不称其包含本次媒体代码。

## 尚未关闭的产品条件

完整照片sRGB四组件前向模型和AJR1到原CP消费、AP/CP启动会话准入、EVF/JPG同次版本和最后帧、原六槽无损迁移及实际持久化仍未闭环。新SD适配解决文件入口，不能代替这些条件；不生成或宣称可安装DAT。

## 当前冻结产物

- [软件回归与目标构建](../../../.local/fixed-custom-filters/continuation34-media-software/verification.json)：240 passed，代码未漂移。
- [AP前像与ASLR合成](../../../.local/fixed-custom-filters/continuation34-media-package/verification.json)：132前像、57研究挂钩；生产发布排除原登记观察BL。
- [真实启动库](../../../.local/fixed-custom-filters/continuation34-media-loader/verification.json)：74488B，SHA `6e54f91deaec91d036ff021dae34e0e2d8e3110e53e2a1397cde406c6144c390`。
- [启动库宿主边界](../../../.local/fixed-custom-filters/continuation34-integration/media-loader-host.json)：7 passed，实际文件私有COW逆7窗口，默认不发布，body与媒体回执分离。
- [未签名USR v3](../../../.local/fixed-custom-filters/continuation34-full-unsigned-usr-v3/verification.json)：410652672B，SHA `b503cc6c499b097f80d267c3cf65eb059c948d04e57ecceba6125da8413ee661`；7AP窗口、70资源、4DSO，原1043项inode保持，新增后1047项，e2fsck0。CP未变、UI不发布、不可安装。
- [当前CP成对回执](../../../.local/fixed-custom-filters/continuation34-cp-bootstrap-final-v4/verification.json)、[内存往返](../../../.local/fixed-custom-filters/continuation34-cp-memory-final-v4/verification.json)与[五组宿主边界](../../../.local/fixed-custom-filters/continuation34-cp-host-final-v4/verification.json)：当前头文件重新绑定；RX3204、引导408B、CRC `e20078b4`，旧六源及前缀保持，9窗口完全逆转，未写CP文件。
