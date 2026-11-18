# AWB 优先参数模板

基于原厂 4.00，只移植上游白色优先 97、氛围优先 −1 的通用模板字段。AP 菜单继续走原厂逻辑。

## 实施与资源

从 `colour_fields.json` 选择 `purpose == "AWB priority"` 的一段。它位于属性 `0x02a40000` 的相对偏移 `0x930`，字节为 `61 ff`。对十二个已锁定的 GL 模板调用 `patch_template`，验证局部范围、重新计算 BK4 bank 校验，再由 DAT 工具更新外层 `backup.sum`。原有用户记录、模板内其他字段和原厂 AP／CP 字节保留。

[字段资源](../../../native24-combined/dependencies/native12-combined/upstream/firmware/r5/src/dependencies/colour_fields.json) · [模板源码](../../../native24-combined/dependencies/native12-combined/upstream/firmware/r5/src/templates/prepare_templates.py) · [资源清单](resources.json)

## 复现与验收

完成[公共准备](../../README.md#公共准备)后执行。

```sh
"$python" -B "$tool" awb-priority --base "$stock" --output "$out/awb-priority"
```

校验十二地区的字段和值，实机验收应区分既有设置保留和原厂模板初始化的行为。 [本轮封包回执](verification.json)
