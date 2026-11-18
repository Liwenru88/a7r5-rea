# 第二十三批：原矩阵/CC1完整构造与两级插值

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-26`
- Status: `OFFLINE_NATIVE_COLOR_PARAMETERS_VERIFIED_FULL_MODEL_PENDING`

## 本轮交付

完成T08b2d2的限定离线范围。从原27/24项加法窗口推进到当前CP完整矩阵、CC1主域/第二域构造，再进入原`0x71b8a0`常规两级插值。新增原生C重建/增量/插值，与独立整数期待和原ARM指令消费逐字节对照。

已落实三端点及独立校准对角值、逐扇区/统一bank/内嵌表来源、CC1绝对/差分展开和修正顺序、旧六款构造后增量、两级Q8截位及有符号半入舍入。不支持的第二域保留原诊断停止，没有伪造成功。

**完整机内功能仍未完成。** 当前补齐的是原颜色参数构造和常规插值；真实运行属性/动态校准、显示sRGB桥、完整组合像素预测、20槽应用与EVF/JPG、菜单及机内存储仍待接入。

## 改动与实际验证

| 文件/证据 | 结果 |
|---|---|
| `native/af_color406.h/.c` | 三端点矩阵、CC1主/第二域、27/24/8项构造后增量与两级Q8插值；低半字和元数据保持、重叠/坏权重拒绝 |
| `a7filters/cp_color406.py` | 186组矩阵、66组主域、134组第二域（112完整返回、22诊断停止）、18组旧六款门控（108次完整调用）、180组原CC1完整插值 |
| `a7filters/native_joint.py` | 在已有`--joint-adapter`联验颜色扩展，成套及范围检查仍在CPU创建前；旧无颜色扩展的模块兼容 |
| `tests/test_native_color406.py` | 11项新测试，独立半字/舍入参考、元数据/源保持、别名拒绝和模块元数据边界 |
| [相关回归](../../../.local/fixed-custom-filters/pytest-23.json) | 241 passed in 9.21s，命令9.533秒，退出0且源码未变 |
| [ASan/UBSan](../../../.local/fixed-custom-filters/sanitizer-23.json) | 20000次含随机颜色端点/插值探测；编译1.986秒、运行1.099秒，退出0 |
| [完整审计](../../../.local/fixed-custom-filters/cp-ui-access-406-23.json)与[命令](../../../.local/fixed-custom-filters/audit-23.json) | 155.753秒，修改4.06验签、736841帧/147成员/71目标/103资源，原24分支/1218刷新/864快照保持 |
| 同报告`native_joint_core.native_color_context` | 原完整函数、新AArch64与独立期待一致；目标契约127检查；既有Gamma126组和导入2273检查结果保持 |

控制流、数据来源、诊断边界和模型适用范围见[颜色构造与插值消费](color-parameters-23.md)。本包内嵌系数来自当前CP，普通属性/校准/阈值为显式夹具；完整构造和参数插值均不代表ISP像素或机身标定。

## 构建与复算

最终研究ELF [joint-converter.elf](../../../.local/fixed-custom-filters/build-23-color-verified/joint-converter.elf) 为121880字节，SHA-256 `5a4f4ca80390db3288c37da6c28bb70052498aa6efc3dbdf6529a764e90f8bc4`，[构建回执](../../../.local/fixed-custom-filters/build-23-color-verified/commands.json)记录22条编译/链接及源/头文件摘要。链接删除局部符号，保留所有全局验证入口和原RX/RW分离，不放宽128KiB文件或1MiB映射预算。初版构建和探测保持，只有最终构建绑定当前源码。

完整复算仍沿用[第二十批命令](continuation-20.md)，将`--joint-adapter`指向本批最终ELF，`--report`换为不存在的新路径。回归命令为`.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests`，复用现有虚拟环境及捆绑依赖，未安装新包。

保留[测试先行失败](../../../.local/fixed-custom-filters/color-23-red.txt)和[最终原指令先行探测](../../../.local/fixed-custom-filters/native-color-23-final.json)。最终源码/文档/输入、所有历史产物及引用核对见[本批指纹](../../../.local/fixed-custom-filters/verification-continuation-23.json)。

未操作相机、USB、SSH或真实SD，未读取私钥、修改输入DAT/冻结材料、生成安装固件或暂存/提交/推送。并行出现的其他QEMU实验目录保持原样；未介入其运行。T08b2d、T08、实际成像/菜单/机内保存总体继续`NOT_VERIFIED`。
