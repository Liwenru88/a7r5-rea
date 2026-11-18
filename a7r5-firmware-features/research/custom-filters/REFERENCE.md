# LUT转换参考与来源

2026-10-26用户追加[QAQLeonard/a7c2-fl23-research](https://github.com/QAQLeonard/a7c2-fl23-research/tree/ef7db116e13e37be91e9af20360dc9bba8d64a9b)为参考，固定提交`ef7db116e13e37be91e9af20360dc9bba8d64a9b`。当时两项目的main重新查询后，Hearts-Ace仍为下述历史提交。公开参数快照可继续支持离线实现，不要求用户先提供新照片。

## 2026-10-30来源刷新

通过GitHub只读连接重新核对：A7C2仍为`ef7db116…`；Hearts-Ace已新增[提交bf71d789](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware/tree/bf71d789262d53ff5fcd23d87aea5bdc07a46f19)，提交时间UTC 2026-10-29 16:32，对应北京时间2026-10-30 00:32。其4.35源码与v4.5训练资料另存`reference30/`，逐文件验证Git blob与SHA256，未运行下载的脚本、刷写工具或改变本包基线。新来源不自动替换现有数值夹具、模型摘要和准入条件。

- 新`sony100mp_5300k_v45/runtime-validation.json`报告99,372个平色块、每块9个探针；模拟前端与原Edit输入逐点相等，PT颜色模型中心5点均值有1块最大差11原生码。这里只读取并验证报告身份，尚未独立复跑99,372块捕获，不能把该数量算作本项目已执行测试。
- 随后独立读取固定`pairs-v45.npz`（SHA256 `ff89b472e8a71686bd4ff3d2e3e3fcb1886841a0e39ede91a1878df13310eb53`），核对99,372项设计值经sRGB反传递函数生成参考RAW码、两种sensor归一化及九探针关系。该数值关系检查不运行上游拟合器，也不验证其2439次捕获／TIFF或留出预测误差；设计sRGB不能当作当前CP的照片sRGB输入。
- `edit_raw_front.py`的输入是RAW码和明确的RGGB／as-shot WB，输出在Vatr及SSCS之前；它不是sRGB到当前CP的完整桥。v4.5数据仍绑定固定PT下游，空间处理和相机等价性不在其声明范围。
- 新`stock_grids423.json`两份模板来自4.00及CP `3269bf…`，与本项目CP `18b265…`不同；资源选择不是独占外观名，不能直接命名为ST／FL2／FL3或当当前机身校准。
- 新`native_color.c`提供网格原控制器后接入和回退快照思路；`r5_render_binding.h`自身明确是离线ABI，仍要求原适配器建立domain／scene／override门控。其12配置、内部格式和地址须重新核对本包，不能直接移植或据版本号宣称成像通过。

## 公开数值资料与新增算子

- A7C2的`calibration/a7c2-2.01.virtual.npz`包含17控制的正负响应、768颜色锚点、ST/sRGB逆坐标与基底正向代理；SHA-256为`7e183f46f7acd739a12b7c2989e0ce245628a1f0d72d4f673f48945f4493b0af`。其范围为A7C2 2.01、ISO800、5000K和单色卡；不是R5标定。借鉴零增量差值锚定、整体量化后重新预测和颜色分组留出，不导入其代理作为R5默认后端。当前配方可独立修改129点与三端点，不能静默外推其17维共享增量子空间。
- R5的`R5ColorLab/data/model/capture/`公开runtime、RAW上下文、settings及逐阶段输入/输出；`data/static_tables.json`公开角度等表。新`a7filters/reference_snapshot.py`只读校验固定context4的长度与摘要，参数仅由同一捕获派生，不执行下载源码。这里的捕获是Imaging Edge Edit的合成RAW原生渲染观测，不能称为本机运行快照。
- 新`native/af_edit_reference.*`依据公开整数/浮点运算定义独立实现矩阵、MainGamma、CC1、AreaComp、色度抑制、YGamma和RGB输出；`af_edit_chain.*`仅组合这些颜色阶段，失败不发布输出。`tests/fixtures/edit_reference_context4.json`仅包含公开数值表/捕获片段及来源摘要，没有移植上游Python算法或优化器。每阶段原patch仅1种重复颜色；矩阵只对含两侧邻点的内部列主张捕获一致，不能以1024像素声称1024颜色。
- Edit后SSCS/矩阵前整数RGB与显示sRGB之间的桥仍未验证。颜色子链不含中间的锐化/降噪等空间处理，不假定残差网格的硬件位置，不授予CP应用能力；其字节误差不等于本机照片色差。
- `af_edit_gamma_table.*`、`af_edit_matrix_table.*`已独立重建完整参考表；`af_edit_context.*`输出拥有全部表并事务发布，公开context4基线逐字节一致，宿主/AArch64均实际执行。矩阵只在显式恒等校准、指定输出域及对角约束下支持，任意新候选不因此取得原Edit逐位保证。
- 最新复核将公开ST的129点Gamma精确对应到本包CP wire0/column6/route0，纵值摘要`f9a61f8329b630a026d386c85b46194a2572e020db2491db6def06b96ac2b55b`一致；Edit128共同节点轴×32、纵值×2。CC1有明确排列/倍率对应，矩阵96项打包对应但20项语义量化不同。这些是参数锚点，不是sRGB或取景/JPG域命名依据；不能改写既有保留18位纵值的坐标桥语义。
- 原矩阵平滑要求邻域，实际AArch64 width1拒绝且输出保持，显式5列常色邻域才成功。后续联合预测必须明确邻域、域桥和网格位置；不能将三组件上下文直接注册为components=15的完整后端。
- 已新增独立`af_edit_cp_gamma.*`落实固定ST/第6列参数锚点，内部核对原记录/轴摘要，明确61440可表示性和舍入准入；宿主5项、AArch64实际11项通过。它不改变旧坐标桥、不标识真实图像流，也不是允许导入的完整模型schema。

A7C2根许可为PolyForm Noncommercial 1.0.0；上游旧子目录存在不同许可文本，不能只据旧文件认定整个项目许可。该项目源码和NPZ仅作忽略目录中的研究缓存。Hearts-Ace及其ColorLab数据/第三方权利保持下述说明，公开捕获数值仅用于有来源的离线测试，不作为已批准的机身默认参数或可安装固件分发。

## 历史参考及本包布局

第十八批依据用户指定的[Hearts-Ace/sony-a7r5-custom-firmware](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware/tree/8b563d46f800679abd3f215950cb541fc81da2a6)研究转换路线，固定提交`8b563d46f800679abd3f215950cb541fc81da2a6`，不跟随浮动分支改变模型。

- `R5ColorLab/compilers/custom_filter_v4.py`用于核对CC1/block13/Gamma/1215字节网格格式；未将对方BIN v4、12配置编号或AP/CP地址用于当前包。
- `R5ColorLab/web/paired_response.py`及`scripts/residual_grid.py`用于核对成对响应、三线性节点及平面排列。新的C预测/优化/打包和ΔE76代码独立实现，没有移植其SciPy求解器或Web服务。
- `tests/fixtures/r5_paired_v2.json`摘录公开成对模型的数值及来源，完整原模型SHA-256为`8879499fbd9b24899dcbd8fee4135b806fdcba1fd18a677b090b7af212b85a45`。复核其11项来源均为PT，且非网格参数摘要固定为`0ce71ba0e51fbf685cb4683f5ffd976f55cd922038e5dc17b18db354ab416181`；此前“保守限定ST”的说明和夹具掩码有误，已纠正。当前接口不能核对该精确捕获条件，因此原始捕获摘要默认拒绝，夹具默认无可用基底。独立数学测试须显式启用另摘要的PT来源数学夹具；更换摘要不授予产品或机身资格，当前没有已准入的完整四组件产品模型。
- 该公开模型由11对图像拟合，训练坐标覆盖42/256网格单元，原模型留出RGB8 RMSE约3.696；未覆盖区域为外推。它不是原厂ISP唯一识别结果，也不是当前修改4.06的机内效果验收。
- 对方仓库根代码许可为MIT，`R5ColorLab/`另列AGPL v3，第三方及原生数据保留各自权利。本轮公开源码只读缓存保留在忽略目录，未复制上游服务或优化器源码进入产品模块；数值来源与适用范围随夹具及报告保留。

当前包中的原生网格布局另由同一锁定CP的`0x231654`完整打包函数及文件偏移`0xd841d8`排列实证，不能仅靠对方格式推断本包兼容。只有原厂打包字节一致，不代表颜色像素、动态应用或帧寿命已验证。

第二十批继续只读核对同一提交的`edit_native_model.py`、`edit_color_pipeline.py`、`edit_native_recipe.py`、`fit_native_proxy.py`、`fit_edit_native.py`、`fit_anchor_native.py`和`web/core.py`。其精确色彩子链的输入为Edit后SSCS/矩阵前整数RGB，包含运行时表、标定、色相分区、Gamma、CC1和其他色度步骤；不能直接接收本项目的显示sRGB颜色点。对方16扇区block13、17位Gamma上限与本包既有端点矩阵增量、18位Gamma需分别适配。来源文本保留在忽略目录`reference-20/`，未执行或移植其模型/优化器代码。新的C整数组件和联合搜索独立实现；完整本机预测后端仍未完成。
