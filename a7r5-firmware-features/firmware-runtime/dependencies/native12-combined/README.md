# 研究版4.11：远端十二滤镜与本地四项整合

本目录已迁入 4.17 主线，保留十二槽基线、固定上游和历史交付。当前固件的构建步骤见 [4.17 实施与复现手册](../../实施与复现手册.md)。

本模块以 [Hearts-Ace 固定4.36提交](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware/tree/47f8f022628aef8de382a613ea4d11cd51d0a965) 为主体，加入本地 FL2／FL3 自包含选择与矩阵、指定 NTSC 提示关闭、限定 type1 的声音选择器及照片标记菜单。按用户要求，当前独立研究版本为`4.11`，纳入中文菜单字体修复；上游基线仍是4.36，不是索尼官方版本或远端原版。

原有 `custom-filters/` 的32槽／机内CUBE工程不进入本包，未修改。没有合入旧六款固定配方或旧4.09图像资源。远端的十二配置BIN、Fn手动注册、原厂静态C.Look图标、R6 ST、白色优先97／氛围−1、冷启动／恢复启动代码保持原有路线。

2026-11-03用户决定维持冷启动导入：冷启动优先导入SD上的有效`R5NATIVE.BIN`并保存机内，卡上无该文件时读取机内；休眠恢复只读机内。[手动热导入候选](../../../specs/007-manual-native12-import/requirements.md)暂不纳入当前版本，未实现、无需回退，也不新增导入菜单。统一入口无独立关闭项，选择ST执行原厂ST逻辑的要求继续保留。

## 菜单修订与配置加载验证

新增私有菜单字体覆盖层`menu-font.c`／`menu_font.py`：按原厂字体属性选择中文或Univers字体，保留当前字号、颜色和排版。4.11封包已纳入该覆盖层，并核对原厂字体库身份。原生窄列对`Portra400`简称的裁切仍未解决，右栏可查看完整全名。

QEMU加载验证入口与模拟边界见[研究入口](../../../../a7r5-qemu/experiments/native12-410-menu/README.md)，字体及加载结果见[菜单修订验证](../../../specs/003-native12-menu-loading-fix/verification.md)。后续[E4调查与修复](../../../specs/004-native12-e4-apply-fix/verification.md)已在明确的菜单隔离场景验证十二款正反切换、原E4完成、持久化及故障回退；完整拍摄初始化和四轮MENU往返仍未通过。旧`releases/4.10/BODYDATA.DAT`及冻结4.11均保持；仅用于QEMU的软件介质与OSAL服务不进入DAT。

新增`e4-menu-compat.c`／`e4_menu_compat.py`修复私有值刷新事件再次提交选项的问题。独立新AP为`65e33ba2075bb59f65a97e6cec550bd8b1d54bac040fe28427cd3922924ffde0`，**尚未封入现有4.11包**，普通`build.py`封包入口也尚未接入该覆盖层。来源、实际截图、完整启动失败现场见[本轮归档](verification/2026-11-02-e4-control/README.md)。不能把菜单隔离通过解释为完整固件稳定或相机可刷。

2026-11-03新增[快速切换回归](verification/2026-11-03-rapid-switch/README.md)：旧4.11的迟到值通知可重复提交、改变请求序列，使下一次连续输入显示失败；独立E4修复候选通过该离线时序用例。当前DAT仍未包含修复，本次未重封包或连接相机；该回放不能替代实机日志确认。

## 当前4.11交付

### 创意外观统一入口开发候选（未封包）

已新增 `unified-look.c`／`unified_look.py` 和 `unified_icons.py`：在原创意外观中保留十九条原记录，追加十二款；撤回独立主菜单和 Fn 候选，扩展选择值与原厂参数模型分离。左列使用 F01～F12 图标，右侧读取 BIN 完整名称并显示事务状态。图标需要配套两份 `image_00_*_IPSX.uxc`，不能只替换 AP。原有32槽工程未修改，存储仍沿用十二款后端。

这仍是未验收开发候选，**不在本节下方的冻结4.11 DAT内，普通 `build.py` 也未接入该覆盖层**。2026-11-03已实现“单笔在途＋最后目标合并”的[快速切换修复](../../../specs/006-unified-look-rapid-switch/verification.md)，不再同步等待或把忙态直接记为失败；QEMU中F12→F11→F10实际跳过F11，显示等待／应用中，失败后四轮菜单开关及ST重入正常。本轮失败终态保留列表，但历史列表消失问题尚未完整验收。

QEMU中的原E4仍受模拟成像初始化缺口阻塞；用户报告实机没有同类初始化问题。当前统一候选十二款实际成功应用、完整恢复／启动生命周期的证据仍未补齐，不能用旧包实测替代新候选验收。当前独立AP为`e833e0290fe60207cc5d9d2b7a0a66b253f7ab0db99ed12afb2a0c47ca6f72f1`，完整整合状态仍见[005阶段记录](../../../specs/005-unified-creative-look/verification.md)，本轮源码／原帧见[修复归档](verification/2026-11-03-unified-rapid/README.md)。

