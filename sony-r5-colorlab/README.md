# Sony R5 Color Lab

完整操作步骤见 [R5NATIVE.BIN使用说明：从训练到导出](R5NATIVE.BIN使用说明.md)。

本地已适配24槽，并安装PyTorch、默认启用Metal／MPS训练，见 [MPS训练与验证](MPS训练与离线验证.md) 和 [24槽格式说明](24槽适配说明.md)。以下保留上游说明；当前改动身份见 [MPS适配清单](MPS_ADAPTATION.json)，原24槽清单保留为历史记录。

Independent public color training, calibration and technical documentation project.

- [Color training workbench and launch instructions](R5ColorLab/README.md)
- [Training algorithm and settings](R5ColorLab/TRAINING.md)
- [Grid calibration workbench](R5GridCalibrator/README.md)
- [Technical research](analysis/)
- [Firmware and macOS flash workbench](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware)
- [Existing v4.5 application and synthetic charts download](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware/releases/tag/colorlab-v4.5)
- [Historical FUJ/v4.5 three-expert filters and export audit](filters/FUJ_12_v45_three_experts_20261102/)

本地训练工作台已于 2026-11-12 选择性更新到上游 `06c3557`：默认采用 Hybrid 响应，标准色卡训练使用“原生 12 起点 → 网格 5 轮 → 联合叠加 3 轮”。保留本地 24 槽工程、预览、色差统计和双版本导出。启动方式、正式参数、兼容范围和实测回执见 [Hybrid 更新与验证](Hybrid更新与验证.md)。已有滤镜没有重训或替换；历史任务继续按其保存的模型身份加载。网格标定工作台未在本次同步范围内。 后续本地 `/2` 修订已补上 [整数候选筛选和旧配方回退](R5ColorLab/PACKED_TRAINING.md)，应用于新启动的正式训练。

Migrated from firmware repository commit bf71d789262d53ff5fcd23d87aea5bdc07a46f19. Historical release assets stay at their original URLs; current training source and documentation are maintained here. Install each workbench using its own requirements.txt. No firmware build scripts or flash operations are part of this project.

Source licenses remain per directory: R5ColorLab/LICENSE and notices govern the training workbench; root MIT does not replace third-party or AGPL terms. See THIRD_PARTY_NOTICES.md and licenses/.
