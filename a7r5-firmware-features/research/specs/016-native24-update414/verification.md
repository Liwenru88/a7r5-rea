# 验证记录

Feature ID: 016-native24-update414
Status: NOT_VERIFIED

4.14离线构建与交付完成。包状态为`OFFLINE_PACKAGE_VERIFIED_DEVICE_RETEST_REQUIRED`，整体实机状态仍为`NOT_VERIFIED`。本轮没有连接相机、写卡、安装或重启；最后确认的机身文件仍为原4.13。

| Evidence | 实际结果 | Acceptance |
|---|---|---|
| E-001 | 固定015审查归档及302项摘要、修复AP／CP／两份F0图标、原正式十二款BIN与既有研究公钥均通过 | AC-001、003 |
| E-002 | 完整相关CPU回归82项PASS，1160.19秒，原始XML／会话回执及来源新鲜度通过，包含本次两个故障回归 | AC-001 |
| E-003 | 同组件正式十二款103帧封存复用；新满24槽115次／115帧、空库39次／39帧通过，合计257帧；实际CPIO组件、真实Qt操作、PNG与原帧、源码及Qt／AP／CP退出核对通过；固定身份测试2项PASS | AC-001 |
| E-004 | 最终封装拒绝测试及既有ext2／DAT工具回归37项PASS；源改变后重新执行封装门禁，未降低为38项运行时定向回归 | AC-001、003 |
| E-005 | USR核对1044路径，恰好AP及两份图标改变；追加153块，原inode、旧数据块地址、无关内容／映射／非容量属性及分区几何保持，只读e2fsck退出0 | AC-002 |
| E-006 | 原CP定长数据区替换、其他字节保持；原WBI、十二份参数模板和原updater保持；17个归档成员变化与完整预期集合一致 | AC-002 |
| E-007 | FDAT版本字节`14 04`；全部736841帧、751577088字节完整明文一致；独立完整解包及四组件回读PASS，OpenSSL返回`Signature Verified Successfully` | AC-002、003 |
| E-008 | 新交付113个文件，112项CONTENTS摘要全部核对；原4.13 DAT及015审查归档摘要保持，无新设备操作 | AC-004 |

构建命令（仓库根目录，现有DAT专用环境）：

```sh
a7r5-dat-tool/.venv/bin/python -B \
  a7r5-firmware-features/native24-combined/release414/build.py \
  --output .local/native24-update414-20261104-01
```

交付：[BODYDATA.DAT](../../native24-combined/releases/4.14/BODYDATA.DAT)、[说明](../../native24-combined/releases/4.14/README.md)、[验证回执](../../native24-combined/releases/4.14/verification.json)、[目录摘要](../../native24-combined/releases/4.14/CONTENTS.sha256)。

- DAT大小：754525608字节。
- DAT SHA256：`c4846fc1e7bd5f279aa8b98ac319990a6f2bb901d75a66b5492320538104ceb2`。
- 研究公钥SHA256：`7f65b296987df665da217de514e785f75238e686ddd18952fa425fc47e8c858a`，沿用原身份。
- 正式十二款BIN SHA256：`19e020fa48c79643aaf9526e9c720d38ec5a92c3df11d0852b0a93a25ee880b6`。

完整CPU现场：`.local/native24-update414-runtime-cpu-20261104-01/`。本次满库／空库运行分别为`native-native12-410-3g2497u_`和`native-native12-410-w78fyhdf`，正式十二款复用`native-native12-410-frzr6wsy`的015封存。封包现场与日志：`.local/native24-update414-20261104-01/`及同名`.log`。

本包纳入图标F0编码与同步导航索引保护。原厂图标像素、滤镜配方及既有功能未借封包扩大修改。QEMU以软件解码代替LDEC；新F0流的实机接受、切Tab不重启、升级／恢复、启动、LCD／EVF／JPEG、声音及照片标记叠加仍待实机验收。原E4初始化缺口和长列表抓帧标题偶有缺失继续列入KNOWN-ISSUES，未因封包宣称解决。
