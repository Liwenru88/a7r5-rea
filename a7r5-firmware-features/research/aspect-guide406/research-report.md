# 照片 2.35:1 标记的独立 QEMU 验证

本轮结论：**真实菜单、参数选择和往返已验证；照片页上的 2.35:1 标记叠加未通过，不能据此制作安装包。** 照片 M 模式读回“开启、2.35:1”后，拍摄信息页仍与关闭时逐像素相同。设置预览能调用原厂标记绘制函数，但这不能替代照片界面验收。

本实验绑定当前研究 4.06 的 DAT 和 AP 摘要。版本来自已验签研究包头，不将它描述为官方未修改发布包。默认 4.00 运行清单保持原样；缺失默认客体时不放宽旧清单校验。

已获授权的目标是完整菜单和照片界面验证：

1. 从已验签研究包的内存文件系统构建独立客体，保存文件内容清单；不输出分区镜像，不访问相机。
2. 核对模拟层的实际函数、指令及依赖库指纹，先启动未解锁基线，取得原厂应用生成的菜单帧和正常退出回执。
3. 在独立客体 RAM 中加入三个属性登记、三个描述符、二十四个子项和一个入口行的机型支持位变更，保留动态互斥。
4. 验证菜单选择、照片画面、比例往返、MENU 往返、原始帧与 PNG 一致性以及工作进程/QMP 退出。

实验状态必须以本次 `runs/` 和 `logs/` 的记录为准。客体构建、内核终端、原指令窗口和完整界面通过是不同阶段。真实 CP 取景、拍摄、相机掉电持久化及回刷安全不属于本次结论。

`export_source.py` 由当前工程 DAT 工具完成验签和解密后调用，仅接收内存读取器。它从零创建带固定内容清单的文件归档，保留原厂组件内容，另加入离线终端初始化脚本；不替换现有运行输入。

## 实际执行结果

| 项目 | 结果及证据 |
| --- | --- |
| 独立内核和根文件系统 | `native-aspect406-edowj8gd/aspect406-kernel.json` 通过，QMP 正常退出 |
| 未解锁完整应用基线 | `native-aspect406-4ayse5ev` 生成真实 640×480 原厂菜单，页数 58；首次提示按键链通过 |
| 解锁后菜单入口 | Shooting → Marker Display，页数增至 59；六种比例完整显示，包含 2.35:1 |
| 冷启动默认值 | 两次新客体均读回 switch=1（关闭）、ratio=0（1:1）、opacity=12；仅证明本次 RAM 初始化 |
| 原厂菜单写入 | switch 1→0，ratio 0→5；最后一轮还完成 ratio 5→0→5、opacity 12→8 |
| 原厂设置流程 | 通过隐私说明、机内设置、区域/日期、温度提示的原厂按键流程；未直接写接受字段 |
| 照片模式 | 原厂模式标志识别为 M，照片信息页可开关菜单 |
| MENU 往返 | 两个有效候选各四轮，菜单帧与照片信息页分别保持同一像素摘要 |
| 原始帧 / PNG | 前一候选 49 帧、最后候选 105 帧，容器校验、帧序列及独立 RGBA4444 逐像素转换全部一致 |
| Qt 与退出 | 最后一轮 105 次真实 Qt 按钮点击（含退出），独立工作进程正常退出，QMP quit 返回 0 |
| 照片页标记叠加 | **未通过**：关闭帧、开启 2.35:1 帧以及透明度改为 8 后的照片帧完全相同 |
| 设置预览绘制 | 原厂 `+0x182e138` 在透明度设置预览中调用 6 次，visible=1,1；不作为照片页通过证据 |
| DISP | 在 1:1 配置下额外执行五次 DISP，采集各布局，未见标记；未将其描述为 2.35:1 各布局通过 |
| 输入拒绝 / 沙箱 | 两个独立清单/版本夹具测试方法通过；一个真实 macOS 沙箱测试通过，验证固定输入只读、外部读写和 TCP 被拒绝 |

最后一轮为 [`runs/native-aspect406-ht_s_kjs`](evidence/native-aspect406-ht_s_kjs/)，独立校验报告为 [`frame-audit.json`](evidence/native-aspect406-ht_s_kjs/frame-audit.json)。前一轮四次往返与 49 帧报告在 [`native-aspect406-e9x10p_0/frame-audit.json`](evidence/native-aspect406-e9x10p_0/frame-audit.json)。

关键客体快照（均为原厂应用绘制，不含相机取景视频）：

- [六种比例及 2.35:1 选项](evidence/native-aspect406-ht_s_kjs/research-037-DOWN.png)
- [原厂透明度设置预览](evidence/native-aspect406-ht_s_kjs/research-042-ENTER.png)
- [关闭标记的照片 M 页面](evidence/native-aspect406-ht_s_kjs/research-011-MODE_M.png)
- [开启 2.35:1 后的照片 M 页面](evidence/native-aspect406-ht_s_kjs/research-039-MENU.png)

后两帧的像素 SHA-256 均为 `b6cd92ad50b3be33d6cd37c641acfb491ea8e654c189b547f7af1574f7e1aea4`。因此，本轮不能证明照片标记已经显示，也不能把设置预览的边框当成照片叠加。

## 已明确的解锁数据范围

全部在 `Application_System_Init` 之前、当前客体 RAM 内执行，开关为 `A7R5_ASPECT_GUIDE406_UNLOCK`；关闭开关的新客体不执行解锁。

