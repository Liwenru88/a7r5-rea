# 镜头 AF 能力过滤

模块 ID 为 `lens-af-compat`，基线为 ILCE-7RM5 原厂 4.00。自动兼容模式下，三处镜头信息处理和两处能力发布改用适配的兼容标志读取器，保留镜头已经上报的能力。原厂镜头分类、强制兼容模式和镜头通讯继续使用原厂逻辑。 [模块清单](module.json) · [五处调用和前像](src/lens_af.py)

单选时直接在原厂 CP 上编译和应用 `lens_af.S`。组合时以本次构建回执锁定 24 槽 CP。若启用纵横比，先接入拍摄模块，再应用 AF 的定长改动。构建器核对完整 CP 摘要、辅助代码空间及五处调用前像，等长替换 `nflasha8` 的 CP 文件。单选包归档另外更新 WBI 首扇区及分区校验表。 [共享组件构建器](../firmware-runtime/build_capture.py) · [Thumb 源码](src/lens_af.S)

在构建手册的公共环境中，将配置的 `modules` 设为 `["lens-af-compat"]`。组合时把该 ID 加入所需的 24 槽预设。执行 `plan`、`build` 和 `verify` 即可复刻。 [封包命令](../构建工程实施手册.md#第四阶段的镜头-af-与十档纵横比)

回放覆盖自动、强制兼容和强制不兼容分流，以及原生发布对实际能力位和零上报位的处理。实际镜头 AF-C、连拍和镜头上报仍需实镜验收。呼吸补偿和镜头专用校准由各自的原厂路径处理。 [回放测试](../firmware-runtime/tests/test_lens_af.py) · [阶段四回执](../tests/phase4-verification.json)
