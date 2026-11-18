# R6 ST 颜色参数模板

基于原厂 4.00，只移植上游 R6 ST 的两段颜色字段。适用对象是升级归档内的十二份地区通用 GL 模板。机身当前用户数据是否会吸收该模板，取决于原厂更新和恢复流程。

## 实施与资源

从 `colour_fields.json` 选择 `purpose == "R6 ST"` 的两段，分别写入 CC1 属性 `0x02a40001` 和矩阵属性 `0x02a4000d`。调用原模板处理器的 `patch_template`，核对每个原厂模板的完整摘要、双 BK4 bank 布局、范围和属性，更新受影响的内部校验。第二次应用要得到相同结果。DAT 工具另重算 `backup.sum`。

[字段资源](../../../native24-combined/dependencies/native12-combined/upstream/firmware/r5/src/dependencies/colour_fields.json) · [模板源码](../../../native24-combined/dependencies/native12-combined/upstream/firmware/r5/src/templates/prepare_templates.py) · [资源清单](resources.json)

## 复现与验收

完成[公共准备](../../README.md#公共准备)后执行。

```sh
"$python" -B "$tool" r6-st --base "$stock" --output "$out/r6-st"
```

变化应仅见十二份模板及 `backup.sum`。该包不含 AP／CP 新功能，ST 的机身生效时点和实际色彩需单独观察。 [本轮封包回执](verification.json)
