# 第47批：多基底成像路由与完整研究升级包

本轮已达到“可以打包升级包”的本地交付目标：基于现有修改版4.06，实际生成并导出完整研究签名DAT，完成独立解密和再次完整解包。4.08只是本候选的版本标记，不是索尼官方4.08。整体设备验收仍为`NOT_VERIFIED`，T12未执行；没有操作相机、执行ARM或硬件模拟。

## 交付文件

- [BODYDATA.DAT](../../custom-filters/build/fixed-filters408-20261101-01/BODYDATA.DAT)：754525608字节。
- SHA-256：`d7763345b1897a85d93b0493576536995c6ae122a11fa69b8dc1bcb034bed413`。
- [使用范围与限制](../../custom-filters/build/fixed-filters408-20261101-01/README.md)、[校验文件](../../custom-filters/build/fixed-filters408-20261101-01/BODYDATA.DAT.sha256)、[完整回读回执](../../custom-filters/build/fixed-filters408-20261101-01/verification.json)、[导出核验](../../custom-filters/build/fixed-filters408-20261101-01/export-verification.json)。
- 原始构建与独立解包保留于项目根目录`.local/fixed-custom-filters/implementation47-upgrade408/`；最终汇总核验保留于`.local/fixed-custom-filters/implementation47-final/verification.json`。

签名通过DAT工具原有流程使用项目已公开授权的研究身份，与输入修改版4.06的公钥摘要相同。没有打印私钥、替换更新器或更改机身信任规则；它不是索尼官方签名。研究签名可验不代表任意机身会接受安装。

## 实际实现与修复

固定32槽、中文名称、八项原厂调参、保存／另存、SD双入口及机内副本的已有源码与模块一并集成。12个原厂外观含FL2、FL3保留；原六个用户槽在明确替换前仍走原生行为。机内入口处理sRGB三维CUBE，电脑入口导入本项目`.a7filter`，两者保存至同一用户槽。

本轮发现并修复原组件只允许profile0的问题。当前依据真实source基底核原生profile：ST为0／特定操作49，PT6、NT2、VV1、VV2为42、FL41、IN43、SH44、BW／SE53、FL2为54、FL3为55。不能把菜单base或线上枚举直接当作原生profile。主域与Capture均核来源，旧六模式、未知或不匹配来源仍委派原厂。

BW／SE原矩阵入口仅复制9个半字，并不走三端点27半字构造。新增独占调用点`71D6EC→71ECCC`的原厂一次委派与18字节增量；真实r6／r5分别传root／sector。每个色相区的三个端点增量必须相同，才能在此原生表示中唯一表达。该约束在AP导入／配方应用及CP银行接收统一检查；不满足时明确拒绝，不覆盖当前槽。AJR2／AJR3通用编解码未改，旧文件仍可解析、恢复和导出。

固定近门来自原FNV检查器自身96字节保留区的等价紧凑重排：80字节检查器、6字节永久门、2字节pad和8字节记录。未占用`BEF9C8`声音区，也未把`BEF53E`有效helper当作空洞。原检查器CFG、常量、返回与调用条件静态核对，宿主FNV对照通过；没有执行ARM。最终RX39192／40960字节、静态RW48744／49152字节，额外有界普通堆63072字节；原栈、页表、旧六资产和声音布局保持。共51挂点、1280字节合同、69个精确可逆窗口。

## 完整封装与独立回读

新增`experiments/packaging406/stage_cp.py`和`build_update.py`。CP在原FAT12中为未压缩`/cpapp-b.bin`，按固定内存计划变换并独立解析FAT簇链回读；原厂其余文件、空隙和元数据保持。USR在同源原镜像上追加本任务AP、70项资源和4个模块，完整树／inode核对及e2fsck退出0。

封装从输入DAT全新解包的固定manifest出发，组合CP组件与USR分区，使用正常工具重算sum、签名和加密。最终独立逐帧解密，再完整解包核对：仅`0700_part_image/dev/nflasha8`、`0700_part_image/dev/nflasha15`和`0701_part_image_sum/part_image.sum`改变；归档顺序、元数据、尾部、明文长度、更新器与外层身份保持，DAT头仅版本与CRC预期变化。

回读CP SHA-256为`91b8dd65b84eda2f9aa424ae3785afdc78cc689de3663c0aed268790440775ae`；USR为`fbf76c8ff24fea510ff0286a5d32578ffe12deecb02cf22891ab9b7e78b93f8b`。75项USR内容（AP＋70资源＋4模块）与冻结候选一致，CP可精确反向还原。完成回执仅在文件持久化与核验成功后发布；不覆盖原DAT或旧候选。

原输入DAT仍为`3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2`。历史CP／USR阶段回执的“未封装／不可安装”状态保留其当时含义，最终DAT状态以本批独立回读为准。

## 执行证据

| 范围 | 结果与回执 |
|---|---|
| 当前相关模块、AP／CP交叉编译 | 903 passed、22配置不适用skip，149.61秒，退出0；392份源与5项产物核对。`.local/fixed-custom-filters/implementation47-software-release/verification.json` |
| 多基底与单色矩阵 | 233项模块通过；组件115＋银行8场景ASan／UBSan通过，未进行泄漏检查。`.local/implementation47-multibase-components-final/verification.json` |
| 检查器／布局 | 检查器10项定向通过，当前ELF四项布局验证通过；69窗口正逆。`.local/implementation47-matrix9-layout/verification.json`及`.local/implementation46-final-native-v5/existing-tests-verification.json` |
| CP／FAT | 12项定向通过，实际阶段文件独立回读／正逆完成。`.local/fixed-custom-filters/implementation47-cp-stage-v2/verification.json` |
| 新封装器＋原DAT工具 | `a7r5-dat-tool/.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests/test_upgrade_package.py a7r5-dat-tool/tests/test_tool.py`：36 passed、退出0。单测使用临时测试身份；最终候选才由工具正常使用研究身份 |
| 实际DAT | `RESEARCH_UPGRADE_PACKAGED_AND_INDEPENDENTLY_READ_BACK`，验签／独立解密／完整回读均通过；导出副本完整SHA一致 |

## 保留的支持边界

机内CUBE拟合仍使用ST/context4固定参考近似；支持12基底的原生路由不等于12种基底均有校准后的LUT预测模型。电脑拟合文件的误差沿提供方模型报告，当前无匹配实拍资料，不能称为机身测量精度。Gamma保留现有相对三tone及AJR2／AJR3格式，不扩大完整Gamma格式。

EVF／JPG消费沿第46批已核原链及原生引用管理。本批不改变原post19／debug覆盖、快照恢复、特殊请求、条件提交和分组失败回退；这些分支可能覆盖部分自定义增量，不承诺所有模式逐帧四组件原子一致。完整运行会话、动态peer、最终物理DMA、实际照片效果、机身菜单画面、SD和掉电恢复仍未实机验收。

T11c本地研究封装子任务完成；T11整体模型／模式验收及T12设备部分保持未完成。文件级补丁可逆不表示机身可以直接降级，本包不是官方升级或设备验收结论。
