# 24 槽切组与浏览预览

选择 `look24-preview` 后，横竖屏按映射方向切组，自动预览目标项。快速浏览只保留最后待处理目标，继续通过原有应用事务与中键确认。

省略该模块时，切组和上下浏览仍能移动高亮，中键才提交目标。已启用的滤镜在浏览时保留。启用调参但关闭预览时，自定义项先确认应用，再进入调参。

[模块清单](../../../look24-preview/module.json) · [分组交互](../../../firmware-runtime/runtime/unified-look.c) · [定向测试](../../../firmware-runtime/tests/test_module_options.py)
