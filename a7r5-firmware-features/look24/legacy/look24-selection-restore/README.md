# 24 槽跨开机选择恢复

选择 `look24-selection-restore` 后，成功应用的选择与配方库身份绑定并保存。冷启动用有效记录恢复，自定义编号失效时走原厂回退。保存失败沿用已应用状态。

省略本模块时，冷启动以原厂选择开始。当前会话的应用失败仍回退到上次成功项，暖恢复沿用会话状态。旧选择文件不参与当前选择，也不被覆盖。

[模块清单](../../../look24-selection-restore/module.json) · [事务实现](../../../native24-combined/runtime/r5_filter_runtime423.c) · [定向测试](../../../native24-combined/tests/test_module_options.py)
