# FL2／FL3 创意外观

模块 ID 为 `look-fl2-fl3`，支持 ILCE-7RM5 原厂 4.00。FL2、FL3 成组开放，在创意外观原厂组内选择。使用原厂能力表和选择器，选择值分别映射到 CP 的 19、20，重置使用各自的默认值。CP 载入对应 CC1、矩阵和 Gamma。 [模块清单](module.json) · [色彩参数与来源](01_FL2和FL3启用实施细节.md)

单选由原厂组件生成，输出版本设为 4.06 时与历史单项包逐字节一致。与 24 槽共存时，构建器在同一套 CP 上分配查表入口，原厂组继续走原厂和 FL2／FL3 行，24 槽走其 SD 配方行。可同时启用 C1–C6。 [原厂单项构建器](../native24-combined/build_stock_color.py) · [24 槽适配](../native24-combined/stock400.py)

按构建手册准备 `root`、`py`、`stock` 和 `out`。单项配置的 `modules` 数组仅填 `look-fl2-fl3`。共存可从第三阶段预设开始选择。运行 `compose.py plan` 核对所选模块，运行 `build` 封包，再运行 `verify` 从原厂基底独立复验。 [构建命令](../构建工程实施手册.md#第三阶段的创意外观) · [共存预设](../presets/phase3-look24-fl23-factory-six.json) · [历史资源摘要](../independent/profiles/fl2-fl3/resources.json)

第三阶段回放核对了 CP 矩阵和 Gamma 相对 4.17 的数值一致性，以及 SD 槽切回原厂组。真实取景和成片仍需实机验收。 [回放用例](../native24-combined/tests/test_color_modules.py) · [离线回执](../tests/phase3-verification.json)
