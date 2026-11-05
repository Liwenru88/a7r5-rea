# 020 原厂 ST 长空闲对照

固定同一最终 AP `36ba6c0a…`、CP、正式十二款 BIN 与沙箱。仅离线，不操作相机。

在 `a7r5-qemu` 中使用本目录 `build_guest.py` 从最终固件构建新的独立客体，再通过 `run_validation.py` 的真实 Qt 路线进入原厂 ST，随后执行最长 90 秒宿主停手观察。新动作 `IDLE_SOAK` 不发送导航输入、不直接调用生产刷新函数；异常监控触发后立即停止并经本实例 QMP 清理。

最终客体 `build/native24-idle-control-final-20261104-01/manifest.json`，运行 `native-native12-410-n633mig5`。未访问自定义 Tab，自定义命令序号为 0。进入原生关机后，透明包装的原生查询函数记录 `command=0x4d8 object=0`，随后 `sequence_still_record::suspend` 在 `AP+0x34e620c` 读取 `NULL+0x3cc`，结果为失败。

查询包装严格核对 `AP+0x321f17c` 前 16 字节为可搬移序言，调用原函数并保留返回；没有跳过空指针、构造替身任务、禁止关机或伪造 E4 完成。`0x11` 因子来源及任务创建失败的更上游原因仍未确认。

本目录继承的完整菜单验证器／身份用例不用于将该诊断失败标记为通过。实际结果见固件归档 `idle-failure.json`、原始控制台及 `idle-disassembly.json`，整体长空闲稳定性未验收。
