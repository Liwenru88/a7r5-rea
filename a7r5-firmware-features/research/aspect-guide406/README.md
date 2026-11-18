# A7R5 照片 2.35:1 标记研究包

本包归档当前研究 4.06 的照片标记解锁方案，供后续构建升级候选引用。**菜单、参数选择及 QEMU 界面操作已验证；照片页标记叠加尚未验证成功，尚无本功能的可安装升级包或实机结果。**

用户本轮授权归档研究成果，后续可据此构建升级候选。本轮没有执行固件构建、相机连接或刷写。原始 DAT、默认 QEMU 清单与既有滤镜研究材料保持原样。

## 从哪里开始

| 内容 | 位置 |
| --- | --- |
| 适用输入、证据级别、排除项 | [manifest.json](manifest.json) |
| 地址、文件偏移、前像、范围、ELF 重定位 | [patch-plan.json](patch-plan.json) |
| 后续升级包的接入步骤与未完成项 | [integration.md](integration.md) |
| 原始实验说明及历史判断 | [research-report.md](research-report.md) |
| 实际测试过的运行时解锁代码 | [aspect-guide406.inc](source/a7r5-qemu/experiments/aspect-guide406/aspect-guide406.inc) |
| 最后一轮 105 帧、原始日志和正常退出回执 | [最后一轮证据](evidence/native-aspect406-ht_s_kjs/frame-audit.json) |
| 未解锁菜单基线 | [基线回执](evidence/native-aspect406-4ayse5ev/aspect406-menu.json) |
| 编译收据、固定输入清单和源归档文件摘要 | [构建证据](build-evidence/index.json) |
| 所有归档来源与摘要 | [provenance.json](provenance.json) |
| 包内文件完整性 | [SHA256SUMS](SHA256SUMS) |

## 本包保留了什么

- 三个属性登记与 28 个支持位的完整清单，包括本轮发现的 MID 0x194 入口支持位。
- 原厂校验器、菜单 setter、当前值 getter 和观察入口的身份；明确区分 AP 虚拟地址、文件偏移、装载后的基址。
- QEMU 实验源码、所需项目内 Python 模块及原生 C/头文件依赖、实际生成的观察源码、构建命令和摘要。
- 最后一轮全部 105 份原始帧及对应 PNG/JSON、完整串口日志、Qt 操作、四轮 MENU 往返和 QMP 退出记录。
- 未解锁菜单基线、前一有效候选的 49 帧校验报告及关键帧，以及 USB/Hotplug 启动失败现场。
- 用于未来构建前核对 AP 前像的只读工具；不会生成修改后的 AP。

QEMU 可执行文件、固件 AP/CP、内核、完整 CPIO、SDK 固件库和私钥没有打入本包。它们的身份和获取/恢复条件保存在清单中。源码和研究证据可独立查阅；重新运行 QEMU 仍需要清单锁定的外部输入及 macOS 运行环境。本包不因保存了源码而宣称环境可在任意机器直接启动。

## 当前验证结论

| 层级 | 结论 |
| --- | --- |
| 原厂菜单入口与选项 | 通过：Marker Display 出现，页数由 58 增至 59，包含 2.35:1 |
| 原厂模型写入 | 通过：开关 1→0；比例 0→5，并完成 5→0→5；透明度 12→8 |
| 默认值 | 新 QEMU 客体读回关闭、1:1、12；不是实机掉电恢复结果 |
| Qt / 帧 / 退出 | 105 次 Qt 点击（含退出）、105 帧逐像素一致、四轮 MENU 往返、工作进程和 QMP 正常退出 |
| 标记设置预览 | 原厂绘制入口调用 6 次，可见字段为 1,1 |
| 照片 M 页叠加 | 未通过：开启 2.35:1 后仍与关闭时像素完全相同 |
| 原因归属 | 未定位；不能单独归因于 QEMU，也不能据此判断真机无法显示 |
| 实机 / 取景 / 拍摄 / 掉电 | 未验证 |

关键图像：[六种比例选项](evidence/native-aspect406-ht_s_kjs/research-037-DOWN.png)、[设置预览](evidence/native-aspect406-ht_s_kjs/research-042-ENTER.png)、[关闭时照片页](evidence/native-aspect406-ht_s_kjs/research-011-MODE_M.png)、[开启 2.35:1 后照片页](evidence/native-aspect406-ht_s_kjs/research-039-MENU.png)。这些是真实客体快照，不含相机取景图像。

## 完整性与构建前检查

使用当前工程 `.venv/bin/python`，工具只依赖 Python 标准库：

```sh
.venv/bin/python -B a7r5-firmware-features/aspect-guide406/tools/verify_bundle.py
.venv/bin/python -B a7r5-firmware-features/aspect-guide406/tools/inspect_ap.py \
  --ap /path/to/extracted-current-4.06/appFw.so
```

`inspect_ap.py` 只接受摘要为 `d15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9` 的 97368304 字节 AP。其他固件或已经叠加新改动的 AP 会被拒绝；不能通过删除检查来复用地址。

研究包 ZIP 是此目录的快照，另附 `.sha256`。包内校验清单覆盖所有文件（自身除外），ZIP 成员经 CRC 和逐文件 SHA-256 读回核对。原始收据内的绝对路径和旧运行目录作为历史来源保留，不是要求在新主机重建相同用户名目录。
