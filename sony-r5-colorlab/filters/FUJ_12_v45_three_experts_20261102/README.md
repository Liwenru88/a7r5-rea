# FUJ/v4.5 三专家正式滤镜（2026-11-02）

这是使用 `r5-paired-20261102-three-experts` 网格响应和原生算子约束训练完成的 FUJ/v4.5 十二项滤镜批次。

- 批次：`3a240e968e7748c79217fffe19cdf24e`
- 状态：`done`
- 模型：ILCE-7RM5
- 三专家算子 SHA256：`3cecec3387acbd72524be42db34586237df0c2c7d458d4090467375d28fa0815`
- 数据集：`v4.5-sony100mp-5300k-sim-center5-20261029`
- 训练：精度优先、Metal/MPS 双并发、2000 评估、12 起点、8 动态轮、Gamma/颜色交替 3 轮、整数微调 3 轮、参数平滑 30、输出连续性 30
- 压缩目标：`fuji-target`
- 压缩后原生／网格交替：关闭
- 灰阶后处理微调：关闭
- BIN：`R5NATIVE.BIN`
- BIN 大小：29552 字节
- BIN SHA256：`b985c0d1e99c33681e5994a282372bc5bf8e7ec0c0811b56e87cd3cbd66b61c8`

滤镜顺序和名称为：AS / CC / EBB / ET / NC / NH / PV / RA / VN / 正片 / 负片 / Portra400。完整原生参数在 `native_config.json`，来源绑定和逐项导出校验在 `export_audit.json`，训练配置及目标散列在 `batch.json`。

目标图像本身、用户照片、运行时上传目录和中间训练缓存不随仓库发布。该 BIN 已通过本地导出审计；实机加载和跨场景成像仍需单独验收。
