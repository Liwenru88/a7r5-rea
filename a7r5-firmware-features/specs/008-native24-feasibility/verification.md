# 二十四槽原型验证

Feature ID: 008-native24-feasibility
Status: VERIFIED
Scope: OFFLINE_PROTOTYPE_ONLY
Runtime Status: NOT_IMPLEMENTED
Updated: 2026-11-03

本阶段离线原型已验证；尚无二十四槽运行时、菜单或升级包。这里的VERIFIED只覆盖下表原型验收，不能解释为机身可用、24款真实色彩通过或原整合固件的未验收项已关闭。

| Acceptance | Status | Evidence |
|---|---|---|
| AC-001 | PASS | E-001：三目标布局一致，24槽947000字节；ARM32／AArch64实际执行写入、哨兵和24个Gamma指针读取 |
| AC-002 | PASS | E-002：原29552字节BIN完整保留；完整／稀疏v5、旧读取器拒绝及损坏原子拒绝 |
| AC-003 | PASS | E-002：0～12原字节保持，13～24候选区分格式，旧读取器及损坏拒绝 |
| AC-004 | PASS | E-003：上游331文件、原AP／CP和两个DAT核对保持；原型、测试和待接线门禁独立归档 |

| Evidence | Code State | Command / Step | Result | Scope |
|---|---|---|---|---|
| E-001 | 冻结上游＋独立layout.c／受限派生头文件 | `prepare.py --output .local/native24-feasibility-20261103-01`；最终pytest中的布局两参数场景 | 6次编译exit 0；两目标执行一致 | 编译布局及隔离，不执行原CP固件消费者 |
| E-002 | build.json固定对象＋归档测试源 | `A7R5_NATIVE24_PROTOTYPE_BUILD=... A7R5_NATIVE24_EVIDENCE=... .venv/bin/python -m pytest -q a7r5-firmware-features/native24-combined/dependencies/native24-format/tests/test_prototype.py --junitxml=.../final.xml` | 15 passed，0.20秒，exit 0 | 与E-001共用一次最终模块验证；文件格式原型，不接线程／传输／菜单 |
| E-003 | 当前旧AP e833…／CP bb8…及冻结快照 | 来源／输出摘要、旧DAT和文档引用检查 | PASS | 未写相机、未迁移配置、未改当前固件 |

命令完整参数、对象、原型源码、内存区域表、测试XML及待实现门禁见[本次归档](../../native24-combined/dependencies/native24-format/verification/2026-11-03-01/README.md)。1 MiB只是显式测试预算；单库余101576字节，不能装两份完整24槽库，也没有实机剩余堆证据。
