# 第二十四批：完整矩阵消费与动态校准

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-26`
- Status: `OFFLINE_NATIVE_COLOR_CONSUMPTION_VERIFIED_FULL_PIPELINE_PENDING`

## 本轮交付

完成T08b2d3的限定离线范围。新增动态CC1校准解码和矩阵专用两级Q8消费，原矩阵完整函数的16扇区输出、首扇区状态副本、独立整数期待和新AArch64逐字节一致。校准门控、前4项有符号/后4项无符号和禁用时不写分别验证。

同时跑通原包装器的“选择外观→CC1→矩阵”前缀，在网格入口前停止。确认颜色profile与矩阵校准profile来自两个独立字段；不完整上游上下文会使FL2/FL3的颜色身份已变化而矩阵仍为ST。这是接入必须处理的约束，不是相机原厂故障结论。

**完整机内功能仍未完成。** 新增的是实际原指令参数消费证据和对应原生算子；上游身份/权重生产器、完整网格对象、真实联合像素模型、EVF/JPG、原厂菜单及机内存储仍有实现缺口。

## 改动与验证

| 文件/证据 | 结果 |
|---|---|
| `native/af_color406.h/.c` | 新增`af_color406_adjust`和`af_color406_matrix_blend`；矩阵差分舍入与CC1首级截位分开，失败不发布 |
| `a7filters/cp_color_consumption406.py` | 6组完整校准门控、24组完整主域及24次完整第二域；72组完整矩阵×16扇区，共1152扇区 |
| 原`0x719ef6`前缀 | ST/FL2/FL3三组到网格前停止；双profile字段及矩阵不同的反例固化 |
| `a7filters/native_joint.py` | 新消费扩展成套/范围在CPU创建前校验；旧模块不含新扩展时兼容 |
| `tests/test_native_color406.py`及原生目标契约 | 17项定向测试；新增独立有理数舍入/门控符号/失败不发布/入口元数据验证，目标168检查 |
| [相关回归](../../../.local/fixed-custom-filters/pytest-24.json) | 247 passed in 9.18s，命令9.413秒、退出0且源码未变 |
| [ASan/UBSan](../../../.local/fixed-custom-filters/sanitizer-24.json) | 20000次含动态字节和矩阵混合探测；编译1.921秒/运行1.133秒，退出0 |
| [完整同包审计](../../../.local/fixed-custom-filters/cp-ui-access-406-24.json)及[命令](../../../.local/fixed-custom-filters/audit-24.json) | 156.399秒，修改4.06验签/736841帧/147成员/71目标/103资源；原24分支、1218刷新、864快照保持 |
| 同报告`native_joint_core` | 原Gamma、联合求解1871检查、导入2273检查和既有颜色/网格结果保持，新增`native_color_consumption`；真实模型和硬件标志均为false |

详细地址、五项权重到四项接口映射、精确舍入、动态来源及原身份反例见[原颜色消费与身份约束](color-consumption-24.md)。

## 失败边界和剩余接入

整包装器尝试因缺少`pipeline+0x10`原网格对象，在`0x230de6`写空对象时停止，保留[失败现场](../../../.local/fixed-custom-filters/wrapper-24-boundary.json)。未增加映射、未伪造服务/返回。最终联验只声明网格前缀和独立完整矩阵函数，未声称整包装器成功。

下一步优先追踪`[root+4]+0x25`及关联权重/基底的上游生产器、`pipeline+0x10`对象构造和原网格查询/缓存寿命，在同一个原上下文验证整组应用。完整显示sRGB桥、四组件像素预测与实测留出误差仍是联合拟合前提，合成后端不能默认替代。

## 产物与复算

最终研究ELF [joint-converter.elf](../../../.local/fixed-custom-filters/build-24-color-consumption/joint-converter.elf)为121976字节，SHA-256 `63ca195c0e0bae9a75d8bb19c7a85f471eee7f02d30f42d36ec7c490e64e60c4`。[22条构建命令及源码摘要](../../../.local/fixed-custom-filters/build-24-color-consumption/commands.json)保留所有全局验证入口，原128KiB文件、1MiB映射预算及RX/RW分离不变。

复算沿用[第二十批完整命令](continuation-20.md)，只将`--joint-adapter`换成本批ELF并为`--report`选择不存在的新普通路径。回归仍用现有`.venv`与桌面捆绑依赖，不安装新包。初始4项缺实现失败见[测试先行回执](../../../.local/fixed-custom-filters/color-24-red.json)；早期原指令探测单独保留为probe，最终来源以完整同包审计为准。

最终[源码/文档/输入与历史指纹](../../../.local/fixed-custom-filters/verification-continuation-24.json)核对当前证据和既有产物。未修改输入DAT、冻结材料或QEMU其他任务；未操作相机/USB/SSH/真实SD、读取私钥、生成安装固件、暂存/提交/推送。T08b2d、T08、实际取景/JPG、界面和机内保存总体继续`NOT_VERIFIED`。
