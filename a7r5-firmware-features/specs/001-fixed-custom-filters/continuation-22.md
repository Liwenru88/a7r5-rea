# 第二十二批：联合候选到保存、恢复和管理事务

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-26`
- Status: `OFFLINE_IMPORT_TRANSACTION_VERIFIED_REAL_INTEGRATION_PENDING`

## 本轮交付

完成T08b3a与T09a的限定离线范围。新增原生C协调器将CUBE解析、四组件搜索、独立留出误差、完整配方、候选文档与既有双副本保存串联。新增重命名/完整导出，保留工作值和报告基准；候选失败或取消不修改槽位，发布不确定继续冻结。

真实目录链已验证：导入C20→八项调参→重命名→保存/工作双导出→保存→另存C07→清空C20→擦除源CUBE和候选→新目录恢复完整四组件。AArch64实际运行同类事务的2273项检查，内存存储夹具和主机普通目录证据分开。

**完整机内功能尚未完成。** 缺口仍包括真实联合颜色模型/sRGB桥、20槽的完整成像应用、EVF/JPG版本/帧寿命、可信机内存储、原厂菜单及动态名称/文件浏览。现有测试不能代替这些接入，也不代表仅剩真机验收。

## 改动与验证

| 文件/证据 | 结果 |
|---|---|
| `native/af_joint_asset.*` | 1943字节显式小端配方，完整Gamma/矩阵/CC1/网格，当前CP/模型/基底和整份SHA；最终Gamma与仅研究标志 |
| `native/af_joint_report.*`、`af_grid_fit.c` | 同一完整后端的独立颜色报告；24色非零误差/P95/裁剪与独立标量数学对照 |
| `native/af_import.*` | CUBE→搜索→留出→封装→候选，只在完整成功后发布；无默认模型、无文件或设备接口 |
| `native/af_persist.*` | 重命名保留未保存参数、显式导出保存/工作参数、重叠/容量/不确定拒绝 |
| `tests/test_native_import.py` | 新增20项覆盖完整普通目录链、载荷/模型/版本、取消、非零误差及输出隔离 |
| [相关回归](../../../.local/fixed-custom-filters/pytest-22.json) | 230 passed in 8.78s，命令9.023秒，退出0且源码未变 |
| [ASan/UBSan](../../../.local/fixed-custom-filters/sanitizer-22.json) | 20000次含整份配方损坏探测，目标事务同源主机执行；编译1.819秒、运行1.231秒，退出0 |
| [同包审计](../../../.local/fixed-custom-filters/cp-ui-access-406-22.json)及[命令](../../../.local/fixed-custom-filters/audit-22.json) | 150.084秒，修改4.06验签、736841帧/147成员/71目标/103资源，原24分支/1218刷新/864快照保持 |
| 同报告`native_joint_core.offline_import_transaction` | AArch64 2273检查，工作区146948字节、候选2236字节、完整载荷1943字节，取消和存储代号5恢复通过 |

全部新增代码可在目标架构编译运行，但未安装到AP/CP。合成模型8训练色和4留出色均可表达目标，误差为0；这只证明合成模型和接口，不是实拍精度。真实基底/参数/域标定缺失时不回退到合成模型。数学、预算、格式和后续接入详见[导入与管理事务](import-transaction-22.md)。

## 构建与复算

最终研究ELF [joint-converter.elf](../../../.local/fixed-custom-filters/build-22-import-verified/joint-converter.elf) 为123672字节，SHA-256 `11efa51e9ebf3b780d8a25a8637f5e3c82af2f71d1bea50b509ef7be3bd6343f`，[回执](../../../.local/fixed-custom-filters/build-22-import-verified/commands.json)记录20条编译/链接及来源。初版构建保留，未覆盖历史ELF；只有最终构建与当前源码匹配。

沿用[第二十批完整命令](continuation-20.md)，将`--joint-adapter`指向最终研究ELF，`--report`换成不存在的新路径即可重算完整同包审计。回归命令仍是`.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests`；使用原有虚拟环境和捆绑依赖，未安装新包。执行器的导入扩展入口必须成套且在CPU创建前通过地址范围检查，旧ELF继续兼容。

测试先行的[缺组件失败回执](../../../.local/fixed-custom-filters/import-22-red.txt)、[目标先行执行](../../../.local/fixed-custom-filters/import-22-native-initial.json)、最终源码/文档/输入及历史产物核对见[本批指纹](../../../.local/fixed-custom-filters/verification-continuation-22.json)。

未操作相机、USB、SSH或真实SD，未读取私钥、修改输入DAT/冻结材料、生成安装固件或暂存/提交/推送。T08b3、T08、T09和完整功能总体保持`NOT_VERIFIED`。
