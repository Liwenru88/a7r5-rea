# 参考项目、致谢与许可

当前项目包含 v4.5 色卡与色彩训练台、网格标定工具及相关技术文档。训练默认采用本项目的 R5 实拍 v2 响应；固件与刷写工作台在 [独立固件仓库](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware) 维护。

- [QAQLeonard/a7c2-fl23-research](https://github.com/QAQLeonard/a7c2-fl23-research)：参考原生 5×9×9 网格、颜色参数及响应拟合方法。保留的参考资料和 MIT 许可见 [来源目录](R5ColorLab/data/qaq/PROVENANCE.md)。
- [Erlla/sony-a7m4-custom-firmware](https://github.com/Erlla/sony-a7m4-custom-firmware/tree/086df3b1e33dfa0206553ac2bb003535c58ddb80)：参考 FL2／FL3 适配与颜色参数处理方法。[MIT 许可](licenses/Erlla-MIT.txt)。
- [shenmintao/Raw-Alchemy](https://github.com/shenmintao/Raw-Alchemy/tree/v0.6.2)：RAW、工作色域及 S-Log3 数值链参考，保留 [AGPL v3 许可](licenses/Raw-Alchemy-AGPL-3.0.txt)。
- [Colour](https://github.com/colour-science/colour)：色域矩阵与传递函数的独立数值核对，保留 [BSD-3-Clause 许可](licenses/Colour-BSD-3-Clause.txt)。

[R5ColorLab](R5ColorLab/LICENSE) 与 [R5GridCalibrator](R5GridCalibrator/LICENSE) 使用 GNU AGPL v3；QAQ 等第三方材料保留各自许可证，其他文件依其声明或根目录 [MIT 许可](LICENSE)。详细数据来源见 [PROVENANCE](R5ColorLab/PROVENANCE.md)，第三方许可原文保存在各目录及 licenses/。

NumPy、SciPy、Pillow、rawpy／LibRaw、PyTorch 等依赖分别遵循各自许可。Sony Imaging Edge 仅用于本地研究，不随项目分发。R5 实拍响应覆盖有限区域，其余区域外推；RAW 预览仍为近似，不能视为完整机内 ISP 等价验证。滤镜名称用于说明模拟目标，非品牌官方产品；项目不分发用户目标照片、签名私钥或完整原厂固件。
