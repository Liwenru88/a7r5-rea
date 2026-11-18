# 最终验证记录

状态：研究、三款复测、工作台共享内核和工程交付闭环完成；三款中仅薄荷青绿采用新配方，另两款按既定门槛安全回退。没有证明全局最优或实机效果。

## 代码与环境

项目 `.venv`：Python 3.12.11、PyTorch 2.15.0、NumPy 2.3.5；GPU 为 Apple Metal/MPS。方案 `native-joint/1`、revision `native-joint-20261114/3`。没有新增依赖、设备连接、固件更改、Git提交或推送。用户已有未提交变更及 release 删除状态保持。

共享入口为 `web/native_joint.py`，工作台适配为 `web/native_joint_workbench.py`，研究 CLI 为 `scripts/benchmark_native_joint.py`。完整 Gamma129、原格式 v4/v5 和工程 24 槽保持。`native_robust_grid.py` 收敛真实输入活动集，`native_cached_forward.py` 与原 CPU 入口逐值一致。

## V1/V2 回归

1. `PYTHONPATH=tests:web:scripts .venv/bin/python -B -m pytest tests/test_native_joint.py tests/test_native_joint_workbench.py tests/test_native_feasible_experiment.py tests/test_native_gamma129.py tests/test_native_conditional_grid.py tests/test_native_full_photos.py tests/test_native_colour_guard.py tests/test_native_active_curves.py tests/test_native_cached_forward.py tests/test_native_joint_photo.py tests/test_native_joint_integer_log.py tests/test_packed_selection.py tests/test_hybrid_update.py tests/test_integrated_training.py --import-mode=importlib -q --tb=short`：**67 passed、47 subtests passed**。
2. 文件、导出、批量、实时日志：`tests/test_file_storage.py tests/test_export_policy423.py tests/test_compression_workflow.py tests/test_batch_training.py tests/test_live_progress.py` 同样导入方式：**22 passed、4 subtests passed、1 skipped**。跳过原因为历史数值夹具缺失，不视作通过。
3. `node --check web/static/app.js` 和 `git diff --check` 通过。最后 UI 提示修订只改变说明，使用真实任务重新载入核对。

回归先复现两项 RED，再修复 GREEN：终检取消后不得发布 done；不同联合 revision 必须产生不同任务签名。新整数事件明确区分 TRAIN 预筛、完整复验接受/拒绝，并继续读取历史 grid 日志。

## 真实 GPU 与源码绑定

证据根目录：`/Users/wenruli/Desktop/索尼/ColorLab-联合训练定稿-20261114`。

- `正式复测/`：三款 C600、分组恢复、条件网格 2000×至多2 和整数精修，真实 GPU 运行。
- `定稿复测/`：完整六张开发照片再收敛600步，三款锁定后终检全部拒绝；失败保留，未宣传为通过。
- `稳健定稿/`：同一冻结六轮×500步活动约束方案处理三款，先全部锁定开发候选，再一次性终检。三款源码和输入摘要在运行前后核对，保留独立源码快照；前段产物按审计来源复用，不伪装成最后源码重新跑了全部前段。

暖金日光 TEST RGB 3.9475→候选3.5489、ΔE00 1.5777→1.4638，但0.919原生色相max超限，采用原配方。薄荷青绿7.0619→3.8879、3.3121→1.4184，灰阶、颜色P95、双域过渡、历史留出照片全通过，采用新配方。冷蓝都市5.3582→3.3408、2.0845→1.2739，但照片局部RGB及新相位原生饱和度max超限，采用原配方。

原始过渡与量化区间分开；没有为了通过而放宽门槛。TEST和四张留出照片在历史研究出现过，本轮不称为全新照片盲测；最终新增相位为0.271/0.919。稳健网格CPU/MPS最大差约1.03e-7，门限2e-6。

## V2/端到端链路

