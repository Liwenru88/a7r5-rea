# 第48批：照片标记并入32槽滤镜升级包

按用户“帮我加入”授权，已将同源照片标记扩展合并到现有固定32槽滤镜候选，实际生成新的4.09研究签名DAT并独立解包回读。4.09仅为研究版本标记；原修改版4.06输入和先前4.08候选保持不变。T11d完成本地合并／封装范围，整体功能与设备验收仍为`NOT_VERIFIED`。

## 交付文件

- [BODYDATA.DAT](../../custom-filters/build/fixed-filters409-20261101-01/BODYDATA.DAT)：754525608字节。
- SHA-256：`18d9093c5abb20e5aa576aae832d46f28b96a119bb51841643ef434ea32e9d19`。
- [功能与限制](../../custom-filters/build/fixed-filters409-20261101-01/README.md)、[SHA校验文件](../../custom-filters/build/fixed-filters409-20261101-01/BODYDATA.DAT.sha256)、[封包回读回执](../../custom-filters/build/fixed-filters409-20261101-01/verification.json)、[合并及导出核验](../../custom-filters/build/fixed-filters409-20261101-01/export-verification.json)。
- 构建工作区：项目根目录`.local/fixed-custom-filters/implementation48-upgrade409/`；独立来源与组合核验脚本及回执：`.local/fixed-custom-filters/implementation48-final/`。

沿用原公开研究签名身份及正常签名／加密流程，不打印私钥、不改变更新器或机身信任规则。它不是官方签名，也不能证明任意机身会接受升级或可以直接降级。

## 实际增加与保留

加入照片标记的28个支持位和三组原登记范围包装函数，复用已有标记开关、比例与透明度菜单逻辑，包括2.35:1选择。三个原生范围分别为0～1、0～5、0～15。该功能用于取景构图参考，不新增成片水印或自动裁切。

保留4.08的12个原厂外观（含FL2／FL3）、20个用户槽、未明确替换时的原六款行为、自定义滤镜菜单、SD双入口、八项调参及机内副本接口。机内CUBE仍为ST/context4参考近似；完整Gamma格式、BW／SE矩阵可表示限制、原厂分组更新与回退均不改变。

## 组合方式与具体改动

照片标记占`0x500fc10..0x500fc70`共96字节，滤镜bootstrap紧接于`0x500fc70`，构造器尾为`0x500ff8c`，都在原同一RX页。唯一重复窗口是ELF段长度字段`0x60/0x68`：丢弃标记独立包较短的终点，统一保留滤镜终点`0x500ff8c`。原37个标记窗口因此保留35个，与原7个启动窗口组成严格42窗。

三个标记登记的指针及原RELATIVE addend同步更新，原数据字段及重定位类型保持；包装函数只设置范围参数并尾调原`0x29051dc`，保留调用者LR。没有新增重定位项、映射页、CP参数格式或照片帧租约，也没有修改原标记绘制函数。

新增`experiments/packaging406/aspect_merge.py`作为固定35窗独立契约，冻结原计划、生成器、检查器三份来源SHA。`build_and_audit.py --include-photo-markers`显式选择合并，默认仍生成纯滤镜计划；再次检查复合AP与运行期UI／消息入口无重叠。`loader/build_loader.py`按完整42窗重生成启动校验头和DSO，不复用旧AP摘要。冻结／USR阶段只允许显式schema3与严格布尔True通过标记契约；封装阶段要求schema3／标记True与4.09配对，原schema2／False／4.08路径保持。

本次AP SHA为`8b34f12d4314a6aa829e14d17971c154575c68ae1d11c4573798f13a860d069a`；USR SHA为`f5860c22d5bdeaea62887c1029269ede9cf1be818730ee62833ae647396626fe`；启动DSO95864字节，SHA为`91a2b4ac7125238c7b21baf5d6ddf8dbf184dc59b57bfe1757d73542373547c1`。

## 实际验证

| 范围 | 命令／来源与结果 |
|---|---|
| 合并与清单范围 | 当前`.venv/bin/python -B -m pytest`定向执行`test_unsigned_staging.py`、`test_aspect_merge.py`、`test_candidate_preflight.py`、`test_recipe_build_pair.py`：45 passed，2.57秒，exit0 |
| 封包与版本配对 | DAT专用环境执行`test_upgrade_package.py`及原`a7r5-dat-tool/tests/test_tool.py`：42 passed，1.26秒，exit0 |
| 真实启动校验函数 | `test_marker_bootstrap.py`：5 passed，5.55秒；提取生产`canonical()`并链接真实SHA代码，完整97MB原AP与标记窗口用于宿主夹具；验证42窗通过、漏逆窗／窗内／窗外篡改拒绝及旧7窗兼容。bootstrap机器码是明示夹具，不声称执行真实ARM |
| 当前模块与交叉链接 | `software31/verify.py --recipe-bridge --capture-copies --output .local/fixed-custom-filters/implementation48-software`：903 passed／22配置skip，151.53秒，exit0；395份来源一致，五项产品产物与4.08一致 |
| 实际USR | `implementation48-usr/verification.json`：42窗AP、70资源、4DSO；完整树／inode及无关元数据保持，e2fsck退出0 |
| 完整DAT | `build_update.py --version 4.09`：验签、独立逐帧解密、再次完整解包及75项USR内容回读通过；相对原4.06仅CP／USR／sum改变，更新器、归档结构及原身份保持 |
| 新旧包独立比较 | 最终AP逐字节等于4.08 AP增加固定35标记窗；CP相同，75项USR内容相对4.08只改变AP和启动DSO。真实启动头42窗逐项核对，二进制含新AP及原AP摘要；132个滤镜校验位置相对4.08全保持（其中131份原指令、1处继承启动跳转） |
| 静态重定位与导出 | 三包装函数在三个装载基址的9组ADR／B目标及范围常量静态核对；不执行指令。新DAT导出副本完整SHA一致，原4.06及旧4.08完整SHA仍相同 |

回执分别见`.local/fixed-custom-filters/implementation48-{prechecks,software,package,loader,usr,upgrade409,final}/`。CP继续复用未变化的`implementation46-final-native-v5`及`implementation47-cp-stage-v2`实际候选，并重新检查其源和产物指纹，不重复编译未改的成像模块。

## 未验证项

**实际照片预览上的标记叠加仍未验证通过。** 旧独立4.07候选曾验证菜单操作，但未观察到照片帧标记变化；本次没有再次执行QEMU或ARM，不将旧菜单证据扩成新组合包的显示验收。

本批仅证明标记登记、支持位及滤镜功能已共存于实际完整DAT。机身升级接纳、真实菜单、EVF／JPG效果、SD与掉电恢复仍未实机验收。T11整体模型／模式条件及T12继续保持，未操作相机或硬件模拟。
