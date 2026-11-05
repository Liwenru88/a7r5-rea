# 稳定性验证

Feature ID: 010-native24-stability
Status: NOT_VERIFIED

离线实施与授权范围内验证完成。最终AP `af7e99791309be845d1c981598b521f6766aca266a7ccae96a067e590bc4dbe3`，CP `35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300`。46项完整相关回归通过，2项QEMU身份检查通过，96原帧与PNG一致。没有生成DAT或操作设备，整体仍NOT_VERIFIED。

| Acceptance | Status | Evidence |
|---|---|---|
| AC-001 | PASS（CPU及有限界面） | E-002／E-003：丢ACK、双重失败、原对象在途、错误对象、ST恢复及实际需恢复提示 |
| AC-002 | PASS（CPU） | E-002：日志、R5SEL4／5读与6写、库身份、发布不确定及重启 |
| AC-003 | PASS（CPU及有限菜单） | E-002／E-003：512／37字节短读、0字节／同库、双卡2秒优先及旧库恢复 |
| AC-004 | PASS（CPU） | E-002：整体预算、早期双路径E4未就绪、显式原厂选择持久化、新epoch与最后输入 |
| AC-005 | PASS（模型与静态门禁） | E-001／E-002：NULL瞬时分配重试、旧库保留与回退、真实缓存资源诊断、RAM环和共享缓冲；真实堆与高水位MANUAL_REQUIRED |
| AC-006 | PASS（离线交付） | E-001～E-005：前像、连续账本、合同、逆还原、46项相关回归、96原帧、四组件重建一致及988文件归档 |

| Evidence | Code State | Command / Step | Result | Scope |
|---|---|---|---|---|
| E-001 | 当前AP／CP，`.local/native24-stable-20261103-12` | 根`.venv/bin/python .../native24-combined/build.py --output ... --inputs .../work/inputs` | exit0，AP BSS282145、RX61160、已知帧保守和1360；CP代码7544／单库947000 | 来源、工具链、反向核对、段与栈门禁；真实资源非实测 |
| E-002 | 同一当前组件及最终源码 | `A7R5_NATIVE24_BUILD=...-12 A7R5_NATIVE24_EVIDENCE=.../final-cpu .venv/bin/python -m pytest -q .../native24-combined/tests --junitxml=.../final-regression.xml` | 46通过，525.75秒；session-result PASS、full_related_suite、sources_unchanged均真 | OS／文件／UI／E4外部执行夹具；真实AP／CP指令 |
| E-003 | QEMU `native24-stable-menu-20261103-05`／`ekfna2tl` | QEMU自身`.venv`，2项unittest；`run_validation.py`实际QTest操作，96个动作含STOP | 96原帧与PNG一致；24双向遍历及原厂／MENU往返；worker／AP／CP退出0 | schema2、2328只读；原E4在途1，等待0／完成0／需要恢复1，未证明成像 |
| E-004 | 当前源、基底与工具链 | `.local/native24-stable-repro-20261103-01`重新构建；比较owned_sources、external_sources及四组件 | 全部一致 | 未使用旧缓存替代重编 |
| E-005 | E-001～004来源与当前源码 | 在QEMU现有Python环境执行`native24-combined/archive.py` | 988文件加SHA清单，压缩包重新读取核对通过；tar SHA `cf8dc76ab9d2c3e247efb3f3b7492f61460afcc052b982bbe4800c77dac38b12` | 研究组件包；无私钥／DAT，不可安装 |

完整回执、源码、目标文件和当前帧见[归档](../../native24-combined/verification/2026-11-03-stability-01/README.md)，用户可读说明见[交付说明](../../native24-combined/稳定性优化交付说明.md)。修复前预期失败XML在归档tests/cpu中保留，009和早期候选的通过结果不替代本轮最终身份。

真实E4完整初始化、LCD／EVF／JPEG、介质掉电、完整电源及安装验收为MANUAL_REQUIRED。本轮不进行相机、USB、SSH、实体SD或原始分区操作。
