# 4.10菜单QEMU截图验证

- Status: CAPTURE_VERIFIED_WITH_FINDINGS
- 用户授权：运行当前4.10整合版菜单并截取自定义滤镜、FL2／FL3、照片标记界面；禁止相机、USB、SSH和真实卡操作。

复用原项目macOS默认拒绝沙箱、原厂内核和真实AP绘图快照。使用独立客体和清单，核对包内AP、CP文件、资源、地区参数与版本；默认清单及历史现场不改写。原厂应用文件保持4.10包内原样；模拟服务既有RAM适配逐项说明，不将此结果等同完整CP／ISP或机身验收。

1. 核对固定QEMU／历史菜单支持客体，生成仅含明确替换条目的独立4.10候选，并核对其余CPIO条目。
2. 用真实Qt按钮和原厂输入链进入菜单、截图；出现固件异常即停止本次运行并保存现场。必要的配置显示夹具独立记录，不能伪装SD／CP真实服务成功。
3. 对原始客体帧、PNG、输入和正常QMP退出独立复核，汇总截图及各项PASS／FAIL／NOT_RUN边界。

主实现落点：`a7r5-qemu/experiments/native12-410-menu/`；构建输出：`a7r5-qemu/build/native12-410-menu-*`；运行证据：`a7r5-qemu/runs/native-native12-410-*`。

## 本次结果

- 当前4.10独立客体：`a7r5-qemu/build/native12-410-menu-20261102-01/manifest.json`。旧guest11部分文字资源与当前包不同，首次前置检查拒绝后，改为明确替换当前包内对应资源；最终其余CPIO内容和元数据保持。
- 有效运行：`a7r5-qemu/runs/native-native12-410-tc2enw_f/`。103次真实Qt按钮操作、103张客体帧／PNG独立核对、四轮MENU往返、worker退出0、QMP quit退出0，无固件或图形异常。
- 输入身份／缺失／篡改／路径／链接拒绝测试：1个参数化测试方法通过；实际macOS沙箱边界：1项通过，固定输入只读、私有文件读取／外部写入／TCP均拒绝，允许本次输出和QMP Unix套接字。
- 所有截图和精简证据集中到[菜单截图归档](../../native24-combined/dependencies/native12-combined/verification/2026-11-02-qemu-menu/README.md)，没有修改DAT或原回执。

| 验证对象 | 状态 | 实际结果 |
|---|---|---|
| 当前AP与真实Qt／原始帧来源 | PASS | 包内原样AP，非预制PNG或网页模拟；每张PNG与原始客体RGBA4444转换逐像素一致 |
| FL2／FL3菜单 | PASS | 分别显示FL2(Film 2)、FL3(Film 3) |
| 照片标记菜单 | PASS | 六种比例含2.35:1；选定后返回显示On／2.35:1／12 |
| 自定义滤镜页面打开 | PASS | 主菜单入口和私有D9页面可进入／返回 |
| 自定义中文显示 | FAIL | 当前英语界面下中文标题及关闭项为方框，原因未定位 |
| 十二款配置加载／应用 | NOT_RUN | 本次未提供完整SD、内部持久化及CP发布条件，页面自然结果只有关闭；未注入名称 |
| 照片画面标记叠加 | NOT_VERIFIED | 开启前后照片M信息页像素相同；Level线框仅设置预览 |
| 实机启动／成像／声音／升级 | MANUAL_REQUIRED | 未授权，本次没有设备操作 |

首次运行`native-native12-410-p9zo4i8z`因宿主非TTY标准输入关闭，控制通道不可写；中断本次worker使其finally正常QMP退出，worker退出2，不纳入验收。随后使用TTY重新启动并完整完成。

最终MenuVM启动前检查又收紧model、CP身份和文件集合；定向拒绝测试通过，当前实际输入再次通过该检查。没有改变客体、QEMU启动参数或运行中的模拟行为，故复用上述有效GUI证据，不重复103次按键。
