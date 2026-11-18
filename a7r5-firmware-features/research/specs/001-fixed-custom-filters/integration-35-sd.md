# 第35批：双卡选择、中文文件名与打包准备

本批实际完成双卡选择器、原生选卡服务与导入入口、UTF-8文件名资格核验，以及长文件名的默认滤镜名生成。当前代码283项宿主回归通过，启动绑定另13项通过，交叉编译链接及新未签名USR准备镜像均通过。没有操作相机、访问实际SD、恢复硬件模拟或生成可安装DAT。整体仍为`NOT_VERIFIED`。

## 已接通的操作

原管理页“导入”在绑定原生选卡服务后，进入“取消／SD卡1／SD卡2”原D4选择页。只有原确认关闭点的真实ENTER许可可提交选择，方向移动不执行选卡。返回原Main后才调用选卡服务，再扫描并进入既有文件浏览、目标槽确认与导入任务。显式目录fd后端沿用原流程。

取消、父页错误、禁用、服务忙及选卡失败均不扫描新卡、不创建导入任务、不改槽内容；失败返回原管理页并保留真实错误状态。导入转换仍要求合格完整模型，浏览成功不会报告导入成功。

这4个新增管理身份为1664～1667，原源表不存在冲突；它们不增加创意外观总数。固定12原厂＋20用户槽、原0x690的隔离及旧六槽委派保持。短名称资源使用私有7fd0文字令牌，避开既有用户名称命名空间。

## 具体改动

| 落点 | 行为与约束 |
|---|---|
| [af_ap_cards.c](../../custom-filters/native/af_ap_cards.c)／[头文件](../../custom-filters/native/af_ap_cards.h) | 原D4模板、默认取消、原树冲突检查、同代一次性选择、过期令牌与显示文本；无文件I/O |
| [af_ap_ui.c](../../custom-filters/native/af_ap_ui.c)／[af_ap_names.c](../../custom-filters/native/af_ap_names.c) | 复用原确认／离页生命周期和名称路由，Main后才切卡扫描；不增加AP挂钩 |
| [af_ap_media.c](../../custom-filters/native/af_ap_media.c)／[头文件](../../custom-filters/native/af_ap_media.h) | 驻留选卡服务、活动任务及重入忙保护、成功后更新当前卡；失败保持旧提供者 |
| [af_fsys406.c](../../custom-filters/native/af_fsys406.c)／[头文件](../../custom-filters/native/af_fsys406.h) | 严格UTF-8路径验证；操作前后核同包原转换器，不修改系统编码。未提供策略的旧调用方仍限ASCII |
| [af_repository_service.c](../../custom-filters/native/af_repository_service.c) | 完整验证最多127字节源名称；默认滤镜名超过63字节时在UTF-8边界取最多60字节并加`...`，实际源路径和浏览名称保持完整 |
| [af_bootstrap406.c](../../custom-filters/experiments/packaging406/loader/af_bootstrap406.c)／[build_loader.py](../../custom-filters/experiments/packaging406/loader/build_loader.py) | 绑定选卡回调和UTF-8资格，固定同一DSO基址／驻留；补齐选择器原先遗漏的IMPORT和EXPORT能力位；首次init不执行编码检查 |

## 中文路径的依据

同包`libInfraFsys.so`全文SHA为`1986525ba65519a00ee5f41fbf40d2651bfcccb518bbb1e7e8e7fc0a58db7c5b`。原Find的长名输出经UTF-16→UTF-8；Open使用mode1，经FAT／exFAT路径比较转回UTF-16。原双向转换器包含合法非BMP的代理对处理，并非仅凭宿主替身开放四字节字符。

loader固定原两个LOAD及完整虚拟跨度0x1606e8，每次实际解引用前重读映射，核8个代码窗口RX、GOT b9e68的8字节可读、module d4418的0x48字节RW，再核原初始化标志和6个转换器指针。没有以708568字节文件大小代替虚拟范围，也不声称遍历了整个60350字节模块。模块handle保持驻留，后续不同基址被拒绝。

适配器拒绝非法／过长UTF-8、代理项、C0／C1控制、分隔符、通配符和越界名称。原宽容转换器会将坏序列换成下划线，故必须在实际打开前拒绝，避免读到另一个名称。保存显示名称和源文件路径的字节预算分开。

原静态窗口、运行期读集及逐项变造拒绝证据见[UTF-8冻结回执](../../../.local/fixed-custom-filters/continuation35-fsys-encoding/freeze.json)。这些是源像分析与宿主边界验证，未执行真实Fsys或原菜单呈现器。原字体的最终字形显示仍待画面验收；接受合法四字节文件名不等于原字体支持所有符号。本批不承诺机内键盘可输入中文，也未改变其原有限制。

## 实际验证与产物

