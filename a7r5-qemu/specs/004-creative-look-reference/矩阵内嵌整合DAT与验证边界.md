# 矩阵内嵌整合DAT与验证边界

本轮按用户确认的收缩范围完成离线DAT：停止扩展PLL／硬件模型，仅核对矩阵加载范围、执行原厂参数逻辑与参考预览，并保留已有整合功能。**离线构建成功，不等于完整启动或实机更新通过。**

2026-10-23 状态：原整合包说明、DAT 及根 `analysis/` 内的回归记录已按用户要求删除，不能再作为下载或重跑入口。下文是此前交付的历史记录；项目内现存模拟材料及回执仍可用于离线验证，不据此恢复已删除的 DAT。

| 项目 | 当前结果 |
|---|---|
| 最终CP | `31f21cce9da148998c065ecf9d927e353d70a24ff245f2842cfa05cc21ce2c3b`，17,617,008字节 |
| 内嵌矩阵 | 保留等长布局、124字节复制器、2304字节供体、原矩阵展开和校准；仅profile54～57读取内嵌数据 |
| 原功能 | CP旧type1声音字节保留；AP、六款色表、Gamma及68份菜单资源保留 |
| 原生参数 | 最终CP20,016次矩阵对照通过；25项封包/声音/色表上传等回归通过 |
| Qt | Cocoa下18款外观、选图、实际相机JPG和正常关闭通过；42次请求含1次预期损坏图片拒绝 |
| 数值一致性 | 18款测试图及实际JPG的ST/FL2/FL3/BW/SE与原设置修复路径逐像素一致；不证明实拍色彩 |
| 加载 | 原NOR描述符和5MiB＋余段覆盖尾部暂存区，静态核对通过；外部链路未实际运行 |
| DAT | 两个FAT解析器、精确反向还原、最终解包、CRC/帧、RSA/OpenSSL及全部明文字节核对通过 |
| 实机 | 未连接、未写卡、未升级；完整CP、原厂ISP、发声及成片均未验证 |

默认参考入口现指向`build/look-materials-integrated-8wzq2z0r/`；上版配置保存在`session-compact-v2.json`。默认相机菜单模拟器及其运行清单未改。前轮未完成的PLL源码和构建历史冻结保留，本次验证使用固定默认QEMU的指令窗口，不依赖该硬件模型。

## 本轮证据索引

- `build/look-materials-integrated-8wzq2z0r/receipt.json`、`matrix-inline.json`、`load-audit.json`。
- `runs/look-inline-verify-h1ggrt53/result.json`：最终CP原生矩阵对照。
- `runs/look-qt-accept-hyewrgzm/result.json`：Qt和原设置路径像素一致性。
- `logs/look-dat-regression-zvslquof/`：53项相关回归。
- 父工程`analysis/matrix-inline-dat-20261022-01/regression.log`：25项封包/功能回归。
- 父工程`analysis/matrix-inline-dat-20261022-01/package-02/verification.json`：最终DAT。

此前`DAT-readiness.json`把完整CP启动作为离线封包门槛，本轮依用户明确确认拆分为“离线构建验收”和“实机准入”；旧判断原样保存在`DAT-readiness-before-scope-change.json`。没有把未完成启动改写成已完成，也没有用软件图或固定成功回复替代硬件证据。

版本保持非官方研究4.05；它是同版本的另一份候选，不代表机身已可接受同版本更新。DAT摘要为`45a97165cc2236ad6aadea24f42ba46bedb5ba1f69da96b8b3806c79ab34188c`。