`tests/verify_native_joint_smoke.py` 使用真实暖金目标 TIFF、GPU、六张完整开发照片和四张终检照片，隔离运行目录 `workbench-smoke/`。预算缩为联合200、条件200、整数1轮、完整照片200、稳健1×100；没有假求解器，仅替代上传文件寻址。任务 bdf1696a8610421c8c4f77e4e1a5be1c 实跑745.7秒，状态done，实际安全回退，104条观察事件。

已校验：一次终检；Gamma129；BIN解码重编译；最终预览与导出runtime相同；实际BIN等于任务输出；整数和各阶段Loss日志存在；完整照片约束审计；HTTP下载包含稳健各轮日志。真实浏览器查看曲线、整数状态、回退说明，保存到24槽，再通过UI导出核对任务BIN。缩预算不用于三款正式交付。

## 交付与页面

`交付/` 内有标准/通用偏差BIN、参数JSON、配置包、`.r5proj`、CSV/JSON指标、45张照片/渐变PNG及HTML。工程 `2366efd5e1a04eefbe10ab4a951a9c19` 已在主工作台载入，15已保存/9空槽；原十二款在标准版逐字段一致。标准版只更新6号，5/14保留原配方。通用偏差版只迁移A1/A2，不能称A1/A2色彩已验收。

标准BIN SHA256 `cb888a42a371e006f84c03738cb2d977e9c0e404557776a477ce20206d0c8ace`。浏览器下载与该文件逐字节一致。工程备份恢复及再次导出均核对通过。目标SHA到照片验收集的本机绑定已登记，工程备份不包含原照片数据。

截图位于根目录 `工作台-最终训练设置.png`、`工作台-真实GPU训练日志.png`、`工作台-最终BIN效果对比.png`、`工作台-工程导出确认.png` 及最终工程截图。抽查照片总览与真实渐变，中文字体正常；首次图表生成因PingFang路径不存在失败，修正为本机Arial Unicode后续跑，无数据丢失。

## 原版 Edit 指令与限制

`交付/Edit-Gamma129-复验.json`：原版Edit ARM64指令离线回放14个案例，每例65536项；CPU匹配Edit、MPS匹配CPU，守卫完整。使用摘要绑定的576字节CP Gamma记录，未验证完整CP文件，不代表完整ISP或机内插值验收。

所有照片仍使用冻结RAW近似前端、原有+1.1EV元数据对齐和网格响应模型。训练/预览/验收共用模型不能替代相机直出。主工作台仅127.0.0.1:4180；没有连接相机。具体数值、来源、可见差异和剩余风险见交付报告。

## 后续可行性研究与累计覆盖修复（revision /4）

后续研究目录 `/Users/wenruli/Desktop/索尼/ColorLab-全通过可行性优化-20261114`，包含原生固定/回缩、完整区域保护、GPU有限差分和整数MILP投影。没有找到同时通过全部累计检查的三款新配方，未调用发布脚本替换原BIN或工程。原来“某轮通过”不能解释为所有历史及新增用例均通过。

发现并修复相位集合替换问题：稳健阶段应保留 .17/.53/.87 并追加16组，共19组。新增回归先RED（缺少累积接口），修复后GREEN；定向回归 `test_native_active_curves test_native_cached_forward test_native_joint test_native_joint_workbench test_native_conditional_grid test_native_joint_integer_log test_native_joint_photo test_hybrid_update`：29 passed、16 subtests passed。node语法和diff空白检查通过。实际CPU反例：旧16组会放行的暖金候选，在新19组正确报告 `dense:0.17:native-saturation:max`，回执为研究目录 `累计覆盖修复回归.json`。

主工作台确认无运行任务后重启至 /4。预算和原BIN格式不变，旧任务按保存的revision解释。研究各版本在改源码前已结束并完成其源码校验；/4仅是后续覆盖修复，不能把此前/3研究写成/4全量训练验收。完整区域/MILP仍为独立原型，不默认启用。
