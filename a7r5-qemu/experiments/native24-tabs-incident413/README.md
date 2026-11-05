# 4.13正式十二款BIN诊断客体

固定旧4.13的AP／CP／图标资源和机内实际十二款BIN，不改变固件、配方或完成位。父客体原本已含相同BIN，因此严格检查五条实际变更，同时核对六份目标内容和所有其他归档条目保持。

原候选完成103次Qt操作，但没有复现实机LDEC崩溃。此客体启用软件LZ77解码，不能验证硬件接受条件。既有E4初始化缺口保留。

实际运行：`runs/native-native12-410-x1b36v1w`；构建：`build/native24-tabs-incident413-20261103-03/manifest.json`。失败的01／02构建保留，未绕过身份或沙箱检查。

修复客体见相邻`native24-tabs-incident413-fix`，根因、设备边界及源码见仓库`a7r5-firmware-features/specs/015-tabs-device-reboot/`。本实验自身不连接相机。
