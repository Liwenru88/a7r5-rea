# 第二十一批：原Gamma完整构造与联合候选的真实参数域

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-26`
- Status: `OFFLINE_NATIVE_GAMMA_DOMAIN_VERIFIED_FULL_COLOR_PENDING`

## 本轮交付

完成T08b2d1的限定离线范围。原Gamma完整选表/构造确认129点横轴是分段非均匀轴；新增C接口生成原轴、定位整数区间，并将完整候选129点写成保留附属字段的576字节记录。12个原厂外观和6款既有滤镜、各7列共126组与新AArch64输出一致。

8组ST/PT/FL2/FL3候选由原构造函数直接消费。另复现旧六款包装器会继续对完整候选叠加原tone；后续新增槽必须区分完整曲线与旧增量格式，不能重复处理。本批不改旧包装器或源Gamma表，所有替换只在匿名影子表中。

完整联合颜色模型仍未接入。已补的是原Gamma参数域，不是显示sRGB输入桥或ISP像素；T08b2d、T08、菜单/机内保存/实际成像继续未完成。

## 主要改动与有效验证

| 文件/证据 | 结果 |
|---|---|
| `native/af_gamma406.h/.c` | 非均匀轴、整数区间、完整曲线替换；非法/重叠/不足或多余分段拒绝，失败不发布 |
| `a7filters/cp_gamma406.py` | 原局部选择/完整构造126组、8组直接候选/1组旧tone继续处理、9组区间边界；影子载荷来源明确 |
| `a7filters/native_joint.py` | 在现有`--joint-adapter`中识别可选Gamma扩展，兼容旧模块；扩展符号完整性/地址范围在CPU前检查 |
| 新定向测试及`native_sanitizer.c` | 非均匀轴、末区间4095、附属字段/源保持、错误不发布、前像门控与扩展符号越界回归 |
| [相关回归](../../../.local/fixed-custom-filters/pytest-21.json) | 210 passed in 7.90s，命令8.135秒、退出0且源码未变 |
| [ASan/UBSan](../../../.local/fixed-custom-filters/sanitizer-21.json) | 20000次含Gamma域/联合核心探测；编译1.431秒、运行0.545秒、退出0 |
| [完整同包审计](../../../.local/fixed-custom-filters/cp-ui-access-406-21.json)与[命令](../../../.local/fixed-custom-filters/audit-21.json) | 153.548秒，修改4.06验签、736841帧、147成员、71目标及103资源，原24分支/1218刷新/864快照保持 |
| 同报告`native_joint_core.native_gamma_context` | 126组原选表/完整构造与AArch64原轴、9组候选边界和9组区间；其他联合/网格/握手/运行时结果保持 |

详细控制流、参数域、实际输入边界与后续接线要求见[Gamma真实参数域](gamma-domain-21.md)。源载荷只映射到显式匿名RAM；原引导复制/整机启动、硬件插值、像素和7列实际模式身份仍未验收。

## 构建、复现与发现

新研究ELF `build-21-gamma/joint-converter.elf`为80568字节，SHA-256 `0d5ca328d069c821cccc335a5d3f6d5e320ba62f5bb6e375897869b7a06ea600`，研究基址沿用0x9080000，仅用于隔离执行器。[构建回执](../../../.local/fixed-custom-filters/build-21-gamma/commands.json)记录7条编译/链接及源码/头指纹；旧产物不改。

复算沿用[第二十批完整命令](continuation-20.md)，将`--joint-adapter`改为上述新ELF，`--report`改为不存在的新路径。现有`.venv`和捆绑依赖不变，不安装新依赖。最终来源、源码、文档、历史产物及引用核对见[本批指纹](../../../.local/fixed-custom-filters/verification-continuation-21.json)。

新增组件先因缺失源码失败，保留[初始契约回执](../../../.local/fixed-custom-filters/gamma-21-red.txt)，实现后5项定向通过。检查可选符号时捕获扩展地址越界未在CPU创建前拒绝，先保留[失败回执](../../../.local/fixed-custom-filters/gamma-symbols-21-red.txt)，修正地址检查后回归及完整审计通过。[原指令先行探测](../../../.local/fixed-custom-filters/native-gamma-21-initial.json)与最终联合审计分列。

真实非均匀轴否定了直接均匀采样的实现假设；本批只给出区间分子/分母，未虚构硬件舍入。旧tone重复处理是匿名候选放入旧行后得到的原代码行为，不是相机已发生的错误；后续完整候选应用需显式区分语义，不能直接覆盖旧六槽数据。

下一步仍为Gamma域控制/sRGB桥、矩阵/CC1端点标定与原组合顺序，随后进行真实完整预测和独立联合误差，再接槽位与菜单持久化。未操作相机、USB、SSH或真实SD，未读私钥、修改输入DAT/冻结材料、生成安装固件或暂存/提交/推送。总体`NOT_VERIFIED`。
