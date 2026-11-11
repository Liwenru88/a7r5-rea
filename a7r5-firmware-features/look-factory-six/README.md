# C1–C6 六款内置滤镜

模块 ID 为 `look-factory-six`，支持 ILCE-7RM5 原厂 4.00。C1 至 C6 依次为 Classic Neg.、Classic Chrome、Nostalgic Neg.、Astia、GR Positive Film、GR Negative Film。六款随固件内置，在创意外观原厂组选择，沿用原厂调参页。SD 卡上的 `R5NATIVE.BIN` 由 24 槽模块使用。 [模块清单](module.json) · [六款配方资产](../materials/upstream-default-six)

单选沿用历史选择值 249–254 和六款色彩数据，输出版本设为 4.06 时与历史单项包逐字节一致。24 槽共存时，固定六款的 Gamma 行为 75–86，SD 槽为 51–74。共存变体在早期 CP 启动代码中单独映射色彩数据页。AP 合并选择器并在 68 份横竖语言资源中追加名称。 [原厂单项构建器](../native24-combined/build_stock_color.py) · [共存构建器](src/build_legacy_six.py) · [配方和语言资源锁](../materials/recipes.json)

按构建手册准备 `root`、`py`、`stock` 和 `out`。单项配置的 `modules` 数组仅填 `look-factory-six`。只与 24 槽组合时，从第三阶段预设移除 `look-fl2-fl3`。同时启用 FL2／FL3 时直接使用该预设。运行 `compose.py plan`、`build` 和 `verify`，核对计划、生成 DAT 并独立复验。 [构建命令](../构建工程实施手册.md#第三阶段的创意外观) · [共存预设](../presets/phase3-look24-fl23-factory-six.json) · [历史资源摘要](../independent/profiles/factory-six-stock/resources.json)

第三阶段回放核对了 CP 启动映射、六款的 Gamma、矩阵和色度，以及 24 个 SD 槽和原厂组往返。另从最终 DAT 解包核对了全部 68 份名称资源。机身首启、真实取景和成片仍需实机验收。 [历史实施细节](02_六款自定义滤镜实施细节.md) · [成像回放](../native24-combined/tests/test_color_modules.py) · [成包回归](../tests/test_compose_phase3.py) · [离线回执](../tests/phase3-verification.json)
