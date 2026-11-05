# 4.13图标解压修复诊断客体

固定修复AP、原CP、新F0图标和正式十二款BIN；未知或旧图标摘要拒绝。沿用原沙箱、原生菜单、Qt真实按钮和只读采样，不伪造E4完成或成像成功。

在本目录所属`a7r5-qemu`中执行：

```sh
.venv/bin/python experiments/native24-tabs-incident413-fix/test_runtime.py
```

最终构建为`build/native24-tabs-incident413-fix-20261103-02/manifest.json`，最终运行`runs/native-native12-410-frzr6wsy`。103次操作／103原帧核对通过，Qt／AP／CP正常退出。01是仅修导航上下文、仍使用旧图标的中间候选，原回执保持，不再作为当前固定输入。

这里仍以fwtool软件解码代替LDEC，仅证明菜单和像素兼容。实机已有两次F01长0F流失败的证据，新F0流尚未写入机身，不能据本实验关闭实机故障。详见仓库`a7r5-firmware-features/specs/015-tabs-device-reboot/故障分析与修复.md`。
