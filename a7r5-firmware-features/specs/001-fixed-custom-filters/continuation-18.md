# 第十八批：机内可执行的LUT网格转换核心

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-26`
- Status: `OFFLINE_NATIVE_GRID_CONVERTER_VERIFIED_NOT_INSTALLABLE`

## 本轮结果

完成T08b1的限定离线范围：将已解析的sRGB三维CUBE近似拟合为原生5×9×9、三平面、1215字节七位网格，包含有界优化、量化、取消及独立留出误差评估。新C代码在AP的AArch64指令集实际执行，拟合产物与当前修改4.06原CP完整打包函数逐字节一致。转换算法没有依赖主机Python、SciPy或Web运行时。

用户最终目标继续是“原厂创意外观＋固定20用户槽＋自定义滤镜菜单”，原厂成像和资源管理优先复用。新代码尚未接入SD文件选择、AP导入工作任务、机内持久化及真实网格应用。T08b/T08、T05/T06/T07/T09整体仍未完成；本轮不等于完整机内导入已交付。

## 主要改动

| 文件 | 行为 |
|---|---|
| `native/af_grid.h/.c` | 模型/样本契约、三线性节点与RGB相关响应预测、405项排列校验、1～8级整数打包 |
| `native/af_grid_fit.c` | 调用者工作区、有界投影优化、平滑约束、最近偶数量化、劣化回退、取消不发布及独立ΔE76/RGB评估 |
| `a7filters/native_grid.py` | 锁定CP摘要、独立AArch64 ELF检查/执行，调用原CP完整函数核对9组产物和保护区 |
| `a7filters/baseline.py` | `--grid-adapter`的研究模式/普通文件/128KiB门控，集成同包审计 |
| `tests/grid_support.py`、`test_native_grid.py` | 实际C库、独立数学/排列/颜色误差对照、非法/重叠/取消/基底拒绝 |
| `tests/native_grid_target.c`、`fixtures/r5_paired_v2.json` | 公开数值来源、目标拟合/报告/取消和2441项目标断言 |
| `tests/native_sanitizer.c` | 加入网格边界/打包探测与拟合/报告/取消，保留已有核心契约 |

核心工作区499436字节，不含CUBE源、样本、任务栈及整机服务。公开模型保守只允许ST；不是当前4.06的物理标定。先保留原基底曲线/矩阵，仅拟合附加网格，没有实现完整CC1/block13/Gamma联合求解。接口、模型来源、许可、误差及剩余接线见[LUT转换报告](lut-conversion-18.md)、[参考说明](../../custom-filters/REFERENCE.md)。

## 实际验证

| 证据 | 结果及边界 |
|---|---|
| [回归命令](../../../.local/fixed-custom-filters/pytest-18.json) | 187 passed in 7.03s，命令7.349秒、退出0，源码未变 |
| [ASan/UBSan命令](../../../.local/fixed-custom-filters/native-sanitizer-18.json) | 20000次输入/状态/网格等探测与实际拟合/报告/取消通过；编译1.325秒、运行0.504秒、退出0 |
| [数值与误差回执](../../../.local/fixed-custom-filters/reference-fit-18.json) | 固定上游数学定义与C预测10000点对照，最大通道差5.3891×10⁻⁷；另4类LUT的独立留出评估 |
| [完整同包审计](../../../.local/fixed-custom-filters/cp-ui-access-406-18.json)与[命令](../../../.local/fixed-custom-filters/audit-command-18.json) | 149.056秒，原修改4.06验签、736841帧、147成员、71目标及103资源；输入起止身份保持 |
| 同报告`native_lut_grid` | AArch64拟合实际执行；原CP `0x231654`完整函数与独立预期及新AArch64打包共9组逐字节一致，源/保护区保持 |
| 既有联合接入 | 原24处AP分支、1218刷新、864快照消费、15组任务运行时和4组HELLO保持；HELLO未开放PRESET成像 |

实际AArch64拟合网格SHA-256为`34a00f6f0958928aa971099ab353d4ef93ab58f5f3d3f7402d50e2d883a2bfe9`。它证明新算法输出已进入原打包函数；未上传像素、执行ISP硬件或安装LUT。

温和暖色LUT、17³非线性LUT的独立留出平均ΔE76分别约0.757、1.277；反转压力案例约84.851，表明单网格能力有限。全部是研究响应模型内指标，不能当作当前相机成像误差或与源模型实拍误差相加。其他基底/参数组合与真实照片仍待验证。

## 构建与复算

当前研究ELF为[grid-converter.elf](../../../.local/fixed-custom-filters/build-18-grid-verified/grid-converter.elf)，88704字节，SHA-256 `6dfd13fb2b6b1245b717ce6c60c71446a0d63436004b34331c6c119002062fa1`。研究基址`0x9060000`只用于模拟器，不是机身装载地址。[构建回执](../../../.local/fixed-custom-filters/build-18-grid-verified/commands.json)记录7条编译/链接命令、源码及模型摘要。

源码、文档、输入、历史产物和引用终检见[第十八批指纹](../../../.local/fixed-custom-filters/verification-continuation-18.json)。仓库根目录复算，回执选不存在的新路径：

```sh
PYTHONPATH=a7r5-desktop/prepared/engine/site:a7r5-firmware-features/custom-filters \
  ./.venv/bin/python -B -m a7filters.baseline \
  /Users/wenruli/Desktop/索尼/BODYDATA.DAT --investigate-ui \
  --ui-adapter .local/fixed-custom-filters/build-12/ui-adapter.elf \
  --ap-ui-module .local/fixed-custom-filters/build-12/ap-ui-hooks.elf \
  --cp-parameter-adapter .local/fixed-custom-filters/build-13-verified/cp-parameters.elf \
  --cp-atomic-adapter .local/fixed-custom-filters/build-15-final/cp-atomic.elf \
  --ap-handshake-module .local/fixed-custom-filters/build-16-handshake-verified/ap-handshake.elf \
  --cp-handshake-module .local/fixed-custom-filters/build-16-handshake-verified/cp-handshake.elf \
  --ap-runtime-module .local/fixed-custom-filters/build-17-runtime-final/ap-runtime.elf \
  --cp-runtime-module .local/fixed-custom-filters/build-17-runtime-final/cp-runtime.elf \
  --grid-adapter .local/fixed-custom-filters/build-18-grid-verified/grid-converter.elf \
  --report .local/fixed-custom-filters/next-grid-audit.json

./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short
```

## 本轮发现与剩余工作

初版把原排列错误地理解为“目标读源”；先执行原CP得到反例并保留[排列失败回执](../../../.local/fixed-custom-filters/grid-permutation-18-red.json)，随后修正为“源写目标”。8位颜色取整还先出现float乘255的半入边界差异，保留[定向失败回执](../../../.local/fixed-custom-filters/grid-metrics-18-red.json)，修正为先提升double再乘255。最终源码重新构建并通过上列全部验证，早期ELF与回执保留。

下一步优先将参数/网格交给原厂整组应用和快照，查明实际用户槽选择到原生消费者的接线；对新增字节的寿命只加必要保护，不默认替换原厂银行和帧管理。随后连接导入任务、进度/取消、候选保存、SD菜单和机内完整副本。模型适用域、其他基底、实际路径/空间、完整画面及取景/JPG仍有离线和设备门槛，总体保持`NOT_VERIFIED`。

未操作相机、USB、SSH或真实SD，未读私钥，未修改输入DAT及冻结材料，未生成安装包，未暂存、提交或推送。
