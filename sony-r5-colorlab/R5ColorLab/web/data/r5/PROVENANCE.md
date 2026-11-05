# R5实拍网格响应 2026-10-24

用户提供R5-grid-response.zip中的model.json，原始JSON完整保留，SHA256 6852ead83bf381215a8d721d1557cc73803f6ef60a0745971e8783144863c96b。11对探针图，refined-smooth模型；留出RMSE1.9158，零修正9.2282，原暂定模型15.2171（8位RGB级）。三通道激励秩3，训练坐标覆盖14/256单元。报告只比较零修正与原暂定模型，没有与C2代理直接比较。模型适用本次拍摄条件，未覆盖颜色属于外推，无重复ZERO漂移回执，不宣称唯一恢复ISP或跨条件通用。

新实测选项替换C2；已有任务保持保存的响应标识。采用独立paired_response实现，不执行用户ZIP中的Python代码。模型在PC训练、压缩、量化及预览使用，BIN仍仅写颜色参数和1215字节网格。


## 2026-11-02 非线性正式响应

默认新增r5-paired-20261102-nonlinear，原始JSON SHA256 a312761c8500e8a9ecb3b1b23ad27cf7709cb6eb8bf41c956970e1bdcc2c82f0，来源4190任务615b5d1cf1cf4b8bbb76c8bb9dab28bb。27控制点二次B样条坐标修正＋30×3二阶响应；原生405节点、三线性查询及BIN不变。CPU/GPU/压缩/预览使用同一固定快照，v1/v2历史身份继续支持。11/12探针已用于开发对照，本次标定仅PT条件经验模型；不宣称新盲测、全色域或跨条件实机验证。核验见工作区analysis/fuj_v45_nonlinear_formal_20261102/；39回归及MPS推理/求解/量化/连续性通过。


## 2026-11-02 三专家正式响应

新任务默认r5-paired-20261102-three-experts，模型SHA256 3cecec3387acbd72524be42db34586237df0c2c7d458d4090467375d28fa0815，来源原三专家4190任务379c5d84e1804a8ea82667f5a45fb2ca（analysis/grid_hue_experts_20261102/model.json）。共享C1 81×3及3×81×3完整响应残差，门控kappa2/s0.25/c0.04，灰轴回共享；坐标warp及原生网格/256尺度保持。CPU/Torch/GPU/求解/整数细化/连续性/预览共用固定身份。

正式平滑改为native-operator-geometry/1及paired-preclip-path-derivatives-v1，输出连续性local-dual-domain-v1保留，推理模型不写入BIN。新结果记录注册表和实际推理指纹；旧v1/v2/a312只按自己的固定身份重放。175回归（7跳过）、19MPS模型/网格及四stage原生GPU验证通过；细节见工作区analysis/fuj_v45_three_expert_formal_20261102/README.md。此模型是标定条件下经验响应，不宣称Edit/ISP恢复、全域无抖动或跨条件实机验证。
