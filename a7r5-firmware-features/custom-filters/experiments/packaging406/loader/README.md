# 4.06 启动装载准备

第36批当前结果见[核心实施与阻塞](../../../../specs/001-fixed-custom-filters/integration-36-core.md)：新增成像provider仅登记驻留元数据，由原refresh在真实HELLO后一次绑定，未启用两处原消息gate或admission。当前289项相关宿主及目标链接、新80464B启动库和未签名USR准备通过；下述第35批命令／摘要保留历史身份，不将其全源码快照误用于本批接口修改。

本目录使用同包 Linux／glibc 2.25。AP 原 RX 末页内有两段 PIC 垫片，共796字节（晚入口396、早入口400），范围`500fc70..500ff8c`，不增加页面。早入口经原`dlopen`／`dlsym`调用`af_bootstrap406_early`，晚入口调用`af_bootstrap406`。

早入口替换`.init_array[104]`指针及既有RELATIVE加数，校验文件COW逆7补丁、实际映射和registry重定位目的地，只安装登记观察，随后尾调原构造器一次。观察先委派原登记，再记录5591项完成；不读取尚未初始化的树内容。错范围、重复、重入或陈旧计数均拒绝回执。

晚入口先恢复自己的初始化首字和登记BL，再消费自然回执，验证70份资源及同包Obj，装载UI／requests、复制文件段、保留零初始化BSS、应用RELATIVE、填写四个单B返回口、刷新缓存和恢复权限，最后核对132项原前像。首次恢复RX失败会回滚原指令并再恢复；两次都失败时明确硬停，不能把NX页当作仍能继续原初始化。

文件计划只含现有4.06与bootstrap的7个固定窗口，不默认合入另一任务的37个aspect补丁。`af_ap_after_original_registration`只追加14个新身份，不重放原5591项范围；其调用仍放在产品发布阶段。

**准备成功不发布功能。** `af_bootstrap406_publish()`缺完整准入生产者，默认始终BUSY，不发布32槽、菜单或成像能力。未来准入后的UI挂钩为56项，排除已完成的构造器BL；57项研究声明及132项原前像保持兼容。实际启动、CP配对装载和完整模型仍不能以宿主测试代替。

`af_storage406_open`已链接进启动库，只读检查精确`/setting`挂载、设备身份、目录权限和容量，成功才返回fd。`af_bootstrap406_bind_native_storage(library)`在产品未发布时直接BUSY；获准后才检查并交给既有仓库，不回退目录、不改变权限、不格式化或迁移。显式父fd接口仍保留。原生body绑定成功后准备slot0的原Fsys提供者和导入服务，真正scan延后至原UI确认；媒体失败另行记录，不撤销body成功。第35批已接原D4双卡页，返回Main后才调用选卡服务并扫描。五个导出须通过完整库摘要、同一动态基址、偏移、前像及RX检查；64位文件token不作fd。context和一份4MiB源缓冲驻留，完整模型未绑定仍不得导入成功。详见[最新操作接入](../../../../specs/001-fixed-custom-filters/integration-35-sd.md)。

中文路径使用同包原UTF-8转换器证据；新binding驻留编码资格回调，首次init不检查编码。每次scan/read前后刷新映射，再核8个RX窗口、GOT和module实际读区及6个转换器指针，原DSO不卸载，基址改变拒绝。编译器固定两个原LOAD和0x1606e8虚拟跨度，不使用文件708568B作为映射范围。不改codepage；旧无策略调用方保留ASCII限制。选择器补齐IMPORT／EXPORT能力位，但原服务和完整模型资格仍独立决定动作是否可用。

当前v2同时修复原只读Read更新访问日期造成的误STALE：稳定比较仅排除Find结果0x18..0x19及0x22..0x25，保留原缓存、0x20..0x21更新10ms及全部其他保护。新日期契约先复现失败后通过；没有据此推断任意物理卡的实际Close／持久化策略。

交叉链接命令：

```sh
PYTHONPATH=a7r5-desktop/prepared/engine/site .venv/bin/python -B \
  a7r5-firmware-features/custom-filters/experiments/packaging406/loader/build_loader.py \
  --preflight .local/fixed-custom-filters/continuation35-dates-package/verification.json \
  --software .local/fixed-custom-filters/continuation35-dates-software/verification.json \
  --output .local/fixed-custom-filters/continuation35-dates-loader-next
```

输出须为全新目录。当前`continuation35-dates-loader`链接通过，DSO79736字节，SHA-256 `8154453e62d086970f4aa4125418daff1ed6911a2bd943b1f77981548d448305`。依赖仅同包`libdl.so.2`、`libc.so.6`和`ld-linux-aarch64.so.1`，未执行目标文件。

宿主定向命令：

```sh
AF_BOOTSTRAP_PREFLIGHT=.local/fixed-custom-filters/continuation35-dates-package/verification.json \
AF_BOOTSTRAP_BUILD=.local/fixed-custom-filters/continuation35-dates-loader \
PYTHONPATH=a7r5-desktop/prepared/engine/site .venv/bin/python -B -m pytest -q -p no:cacheprovider \
  a7r5-firmware-features/custom-filters/experiments/packaging406/loader/test_loader_identity.py
```

当前统一软件回归283项通过；父fd驻留与媒体失败独立回执、默认关闭及文件COW共7项另行通过，媒体绑定及UTF-8读区映射另6项通过。COW逐字逆转7窗口回原AP摘要，候选文件保持；篡改拒绝，发布及native-storage默认BUSY。资格测试只使用临时目录和测试元数据，不访问真实`/setting`、设备节点或运行期`/proc`。

本次新未签名USR含7个AP窗口、70份资源和4个DSO，原1043项inode／无关内容保持，新增后1047项，独立e2fsck退出0；实际文件及全部组件回读通过，SHA-256 `eece30774fa1f967c5ca65a996a0c80843b052f6ceba71f18526718f2920c422`。它不含CP更新，不能安装；CP实际装载与发布、完整sRGB／非零网格模型与原生消费、全部模式退出、原SD服务的实际调用／热拔卡和旧六槽继承仍须接通及验证。旧v2／v3保留，不覆盖历史产物。

没有运行 QEMU／Unicorn／硬件模拟，没有连接相机，没有访问实际 SD、Backup 或私钥。生成的 DSO 和70项资源可供独立未签名 USR staging；它们不是可安装固件。
