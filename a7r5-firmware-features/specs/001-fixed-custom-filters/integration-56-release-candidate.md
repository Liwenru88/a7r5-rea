# 第56批：整合最新修复的完整研究测试候选

日期：2026-11-02。本轮已完成T11j56：将第55批Gamma选表修复写入新的CP/FAT，与现有AP、四个产品库和资源组成完整DAT，并完成严格封装与独立内容核对。没有连接、修改或更新相机，没有CP／ISP硬件模拟。整项功能和实机验收仍未完成。

## 交付身份

| 项目 | 本次结果 |
|---|---|
| 候选 | [BODYDATA.DAT](../../../.local/fixed-custom-filters/integration56-release410/update410/BODYDATA.DAT) |
| 版本／修订 | 研究4.10／integration56；不是索尼官方4.10 |
| 长度 | 754525608字节 |
| DAT SHA-256 | `3e3d7e5759e39a0c8018e055e6309292eeb7c5ea742dd186b35e388bc180c158` |
| CP SHA-256 | `ef616a6581dac99106380a4f56da9d88093680cf524f72b0eb0b502cea58fc99` |
| 固定输入 | `/Users/wenruli/Desktop/索尼/BODYDATA.DAT`，修改版4.06，SHA `3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2` |
| 最终总回执 | [verification.json](../../../.local/fixed-custom-filters/integration56-final/verification.json) |

旧第53批4.10包仍保留，SHA `36cf5ff87c9e1f2baac0ac531e22abbaf50c70cf7b5443dc156c9cc31f59619a`，不含第55批修复。两包版本字符串相同，必须用修订目录和完整SHA区分，不以显示“4.10”识别新内容。没有增加同版本重装或降级能力。

## 本次实际变化与功能范围

产品代码变化仍只有第55批`af_cp_components406.c`：主／Capture共用Gamma检查额外接受继承FL2／FL3的四个已证精确记录来源。修复合法用户配方Gamma增量被旧RO范围误拒的问题，保持原厂选表、曲线附属数据、后处理与分组回退。

本轮刷新399项来源的软件构建，复用来源未变的114项CP链接及第55批测试，生成新CP并封装。与第53批候选相比，最终AP及75个USR内容项（AP、四DSO、70资源）完全一致；CP改变，分区校验同步改变。四条继承Gamma记录及原始4.06完整DAT保持。未修改更新器、信任政策、原厂槽或Gamma载荷格式。

沿用既有实现：12个原厂外观（含FL2／FL3）＋20用户槽、中文自定义滤镜菜单、SD双入口（机内sRGB三维CUBE转换／电脑拟合`.a7filter`）、八项参数临时编辑／保存／另存及照片标记扩展。沿用不代表这些功能已全部获得实机验收。

## 实际验证

| Evidence | 回执／结果 | 证据边界 |
|---|---|---|
| E-401 | [软件构建](../../../.local/fixed-custom-filters/integration56-software/verification.json)：66 passed，12.83秒、exit0；当前UI和仓库交叉构建 | 仅启动依赖与宿主合同；不执行机身AP／CP |
| E-402 | [CP staging](../../../.local/fixed-custom-filters/integration56-cp-staged/verification.json)：51挂点／69窗口、新CP落盘；独立FAT提取、无关文件／元数据保持、全分区及CP精确逆还原 | 复用第55批真实ARM链接，RX39280／40960，静态RW48744；未运行新CP模块 |
| E-403 | [封装回执](../../../.local/fixed-custom-filters/integration56-release410/update410/verification.json)：5阶段exit0、研究签名验证、独立解密逐字节一致、完整再次解包／分区及75内容项回读 | 仅三预期归档成员改变；不证明实机启动、接受升级或像素效果 |
| E-404 | [独立内容审计](../../../.local/fixed-custom-filters/integration56-content-audit.json)与[最终来源审计](../../../.local/fixed-custom-filters/integration56-final/verification.json)：四DSO、两UXC共60复杂载荷、最新CP身份／精确逆还原、四继承记录及输入／旧包保持全部通过 | `device_installation_approved=false`；实际设备仍未验收 |

来源未变，复用第55批310 passed／10旧配置skip、36个ASan／UBSan场景及15个产品候选进入原CPU Gamma构造的证据，本轮未重复执行这些测试；见[第55批报告](integration-55-native-selection.md)。AP/UI／产品库与第53批字节一致，因此可引用既有QEMU菜单和原Fsys软件卷证据。本轮没有重跑QEMU，更未以此声称真实SD或/setting耐久性已通过。

## 剩余限制

T03native55、T03f2与T12保持未完成。仍缺完整实际AP／CP任务运行、机身启动菜单／握手、真实SD和机身持久化、照片取景／JPG像素与切回验收。特殊2B未知来源保持原委派，未列为无条件前置，也不宣称已支持。默认LUT模型仍为ST/context4参考域，不能把FL2／FL3记录接受修复提升为全12基底转换模型或实拍色差完成；完整Gamma格式本轮未扩大。

照片标记扩展已合并到候选，实际照片叠加仍未验收。签名／容器完整只证明本地封装身份和内容，不构成可安全刷机或可回退的保证。后续受控设备测试范围及异常处置见[实机测试与恢复说明](integration-56-device-test.md)。
