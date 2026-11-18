# 验证记录

Status: VERIFIED
Updated: 2026-11-15

## 范围与环境

Python 使用项目 `.venv`，真实 GPU 为 Apple Metal/MPS。未新增依赖、连接相机、改固件、提交或推送。原工程及十五款交付库不自动替换，新增产物位于 `/Users/wenruli/Desktop/索尼/ColorLab-统一C训练验证-20261115`。

## V1 / V2 已执行

- 新回归先 RED：旧请求仍走旧算法、没有强制候选选择器、终检失败回退原配方。实现后 GREEN。
- `PYTHONPATH=tests:web:scripts .venv/bin/python -B -m pytest tests/test_forced_native_training.py tests/test_native_joint.py tests/test_native_joint_workbench.py tests/test_native_feasible_experiment.py tests/test_native_gamma129.py tests/test_native_conditional_grid.py tests/test_native_full_photos.py tests/test_native_colour_guard.py tests/test_native_active_curves.py tests/test_native_cached_forward.py tests/test_native_joint_photo.py tests/test_native_joint_integer_log.py tests/test_packed_selection.py tests/test_hybrid_update.py tests/test_integrated_training.py tests/test_file_storage.py tests/test_export_policy423.py tests/test_compression_workflow.py tests/test_batch_training.py tests/test_live_progress.py --import-mode=importlib -q --tb=short`：96 passed、61 subtests passed、1 skipped。跳过为 `test_compression_workflow.py` 的历史数值夹具缺失。
- `node --check web/static/app.js`、`node --check web/static/workspace.js` 通过；直接执行页面实际 `qualitySummary`，确认新策略失败显示“仍可保存和导出”，历史策略仍显示原来回退语义。
- 真实 v4.5 输入经过 `core.prepare_target` 的 S-Gamut3.Cine identity LUT 生成后成功进入同一 `native_joint.Data`：TRAIN 64562、VALID 17467、TEST 17343，目标有限且在0–1。回执 `LUT输入适配.json`。没有宣称整条 LUT GPU 训练已复测。
- 回归覆盖：品质失败仍保存新候选、基准及仅改名配方排除、非法 BIN/身份冲突/非有限值拒绝、开发照片评分不因诊断短路而变化、取消停止发布、历史重试与批量统一 C、编解码和旧历史模型读取。

## 真实 MPS 链路

运行 `tests/verify_native_joint_smoke.py`，真实暖金日光 TIFF、相同 v4.5 数据、六张开发照片和四张历史留出照片；隔离目录 `GPU链路`。预算为 C200、条件网格50、整数1轮、完整开发照片50、稳健1×20；只缩减预算和替代上传寻址，不替代数值求解器。

任务 `c31c14ed96474521acfd7835c2ae5c8a` 实跑726.90秒，状态done。候选池86项，同时保留早期C与末段稳健修复候选，选择 `robust-r1/conditional/20/a0.5`，其四组参数与冻结基准不同。开发阶段有10条双域过渡max超限，独立终检有2条，`quality_passed=false`；`adopted=true`、`retained_baseline=false`、`export_allowed=true`。因此真实覆盖了“质量失败仍保存新结果”的分支，没有用回退结果伪装验证。

最终 BIN SHA256 `494826139b73dde913d46f97a178955ea8e15ff2dfd836e916c9f889f1610a15`；编解码往返、`selected.BIN`解码配方与任务输出、预览runtime与导出、来源校验均一致。条件网格/完整照片/稳健修复CPU/MPS最大差分别1.0568e-7、1.0470e-7、9.5715e-8，均低于2e-6门限。66条真实Loss/整数阶段事件保留。见 `GPU链路/summary.json` 和各阶段审计。

## 工作台页面与导出

隔离服务 `127.0.0.1:4181` 读取测试运行目录，不启动/改写原工作台工程。真实页面核对：色卡和LUT只有C入口；当前预算/警告清楚显示；载入上述历史结果时页面显示“已采用本次 C 新配方，质量验收未全部通过，仍可保存和导出”，开发与独立终检失败项均显示，浏览器没有error/warn日志。

通过页面保存到隔离工程第24槽，刷新后仍为已保存；通过页面导出标准配置包，实际下载的BIN与训练输出逐字节相同。回执为 `页面导出复验.json`，截图为 `工作台-统一C入口.jpg`、`工作台-新配方质量警告.jpg`。复验发现并修正了三处沿用旧“自定义预算/采用门槛”的提示及一处“最终须通过”的旧文案；仅改前端文字，未更改已完成GPU运行的求解/发布代码。前端语法与相关模块验证已复跑。

完成后确认无训练任务，关闭测试服务；4180、4181均无监听。没有连接相机。现有交付库未自动重训或替换。

## 覆盖矩阵

| 验收 | 状态 | 证据 |
| --- | --- | --- |
| AC-1 单一入口和历史兼容 | PASS | 请求/服务/批量/历史模型回归，LUT真实适配 |
| AC-2 本次新候选与候选池 | PASS | 强制选择与旧基准排除回归；86项真实GPU候选池 |
| AC-3 品质失败可发布且留出隔离 | PASS | 回归与真实12项过渡失败分支仍发布新配方；未用留出重挑 |
| AC-4 合法性和一致性 | PASS | 非法值回归、实际BIN往返、预览一致、浏览器保存/下载逐字节核对 |
| AC-5 页面统一和警告 | PASS | 色卡/LUT单一C入口、橙色警告、实际保存导出与截图 |

此次为训练策略闭环，未重跑三款完整生产预算，也未重跑整条LUT GPU训练；LUT已验证真实输入适配，联合后续内核共用。没有证明数学全局最优、三款正式精度改善或实机验收。历史照片留出已在研究中出现，不能宣传为新盲测。