| 数据 | AP 相对地址 | 变更 |
| --- | --- | --- |
| APID 0x645 / 0x646 / 0x647 登记 | `0x5560700` 起，每项 24 字节 | 占位校验器改为原厂 `0x29051dc`，分别使用 0..1、0..5、0..15 范围；原校验器代码不改 |
| 三个菜单描述符 | `0x58a4690 / 0x58a2570 / 0x58a4750 + 0x4c` | 机型列 16 的 u16 支持位 0→1 |
| 24 个选项行 | `0x3f9b900 / 0x3f7a380 / 0x3f94c00` 起，步长 `0x80`，各行 `+0x64` | 机型列 16 支持位 0→1；先核对属性及选项身份 |
| 完整菜单入口 MID 0x194 | `0x3fdfa64` | 独立支持位 0→1；MID 0x195 / 0x196 原为 1，不改 |

总计三个属性登记和 28 个支持位。完整菜单入口的额外关闭位，是本轮完整界面检查发现的；仅验证选项页枚举会漏掉这一层。

最后一轮另在 `+0x57837f0` 安装透明绘制观察包装，调用原厂 `+0x182e138` 后记录参数；不伪造绘制结果。原厂属性互斥计数、菜单 setter、刷新函数均未强制返回成功。观察代码和解锁数据与已有模拟适配分别保存在构建收据和日志中。

## 独立环境及原厂组件适配

源归档在 `build/aspect-guide406-20261026-01/source-02/`，最后候选为 `guest-11/`。构建比较确认源归档的 **1254 个条目内容和元数据未变**，只增加 11 个明确列出的模拟辅助文件；这里的比较基准是导出的源归档，不是宣称 CPIO 与原文件系统逐字节等价。

默认清单缺少的设备树，在历史客户端运行目录找到与固定清单摘要完全相符的副本。独立设备树只按新归档容量调整 ramdisk 大小和 initrd 结束地址，未替换默认输入。

以下是为了启动模拟器的环境适配，不是标记解锁内容，也不是相机验证：

1. 复用现有软件 GPE、AP 图形消费者、CP 服务子集、蓝牙包装和 MENU 重入适配。无真实 CP 图像合成或面板。
2. 为当前 ALLLANG 种子的 UTC+09:00 时区编译专用时钟初始化工具，调用原厂 BY_BOOT 接口并验证本地时间读回、时区保留和走时；旧 UTC 工具不能直接套用。
3. 从已验签包头生成普通文件 FAT 夹具，供原厂版本查询读回型号/区域，以及 `dat4=06 04`；无真实相机分区读写。
4. 新增一份 IMDB 模拟加载配置，仅移除 QEMU 目标位，启动时复制到客体 RAM。集合为蓝牙相关五项、USB 四项和 Hotplug；WoLEBoot 原本没有该位，保持不变。九个实际字节变化以收据为准。原 IMDB 文件仍保留。

保留了所有失败现场。`guest-06` 在 USB gadget 注册处触发空指针；排除 USB 硬件模块后，`guest-07` 又在 Hotplug 对未加载的 USB 控制服务发同步请求时触发原厂断言。之后完整排除这套未模拟硬件初始化链，未跳过断言或改内核返回值，`guest-08` 起成功出帧。

`guest-09` 的初版观察器误把 getter 返回地址当作整数，相关模型值日志不可用于验收；`guest-10/11` 已按原指令核对为指针并正确解引用。菜单导航图像仍保留，但模型验收只引用后两轮。

## 剩余限制与下一步

最后一轮日志读到 `system_mode=2`，switch 互斥字段为 0；不能再把照片未出帧归因于“系统仍停在启动状态”。标记绘制观察只在设置预览触发，返回照片页未观察到相应调用。五次 DISP 是 1:1 配置的补充探测，不能替代 2.35:1 的逐布局验收。

目前尚未分清照片控制器的组件创建/快照绑定限制与模拟器 AP/CP 平面组合缺口。下一步应针对**当前真实照片控制器**记录标记组件、快照字段、`+0x240dae0` 参数转换及 `+0x182e138` 绘制的实际调用，定位第一处断点。不要通过直接调用绘制函数、强写可见字段或拼接边框来让验收变绿。

本轮没有相机 I/O、原始分区镜像输出、DAT 修改、默认清单切换或固件安装包。真实取景、拍摄文件、掉电持久化、动态互斥的全部真机场景及回刷安全仍未验证。

## 复现与证据

在 `a7r5-qemu` 目录执行，给新构建选择未使用的输出目录：

```sh
.venv/bin/python -B experiments/aspect-guide406/build_guest.py \
  --source build/aspect-guide406-20261026-01/source-02 \
  --boot-manifest build/aspect-guide406-20261026-01/boot-01/manifest.json \
  --output build/aspect-guide406-20261026-01/guest-new
.venv/bin/python -B experiments/aspect-guide406/qt_research.py \
  --manifest build/aspect-guide406-20261026-01/guest-new/manifest.json --unlock
```

测试台通过标准输入接收固定按键名，例如 `LEFT`、`ENTER`、`MENU`；`STOP` 走正常 QMP 退出。所有操作经真实 Qt 按钮和独立工作进程转发，不提供任意客体命令。

本次校验命令及结果：

```sh
.venv/bin/python -B experiments/aspect-guide406/test_runtime.py
# 2 个测试方法通过
.venv/bin/python -B tests/test-native-backend.py NativeContract.test_real_macos_policy_enforces_boundaries
# 1 个真实沙箱测试通过
.venv/bin/python -B experiments/aspect-guide406/verify_run.py \
  --run runs/native-aspect406-ht_s_kjs --cycle-start 96
# 105 帧一致、4 轮 MENU 一致；complete_photo_overlay_verified=false
```

原始 DAT SHA-256 复核保持 `3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2`，AP 为 `d15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9`；默认清单与 Git HEAD 相同。其余输入、源码摘要及语法检查见 [`verification-checks.json`](build-evidence/verification-checks.json)。