2026-11-03已补齐[冷启动版统一入口离线验证](verification/2026-11-03-unified-cold/README.md)：新增9项真实AP／CP跨层测试覆盖十二款分别返回ST、FL2／FL3、快速切换、重建运行态后的无卡恢复及休眠恢复；真实Qt逐项显示十二款和原厂入口，72原帧逐像素核对通过。CPU的原E4外部执行和原厂UI仍为明确夹具，QEMU实际应用成功、整机重启和实体介质验收未完成。本次未发现新的生产代码问题，没有更改AP／CP或重封DAT。

- [BODYDATA.DAT](releases/4.11/BODYDATA.DAT)、[配套十二款BIN](releases/4.11/R5NATIVE.BIN)。
- [交付说明与已知问题](releases/4.11/README.md)、[校验清单](releases/4.11/SHA256SUMS)、[封包回执](releases/4.11/verification.json)。
- [新旧差异审计](releases/4.11/evidence/411-vs-410.json)：版本字节`11 04`，包内AP与既有QEMU复验组件身份相同，CP、BIN、参数模板、原updater和签名公钥保持。

DAT为754525608字节，SHA256 `71cd3a680834b8559591509dc4dc76e3b1135b1657e22d593d0f7c6687e6cf1d`。封包时实际101项回归、研究签名及OpenSSL、全部736841帧、独立解包、预期明文及USR文件系统检查通过，当时复用同AP／CP的4.10字体客体证据。后续E4新AP的QEMU结果单独归档，未覆盖此冻结包；长简称裁切及实机未验收边界保持。

## 冻结交付

- [完整升级候选 BODYDATA.DAT](releases/4.10/BODYDATA.DAT)：754525608字节。
- [匹配十二滤镜 R5NATIVE.BIN](releases/4.10/R5NATIVE.BIN)：29552字节，上游v4.5成品、BIN结构v4。
- [校验清单](releases/4.10/SHA256SUMS)、[冻结验证回执](releases/4.10/verification.json)、[归档说明](releases/4.10/README.md)。
- [新增运行时离线检查报告](../../../specs/002-native12-combined-firmware/offline-runtime.md)、[最终101项回归回执](verification/2026-11-02-runtime/final-verification.json)。
- [首次4.10的实际QEMU菜单截图](verification/2026-11-02-qemu-menu/README.md)：历史103张客体帧；当时中文显示方框且只有关闭。该失败证据保持，后续修订结果见上节。

冻结4.10 DAT SHA256：`1cc7ec6644c3a86a959341ff95b8904c633f12e8c9e4c6c58a0828568dcd4eb5`。该历史目录及原`.local`下的4.10和首次4.37产物均保留，当前入口见上方4.11。

使用本项目已有研究身份，公钥PEM SHA256为`7f65b296987df665da217de514e785f75238e686ddd18952fa425fc47e8c858a`。原updater逐字节保持；没有使用远端签名身份或其信任安装器。当前机身信任与版本准入未读取，不能把离线验签解释为机身会接纳。私钥不在交付目录中。

## 实际合并方式

1. 188项上游源码锁核对，实际重编AP／CP。AP、CP、三个分区及完整TAR摘要均精确匹配上游冻结输出，之后才合并本地补丁。
2. AP按主选择17／18固定发送19／20，使旧保存基底0也能选择FL2／FL3；六个FL2／FL3默认字段同步。普通十二基底采用远端实际内联映射表，不导入旧六槽路由。三条原调用窗口经CPU验证。
3. CP保留远端已有FL2／FL3选择和内嵌CC1；四档矩阵使用本地2304字节参数。两条原Gamma记录原样搬迁并修正其全部已知对齐引用，腾出的原RX空间放置矩阵与声音代码。受FNV校验的复制器分置于`108f20..108f40`和`108f8c..108fe8`，保留远端`108f40..108f8c`映射器；不移动原全局变量、页表根或栈。
4. NTSC只合入本地两条限定分支。照片标记迁移28支持位、三组登记／RELA和96字节范围包装器；更新远端已搬迁的活动PHDR，不沿用旧AP的`0x60/0x68`写入位置。
5. 包内12份地区参数模板和backup.sum沿用远端配方。三个分区及part_image.sum与上述模板共同形成17个变更成员；其余归档头、成员、原updater保持。模板的更新不等于已经验证机身上的个人设置迁移或保持。

## 复现

在仓库根目录执行。需要固定上游源码、指定官方4.00 DAT，以及现有两套Python3.14环境、LLVM/lld、Apple clang、OpenSSL和e2fsprogs。当前复现环境为macOS arm64；没有安装系统依赖或修改现有虚拟环境。

固定上游现已归档在[upstream](upstream/UPSTREAM_SNAPSHOT.json)，完整保留固定提交的331个已跟踪文件及许可，不含Git元数据或本地缓存。构建器默认使用该快照，检查固定清单摘要、全部文件身份、缺失／额外源及原188项源码锁；也可用`--upstream`指定原有精确Git检出，校验不放宽。重新运行须选择全新的输出目录。

归档结构：

