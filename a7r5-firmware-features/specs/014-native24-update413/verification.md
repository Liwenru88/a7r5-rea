# 验证记录

Feature ID: 014-native24-update413
Status: NOT_VERIFIED

离线封装已完成，整体仍为NOT_VERIFIED／DEVICE_UNTESTED。013的80项回归和两场景154帧QEMU经来源及组件新鲜度检查复用；本轮另执行完整DAT验证，不将旧回执冒充新包验收。没有设备操作。

| Evidence | 实际执行及结果 | Acceptance |
|---|---|---|
| E-001 | 固定013压缩包及1369项摘要、四组件、原80项XML／会话回执、两场景及其源码新鲜度全部PASS | AC-001 |
| E-002 | 新拒绝测试及既有尾部扩展／DAT工具回归：35项PASS，1.08秒，无跳过；原始XML／日志随包保存 | AC-001、003 |
| E-003 | USR独立Audit核对1044路径；恰好AP及两图形资源改变，新分配659块，原inode及旧数据块地址、无关内容／映射／非容量元数据、分区几何保持；只读e2fsck退出0 | AC-002 |
| E-004 | CP定长写入及所有无关字节保持；原WBI、重建十二参数模板与上游基线一致；17个归档成员变化符合预期，其余归档元数据／布局和updater保持 | AC-002 |
| E-005 | 正常研究签名；全部736841帧、751577088字节完整预期明文、独立完整解包、四组件回读及OpenSSL `Signature Verified Successfully`；FDAT版本字节13 04 | AC-002、003 |
| E-006 | 新交付目录33项文件摘要核对，原十二款BIN、公钥、源码／证据和已知问题齐备，无私钥或合成配方；旧包／013归档保持 | AC-004 |

构建命令（仓库根目录，DAT专用已有环境）：

```sh
a7r5-dat-tool/.venv/bin/python -B \
  a7r5-firmware-features/native24-combined/release413/build.py \
  --output .local/native24-update413-20261103-01
```

完整现场：`.local/native24-update413-20261103-01`；总日志：`.local/native24-update413-20261103-01.log`。原始帧与运行时证据仍由013封存提供，包内AP、CP及两图形资源逐字节对应，不另跑未变化的QEMU。

交付：[4.13说明](../../native24-combined/releases/4.13/README.md)、[BODYDATA.DAT](../../native24-combined/releases/4.13/BODYDATA.DAT)、[回执](../../native24-combined/releases/4.13/verification.json)、[全目录摘要](../../native24-combined/releases/4.13/CONTENTS.sha256)。DAT大小754525608字节，SHA256：`efeaaa2bd2c094b456ca16e66e2e763263a98b983e80aa600761882e5d4f167d`。

签名公钥沿用既有研究身份，公钥文件SHA256：`7f65b296987df665da217de514e785f75238e686ddd18952fa425fc47e8c858a`，未更改机身安全策略或updater。配套BIN为29552字节原十二款正式配方，SHA256：`19e020fa48c79643aaf9526e9c720d38ec5a92c3df11d0852b0a93a25ee880b6`。

| Acceptance | 状态 |
|---|---|
| AC-001 固定当前载荷与证据 | PASS（离线） |
| AC-002 完整封装与范围保持 | PASS（离线） |
| AC-003 签名、逐帧及独立回读 | PASS（离线） |
| AC-004 可追溯本地交付 | PASS |

机身信任、4.13版本准入、安装／恢复、正常启动、真实LCD／EVF／JPEG、声音、照片标记画面叠加和介质掉电仍未在本候选上验收。原E4初始化及长列表AP抓帧顶部文字缺失问题保留，详见包内KNOWN-ISSUES.json。封包通过不代表上述问题已修复；没有连接相机、写卡、安装、提交或推送。
