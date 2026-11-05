# 020 调参及切换状态同步复验

固定 AP `36ba6c0a9285d2708e74af651a6683d020c50d880d6b35a48cab51bafe2b1438`，CP、图标和正式十二款 BIN 不变。仅离线，保留固定输入和沙箱。

在 `a7r5-qemu` 目录使用 `.venv/bin/python -B`、`PYTHONDONTWRITEBYTECODE=1` 和 `PYTHONPATH=tools`。构建器输入本轮 `.local/ui-refresh-20261104/fix-02`，输出须为新的 `build` 子目录；已验证客体为 `build/native24-ui-sync-fix-20261104-02/manifest.json`。依次使用 `build_guest.py`、`test_runtime.py`、`run_validation.py`、`verify_receipt.py`，不与其他 AP 虚拟器并发。

真实 Qt 路线覆盖原厂外观、FL2／FL3、正式十二款、八项调节／重入／重置、四轮 MENU 及四处自然停手观察，共 107 操作和 107 帧。观察器透明包装原有入口，检查可搬移序言，只记录自然事件、原绘制调用与只读状态，不调用刷新协调器或写完成位。

最终运行 `native-native12-410-deev3qmz`：后台 1→5 时无按键自动显示“切换未完成”；八项画面已人工逐项与工作值核对，清晰度按键后及停手后均为 2。E4 成功应用及传感器成像仍未验证。通用驱动的保守终态字段保持，其较窄的失败提示与数字观察记录在归档 `visible-observation.json`。

完整报告：仓库 `a7r5-firmware-features/specs/020-native-ui-sync-idle/分析与验证.md`。长空闲失败由相邻 `native24-idle-control` 实验单独记录，不以本短窗口结果代替。
