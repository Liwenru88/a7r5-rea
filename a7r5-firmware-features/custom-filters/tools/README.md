# 电脑端拟合与完整配方文件封装

`fit_recipe.py`接收针对sRGB照片的三维CUBE，直接调用本项目的宿主C参考链拟合，导出现有AJR2/AFD1 `.a7filter`。不需要安装数值库，需要项目Python环境和宿主clang；不连接相机、不执行目标指令。

在项目根目录运行（输出目录必须尚不存在，父目录须已存在）：

```sh
.venv/bin/python -B a7r5-firmware-features/custom-filters/tools/fit_recipe.py fit \
  /path/to/input.cube --name 暖光 --budget 4096 --starts 3 \
  --output /path/to/new-filter-bundle
.venv/bin/python -B a7r5-firmware-features/custom-filters/tools/fit_recipe.py verify \
  /path/to/input.cube --bundle /path/to/new-filter-bundle
```

交付目录包括`filter.a7filter`、`fit.ajr`、`metadata.json`和`fit-report.json`。导入使用`filter.a7filter`；其余文件用于审计和误差复算。`verify`不重新拟合，会重新核对源CUBE、工具/模型摘要、最终配方与基线误差。拟合可用Ctrl+C取消；取消不发布结果。磁盘写入失败可能留下新建的不完整目录，不会覆盖旧文件或自动删除现场，请换一个新目录重试。

首版兼容现有格式，独立搜索三项tone、18矩阵和24 CC1，并优化整数网格。现有257候选机内求解作为基线；电脑采用显式预算、多起点和粗到细搜索，按独立选优区域选择结果。预算范围300～131072，起点1～12。较高预算不保证最终测试误差下降；保留真实的基线、最终误差和未改善结果。

**适用范围仍是固定ST/context4及PT经验网格的研究近似。** 当前512训练、25选优、18最终测试样本，三个集合按颜色区域隔离；最终测试不参与参数选择。模型内ΔE76不是实拍色差，灰阶/暖色标签只是代理。固定上下文的端点权重不能辨识全部18/24自由度；任意Gamma仍不支持。`camera_apply_allowed=false`保持。原兼容版见[第43批实现记录](../../specs/001-fixed-custom-filters/integration-43-desktop-fit.md)。

需要显式16色相区时，在`fit`命令加`--matrix-sectors 16`。它导出2483B AJR3，内部为3×16×6增量矩阵，仍使用`.a7filter`封装；必须配套支持新格式及`SECTOR_MATRIX`协商的软件，旧文件保持可用。默认`--matrix-sectors 1`继续导出AJR2。`verify`自动读取报告模式，禁止跨模式套用报告；初始八值、源LUT、模型和嵌入统计必须匹配。

当前同预算数值样例表明16区并不总能降低最终误差，部分最大色差还会变大，因此没有自动将它设为默认。固定Q8权重只选择端点1，该域只能辨识其中96个矩阵系数，不代表288项独立实拍标定。新格式、容量与完整对照见[第44批记录](../../specs/001-fixed-custom-filters/integration-44-sector-matrix.md)。

以下`recipe_file.py`是独立的已有配方封装工具；其本身不拟合CUBE。

`recipe_file.py`将**已经拟合完成、符合本项目格式的AJR2或AJR3**封装成完整AFD1 `.a7filter`，供双入口导入使用。它不是新的电脑训练器，不接收原始CUBE进行高精度训练，不访问相机或运行目标指令。需要Python 3.9+及宿主clang；在临时目录编译当前C格式校验器，直接调用`af_joint_asset_decode`和`af_import_asset`，没有额外Python依赖。

电脑训练程序必须直接面向本项目可表达的配方：18矩阵增量、24色度增量、1215个网格系数，以及能够由seed和三项tone精确重建的Gamma。不能把任意绝对Gamma曲线改名为AJR2，也不能将Hearts-Ace的12配置BIN直接改扩展名导入。AJR1可检查，但本次参数导入不支持它。

元数据示例（摘要必须替换成实际值，示例本身不代表有效拟合结果）：

