# 24 槽组内记忆

选择 `look24-group-memory` 后，原厂组和自定义组各自记住本次开机中最后应用成功的外观。记录失效时回到首个有效项。该模块自动引入预览和基础运行时。

预览开启但省略本模块时，每次切组都从首个有效项开始。跨开机恢复由独立的选择恢复模块管理。

[模块清单](../../../look24-group-memory/module.json) · [定向测试](../../../firmware-runtime/tests/test_module_options.py)