```text
native12-combined/
├── build.py、patches.py、integration.S/.ld、selection.S、menu-font.c、menu_font.py
├── tests/                 功能及归档路径合同
├── upstream/              固定上游源码、滤镜、许可和清单
├── releases/4.11/         当前DAT、BIN、公钥、封包回执及证据
├── releases/4.10/         冻结的历史交付，不包含字体修复
└── build/                 后续复现的本地中间件目录，按需创建
```

```sh
mkdir -p a7r5-firmware-features/native24-combined/dependencies/native12-combined/build

PYTHONPATH="$PWD/a7r5-dat-tool/.venv/lib/python3.14/site-packages" \
  .venv/bin/python -B a7r5-firmware-features/native24-combined/dependencies/native12-combined/build.py \
  --phase baseline \
  --output a7r5-firmware-features/native24-combined/dependencies/native12-combined/build/baseline

PYTHONPATH="$PWD/a7r5-dat-tool/.venv/lib/python3.14/site-packages" \
  .venv/bin/python -B a7r5-firmware-features/native24-combined/dependencies/native12-combined/build.py \
  --phase package \
  --baseline a7r5-firmware-features/native24-combined/dependencies/native12-combined/build/baseline \
  --output a7r5-firmware-features/native24-combined/dependencies/native12-combined/build/411-new
```

默认原厂输入是`a7r5-firmware-images/官方升级包/BODYDATA.DAT`；可通过`--original`提供另一个内容完全相同的普通本地文件。每项原厂输入的大小和摘要必须匹配上游输入锁。原厂4.00 DAT SHA256为`51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2`。

第二阶段自动执行`tests/`下当前全部回归（本轮101项），再封包和独立解包。错误时保留新目录中的`FAILED.json`与现场，不覆盖原始文件或已有结果。本工具没有相机、USB、SSH或卡刷入口；本次实际输入输出均在本机仓库内。

只补验冻结4.10、无需重签时，可使用以下历史入口；该脚本固定4.10，不用于4.11。输出目录必须不存在。它运行全部回归，重新正常验签、逐帧核对、独立完整解包、比较被测组件和12份模板，并执行OpenSSL及e2fsck。无需私钥，不连接设备。

```sh
PYTHONPATH="$PWD/a7r5-dat-tool/.venv/lib/python3.14/site-packages" \
  .venv/bin/python -B a7r5-firmware-features/native24-combined/dependencies/native12-combined/tests/verify_release.py \
  --baseline .local/native12-combined-baseline-01 \
  --output a7r5-firmware-features/native24-combined/dependencies/native12-combined/verification/new-runtime-check
```

`--baseline`需要精确重建的上游基线及其符号／链接审计；也可换成上述`build/baseline`。宿主测试服务的`.c`文件和Python回放一同纳入来源清单。

## 验证与未验收部分

实际通过：17项回归、全部源码／输入摘要、真实AP／CP链接、精确逆还原、上游菜单模块保持、十二款BIN原版解码、USR `e2fsck -fn`退出0、RSA及OpenSSL验签、736841帧、完整明文SHA和独立解包。详细命令和证据见[验证记录](../../../specs/002-native12-combined-firmware/verification.md)。

上述为冻结4.10的封包证据，已随成果归档。此次集中目录另通过22项回归，包含新增快照来源及额外文件／篡改拒绝；DAT、BIN及原回执与来源逐字节相同，没有重封固件。原回执内的绝对路径、版本比较和源指纹是当时历史记录，未改写；当前构建器仅增加归档快照和路径兼容，差异由归档清单与新增证据记录。

2026-11-02随后补齐运行时离线检查：最终101项全部通过。覆盖原启动工作线程、双卡导入与持久化失败、真实AP／CP双CPU通信、选择／原E4回执与回退、Gamma／网格参数消费、菜单／Fn／页面生命周期，以及本地四项补丁。当前DAT另重新通过签名、OpenSSL、736841帧、完整独立解包、12份模板重建比较与e2fsck；实际被测AP／CP和包内组件完全一致。本轮没有复现固件兼容缺陷，仅修复验证来源清单遗漏C服务的问题；不重封或覆盖旧包。详见[覆盖与边界](../../../specs/002-native12-combined-firmware/offline-runtime.md)。

未进行真实相机启动、LCD／EVF／JPG、颜色精度、声音播放、照片画面标记叠加、换卡／睡眠恢复、掉电或救援验收。CP扩大回放覆盖原厂`0x108398..0x108728`的映射、复制和元数据清理，仍未证明后续OS或完整系统启动。原厂文件／线程／消息／堆／UI服务由明确替身提供；没有硬件模型。照片标记保留原研究的菜单／参数能力和叠加未验收边界；声音仍是原厂选择器候选。本候选不能标注为实机稳定版。本次没有相机或真实存储卡操作。

上游固件及滤镜来源遵循其[第三方说明](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware/blob/47f8f022628aef8de382a613ea4d11cd51d0a965/THIRD_PARTY_NOTICES.md)，本地派生部分保留本仓库的个人非商业研究使用范围。原始固件、签名私钥和机身备份不属于本模块交付内容。
