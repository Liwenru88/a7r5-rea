# integration58 创意外观入口重启：离线调查记录

日期：2026-11-02。任务 `T11ui59`、验收项 `AC-010-UI59` 未完成。用户选择“暂不连接相机，仅保留离线排查结果”。本次没有连接、读取、修改或重启相机，没有修改产品固件，没有生成修复升级包。

后续记录：用户此后重新明确授权SSH只读分析，已取得单独的[设备现场证据](incident-59-ssh-readonly.md)。本文件保留此前离线阶段的执行边界；新阶段没有触发复现、写入或重启相机，根因仍未确定。

## 已确认的故障与范围

用户确认刷入 integration58，进入原厂“创意外观”会死机重启，重启后正常。当前没有现场崩溃日志、重启原因或机身已安装文件摘要，无法确定故障进程和重启来源。

本地故障候选为 `.local/fixed-custom-filters/integration58-release410/update410/BODYDATA.DAT`，754525608 字节，SHA-256 为 `b1f3f35c7cd614fdc07b94971323cda5b25a14de6fbbc9e94ecf582bc8d17c37`。该摘要只标识本地文件，不证明机身安装内容完全一致。保留原候选和历史回执，停止推荐继续测试此候选。

integration56 与 integration58 的 AP、CP、四个动态库和70份资源功能载荷相同，已知差异仅为 USR 文件系统写入时间；不能将换回同载荷候选视为已验证修复。

## 本次实际执行

以 integration58 的 AP、产品启动库和资源建立隔离的原厂 AP 软件运行环境，使用中文菜单及软件通信对端。没有使用实验性存储替换库，没有强制准入或强制发布。AP 摘要 `8b34f12d4314a6aa829e14d17971c154575c68ae1d11c4573798f13a860d069a`；启动库和产品启动库摘要均为 `ac6c92c9e3d7f62854544fbcc14926728a157828ded54c319c0f1580b67efdff`。

```text
PYTHONPATH=a7r5-desktop/prepared/engine/site .venv/bin/python -B
  a7r5-firmware-features/custom-filters/experiments/boot-menu406/build.py
  --loader .local/fixed-custom-filters/integration58-release410/loader
  --software-peer --chinese
  --output .local/fixed-custom-filters/incident59-boot-entry

a7r5-qemu/.venv/bin/python -B
  a7r5-firmware-features/custom-filters/experiments/boot-menu406/run.py
  --manifest .local/fixed-custom-filters/incident59-boot-entry/manifest.json
  --interactive
```

命令按参数分行展示。构建及软件运行均退出0。24次按键操作中，索引16 ENTER 后显示原厂创意外观 ST 页面，页面 ID `0xd9`；索引18 RIGHT 后进入参数页 `0xda`；索引23 ENTER 后回到 `0xd9`。最终通过 QMP 正常退出，未在此路径复现用户报告的重启。

运行记录：`.local/fixed-custom-filters/incident59-boot-entry/execution/runs/native-boot-menu406-wsysunw3/`，包含 `verification.json`、`actions.json`、日志及逐步 PNG。入口图像为 `menu-016-ENTER.png`。汇总审计为 `.local/fixed-custom-filters/incident59-offline-audit.json`，已核对24次动作、三个页面节点、图像文件摘要、同一产品启动库及退出码。

## 结论与限制

结论是 `NOT_REPRODUCED_AP_SOFTWARE_ONLY`，不是修复通过。真实 CP、ISP、机身 SD 卷及持久化环境均不在本次运行范围；原生存储初始化在软件环境中失败，不能把这个环境视为完整机身。此次只观察 ST 入口和参数页面，未验证全部32槽或真实取景／JPG。

尚不能区分 AP 页面状态／调用、设备安装内容或版本差异、AP／CP 预览参数交互、CP 异常等原因；这些只是待查方向。上次4.09图像资源偏移故障不是本次已证实根因，不套用旧补丁。

后续若恢复调查，优先使用已经存在的崩溃／重启原因日志和安装文件摘要定位，再建立对应失败用例和最小修复。任何新增设备采集、触发复现或写入均须遵守届时的明确授权。当前按用户选择保存证据，不继续操作相机，不将 `T11ui59` 标为完成。