| 证据 | 已观察结果 | 不包含的验收 |
|---|---|---|
| [统一构建](../../../.local/fixed-custom-filters/continuation35-dates-software/verification.json) | 283 passed in39.57s；当前native／测试及编码fixture摘要无漂移；动态／固定AP、仓库、AP／CP请求和原生适配目标编译链接通过 | 不执行目标、模拟器或设备；不是当前画面和像素证据 |
| [媒体与映射](../../../.local/fixed-custom-filters/continuation35-dates-integration/loader-media.json)／[启动与存储](../../../.local/fixed-custom-filters/continuation35-dates-integration/loader-host.json) | 6项0.89秒＋7项1.96秒通过；每次先核映射、半绑定及基址变化拒绝；默认关闭、父fd驻留、真实临时文件COW逆补丁通过 | 动态服务与原系统路径由宿主边界替换，不代表实际选卡／掉电 |
| [AP预检](../../../.local/fixed-custom-filters/continuation35-dates-package/verification.json)／[启动库](../../../.local/fixed-custom-filters/continuation35-dates-loader/verification.json) | 132原前像／57研究挂钩；发布仍56项，排除原登记BL。启动库79736字节，SHA`8154453e62d086970f4aa4125418daff1ed6911a2bd943b1f77981548d448305` | 产品准入生产者未闭合，publish仍BUSY；CP安装门禁未启用 |
| [准备清单](../../../.local/fixed-custom-filters/continuation35-dates-integration/staging-input.json)／[镜像内容](../../../.local/fixed-custom-filters/continuation35-full-unsigned-usr-v2/verification.json)／[独立回读](../../../.local/fixed-custom-filters/continuation35-dates-integration/image-readback.json) | 7AP窗口＋70资源＋4DSO；410652672字节；1043原项及无关元数据保持，新增后1047项；e2fsck退出0。实际文件SHA`eece30774fa1f967c5ca65a996a0c80843b052f6ceba71f18526718f2920c422`；独立回读全部组件及逆7窗口回原AP | CP不变、UI未发布、未签名／无DAT／不可安装；机内保存与取景JPG不能以ext2检查代替 |

实际准备镜像：[UNINSTALLABLE-unsigned-USR.ext2](../../../.local/fixed-custom-filters/continuation35-full-unsigned-usr-v2/UNINSTALLABLE-unsigned-USR.ext2)。原修改版4.06的DAT、CPIO和USR仍按原完整摘要保持，前批v3及本批首版均保留，当前交付为日期修正v2。44项UTF-8及各模块定向测试已纳入283项，不重复累加为额外验收；6项loader抽取契约的实际依赖源未变，按摘要复用首版结果，7项包含真实Fsys实现的启动宿主测试已重新执行。

## 访问日期误判的实际修复

同包原Read在读回字节非零、volume标志允许时可更新文件拥有者的访问日期、时间和UTC。原Find结果中的对应范围精确为`0x18..0x19`和`0x22..0x25`；`0x20..0x21`是原更新10ms，必须保留。Root独立读取原`40510`、`67c8c`及`7bc08`窗口后才实施，没有沿用早期口述的错误偏移。

原实现比较全部22字节，会在合法访问字段改变时返回STALE。新增独立契约先实际复现1失败／1通过，修复后2项通过：只排除上述6字节的比较，缓存仍保留原22字节；其余16个日期字节逐个变化均拒绝并保持输出元数据未发布。大小、名称、属性、卡快照、两遍内容及首末SHA保护仍保持。没有断言任何具体物理卡当前设置或每次Close必然持久化访问日期。

原字段映射与6个指令窗口见[更正后的日期证据](../../../.local/fixed-custom-filters/continuation35-fsys-encoding/date-followup.json)，复现和定向修复见[失败回执](../../../.local/fixed-custom-filters/continuation35-dates-integration/red.json)／[通过回执](../../../.local/fixed-custom-filters/continuation35-dates-integration/green.json)。随后283项完整相关回归、目标链接、启动宿主及新v2准备镜像已重新通过；相对本批首版只有启动库的实际组件字节改变。

## CP接入的新增证据与阻塞

[同版原网格入口报告](../../../.local/fixed-custom-filters/continuation35-cp-source/README.md)已定位私有选择器`bef550`，其原fallback及成功`bef578→230f10`可保留；从此尾入口可到新RX，不能从过远的原230f0c直接跳转。原415160→25df9c是物理记录分类，保留其实际查询不需要硬件模拟。

原1215字节网格存在两条同步打包读取，但返回后state+184仍保留原始源，下次失效可重包。230d1c释放的是packed资源，不能作为raw源最后引用。原ARM `5ef69c/5ef73c`提供真实heap分配／释放，解决空间来源，但不能决定安全释放时刻。原`240de2 STRD`保存C4，已更正旧注释把该写入误标成240dde的问题，未改运行逻辑。

后续[同次C4与银行来源报告](../../../.local/fixed-custom-filters/continuation35-cp-binding/README.md)进一步证明原快照经`164eef0→1653c68→C4 192b070→C4副本1214e98→原任务71965a→23091c`。双银行`1efb7d0/1efd1a8`由原代码明确生成，原reset会清raw指针，但packed释放不会清raw。22窄窗口及28指令静态复核通过。

确切缺口是：当前私有prepare不接收版本，快照只覆盖九字段，私有版本留在另一全局变量，不能沿上述副本和异步任务传播；原任务串行／排空及其他C4路径的全部持有者退出也未证明。另须闭合最终Gamma／矩阵／CC1／网格的同版组合消费与适用sRGB域。原packer返回、PREPARED消息和相同参数值均不能替代这些证据。本批没有安装空gate、默认成功回执或新的通用租约框架。

因此M1～M4、T05／T07／T08／T09／T10／T11仍未全部完成。旧六完整迁移、真实机内容量／换卡重启／掉电、实际EVF／JPG及最后图像帧仍待验收，T12保持当前未授权。最终源像、当前产物与文档边界由本批V0审计另记。