```json
{
  "schema": "a7r5-recipe-file/1",
  "target_cp_sha256": "18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97",
  "base": 0,
  "name": "暖光",
  "lut_sha256": "填写原始CUBE完整字节的小写SHA256",
  "model_sha256": "填写AJR2所绑定模型的小写SHA256",
  "initial_params": [0, 0, 0, 0, 0, 0, 3, 0],
  "saved_params": [0, 0, 0, 0, 0, 0, 3, 0],
  "report": {
    "samples": 43,
    "clipped": 0,
    "delta_e76_milli": [1000, 2000, 3000, 800, 1200],
    "scope": 1
  }
}
```

八项参数顺序为：对比度、高光、阴影、饱和度、褪色、锐度、锐度范围、清晰度。色差数组顺序为均值、P95、最大值、灰阶均值、暖色／肤色代理均值，单位是ΔE76的千分之一，显示sRGB/D65且按原报告规则量化。`scope=1`只表示文件提供者声明的模型预测结果；工具核对字段和绑定关系，**不会复算或认证该误差，不表示机身实测**。改变saved参数后，原误差仍只对initial参数适用。

在项目根目录运行：

```sh
.venv/bin/python -B a7r5-firmware-features/custom-filters/tools/recipe_file.py pack \
  --asset /path/to/fitted.ajr \
  --metadata /path/to/metadata.json \
  --output /path/to/暖光.a7filter
.venv/bin/python -B a7r5-firmware-features/custom-filters/tools/recipe_file.py inspect \
  /path/to/暖光.a7filter
```

输出使用独占创建，不覆盖既有文件；写入失败可能保留不完整新文件，不自动删除。名称最多63个UTF-8字节，不静默截断。输入只接受有界普通文件，拒绝符号链接和设备文件。AJR2固定当前修改版4.06的CP身份；格式校验通过不授予固件安装或相机成像资格。

AFD1沿用现有导出格式，没有覆盖整个文件的签名或校验和；AJR2有载荷摘要，外层有载荷／模型绑定校验。文件摘要可由`inspect`记录以便交付核对，但不能当作作者认证。实际SD导入、菜单和机身成像的验收状态以当前项目交付记录为准。

## 完整Gamma离线对照

`compare_gamma.py`在同一真实宿主C参考链内比较三项tone和17个可调结点展开的129点Gamma。先重新运行现有257候选联合拟合取得固定基准，再冻结矩阵、CC1和网格；两臂各使用相同的额外评估预算，训练接受候选、独立selection选择，全部选择冻结后才各计算一次最终test。不读取既有报告的test来调整预算或选候选。默认使用16色相区；可显式选择旧18项矩阵模式。

```sh
.venv/bin/python -B a7r5-firmware-features/custom-filters/tools/compare_gamma.py \
  /path/to/input.cube --matrix-sectors 16 --additional-budget 96 \
  --output /path/to/new-gamma-comparison
```

额外预算范围16～16384，计入训练及selection的真实C损失调用，不包括共享的257候选基准和最后三份test报告。输出仅为`gamma-comparison.json`和`gamma-curves.json`，包含源摘要、原非均匀轴、冻结组件、整数曲线、模型内ΔE76/RGB误差及拒绝数。路径独占创建，不覆盖旧结果；Ctrl+C或取消在发布前不产生结果目录，写盘失败可能保留不完整的新目录，不自动删除现场。参考桥源码也参与旧拟合器来源摘要，桥改变后的比较须重新运行，旧报告只作历史记录。

**这不是任意129自由度已经得到验证。** CP曲线必须单调、原点为零且处于18bit范围；固定ST/第6列记录及横轴摘要不匹配会拒绝。当前Edit桥的两倍纵值限制还要求CP值不大于131071。129点中原点固定、独有的61440点按已有政策从邻点重建，因此最多有127个独立纵值；本工具只搜索其中17个平滑结点。独立改动61440点会明确拒绝，不能静默丢弃。该重建和舍入是表示政策，不能当作ISP硬件插值依据。

所有结果保持`research_only=true`、`camera_apply_allowed=false`。固定ST/context4与PT经验残差仍缺机身主／第二Gamma逐路由曲线和完整sRGB域依据；模型误差不是实拍误差，完整Gamma可能没有收益或在最终test退步。工具不导出`.a7filter`、不新增AJR4、不改变AJR2/AJR3及机身准入，不能把所得绝对曲线替换所有原厂外观的相对tone。
