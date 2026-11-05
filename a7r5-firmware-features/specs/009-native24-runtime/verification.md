# 二十四槽运行时验证

Feature ID: 009-native24-runtime
Status: NOT_VERIFIED
Updated: 2026-11-03

本阶段离线实施和有限验证完成，无新DAT、不连接设备。18项CPU／解码测试和2项QEMU身份检查通过，96原帧逐像素一致。完整原E4、实际色彩和真实共享堆余量未验收，整体NOT_VERIFIED。

| Acceptance | Status | Evidence |
|---|---|---|
| AC-001 | PASS（离线） | E-001／E-002：947000布局、原窗口7540字节、旧协议双向拒绝、两类堆失败保留；真实堆MANUAL_REQUIRED |
| AC-002 | PASS（CPU） | E-002：新AP真实线程、旧v4、0／13／24无卡冷启动和休眠复用、高槽边车发布失败真实回退及重试；完整机身电源／介质MANUAL_REQUIRED |
| AC-003 | PASS（CPU及有限菜单） | E-002／E-003：43行、86次双向导航、24款事务／标题、48图标、合并及原厂退出；实际应用／颜色MANUAL_REQUIRED |
| AC-004 | PASS（局部机器码） | E-002：新组件上的本地四项及原厂路线；实机声音／照片覆盖／色彩MANUAL_REQUIRED |
| AC-005 | PASS（归档与限制） | E-004：来源／摘要／原帧及退出；未生成DAT、未操作设备、合成配方标记明确 |

| Evidence | Code State | Command / Step | Result | Scope |
|---|---|---|---|---|
| E-001 | AP c4efcaa0…／CP31f85fa3… | 根目录`.venv/bin/python .../native24-combined/build.py --output .local/native24-runtime-20261103-05` | exit 0，前像／逆还原／不重叠通过 | 新独立组件，无DAT；前四次中间／失败候选保留 |
| E-002 | 同一新AP／CP＋最终测试源 | `A7R5_NATIVE24_BUILD=... .venv/bin/python -m pytest .../test_runtime.py`，追加资源／持久化及图标定向验证 | 15＋1＋1＋1＝18通过 | 真实AP／CP与文件协议，原E4外部执行／OS／UI服务夹具明确 |
| E-003 | `native24-menu-20261103-02`／`rsdd3lr1` | QEMU目录自身`.venv`，2项unittest；真实Qt前台设置、UP24／DOWN24、原厂与MENU往返 | 2项通过，96帧逐像素一致，三侧退出0 | 仅菜单／真实失败闭环；最后命令3、AP／CP／文件0，不是滤镜实际成功 |
| E-004 | 归档组件及冻结源 | 上游331文件、旧DAT／旧AP、22派生文件、原帧及来源检查 | PASS | 旧交付保持，实际堆／成像与新增真实配方未验证 |

完整命令、XML、组件、源码、图形、原帧、失败现场和剩余门禁见[本轮归档](../../native24-combined/verification/2026-11-03-01/README.md)。008原型、旧005／006记录保持，不以本轮离线任务完成覆盖其整机缺口。
