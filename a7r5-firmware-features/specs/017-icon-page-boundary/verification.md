# 验证记录

Status: OFFLINE_REPAIR_VERIFIED_DEVICE_NOT_VERIFIED

本轮明确离线，未连接或写入相机；未生成DAT。详见[分析报告](离线分析与修复.md)和[组件归档](../../native24-combined/verification/2026-11-04-icon-pages-01/README.md)。

| 执行项 | 结果 | 原始证据 |
|---|---|---|
| 旧4.14逐块回归 | 预期失败：新增块5600≠4096＋1504；原厂全集通过 | `.local/incident414-offline-20261104-01/before-pages.log`及XML |
| test_icon_pages.py＋test_icons.py | 7 PASS，9.17秒 | `after-icons.log`及XML |
| test_build_contract.py＋test_tabs.py | 16 PASS，13.23秒，sources_unchanged=true | `cpu.log`、`cpu/session-result.json`及XML |
| 新QEMU固定身份 | 2 PASS，0.194秒 | `qemu-identity.log` |
| 实际Qt／原帧／退出 | 103动作／103原帧PASS，Qt／AP／CP退出0 | `qemu-proof.json`、运行`native-native12-410-yzssneml` |
| 原厂全样本 | 7022份载荷／39869块均符合分块规则 | `block-audit.json` |
| 组件兼容／独立重建 | 两次四组件相同；AP、CP与4.14相同，仅两份图标变化 | `compatibility.json`、两份build.json |

实际命令的根Python为`.venv/bin/python`，QEMU子项目使用自身`.venv`并设置`PYTHONPATH=tools`。资源构建输出为`.local/native24-pages-20261104-02`和`...-03`。CPU命令设置`A7R5_NATIVE24_BUILD`到`...-02`；QEMU输入为`a7r5-qemu/build/native24-tabs-pages-20261104-01/manifest.json`。

23项是本轮实际定向回归总数；此前82项全套仅按相同AP／CP二进制复用，未宣称本轮重跑全套。QEMU仍有E4／硬件／成像边界，新页面门禁不是完整LDEC仿真。当前机身结论仅为用户确认的4.14失败报告，没有本轮新异常栈、文件回读或功能验收。

旧包校验清单、历史归档和原测试回执不修改。首轮构建因测试生成的字节码缓存被门禁拒绝，该缓存已限定清理且改为内存加载；后续原快照校验及独立重建通过。
