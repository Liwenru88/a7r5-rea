# 关闭指定 NTSC 提示

基于 ILCE-7RM5 原厂 4.00，复用已验证的两处 AArch64 分支替换。模块修改 AP 中的提示路径，PAL／NTSC 制式、帧率和其他警告由原厂控制。

在构建配置的 `modules` 中加入 `video-ntsc-prompt` 即可单选或与同阶段模块组合。清单内含两个定长补丁的前像和结果。构建器核对完整 AP 摘要并检查回读的 AP 与 ext2。单选用 4.06 包头复现历史单项包。

[模块清单](module.json) · [实施细节](03_关闭NTSC提示实施细节.md) · [构建与离线复验命令](../构建工程实施手册.md) · [历史单项与行为验证](../independent/profiles/ntsc/README.md)
