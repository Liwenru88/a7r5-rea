# 4.15离线封装验证

Status: OFFLINE_PACKAGE_VERIFIED_DEVICE_RETEST_REQUIRED

已将017图标分块修复封装为4.15，未连接相机、写卡、上传、安装或重启。旧4.14、原017审查材料和历史回执保持。

| 项目 | 实际结果 |
|---|---|
| 构建 | `.local/native24-update415-20261104-01`，COMPLETED，未残留INCOMPLETE标记 |
| 封包命令 | `a7r5-dat-tool/.venv/bin/python -B a7r5-firmware-features/native24-combined/release415/build.py --output .local/native24-update415-20261104-01` |
| 封装层回归 | 51 PASS，1.08秒；原始XML／日志在交付evidence中 |
| 版本／头 | 4.15，版本字节`15 04`，头CRC32核对通过；原机型标识`0x11030080`保持 |
| DAT | 754525608字节，SHA256 `4924ccfa29bb711124a31667a8f51e0b7e691d4547edc371e82989c40a017dde` |
| 全帧 | 736841帧，明文751577088字节，完整预期明文一致 |
| 明文SHA256 | `acc01626870042815a5ff56b362264c46fe694c1e0aef33af2f1c7b3aa49c268` |
| 完整独立回读 | 全部归档成员／元数据、原更新器、分区、AP／CP／两份图标回读通过 |
| 签名 | 原研究公钥SHA256 `7f65b296987df665da217de514e785f75238e686ddd18952fa425fc47e8c858a`，OpenSSL返回`Signature Verified Successfully` |
| USR | 1044路径审计，恰好替换AP＋两图；追加155块，无关路径／块映射／非容量inode字段及几何保持；只读e2fsck退出0 |
| 同4.14比较 | USR仅两份图标变化；CP、WBI、更新器和全部参数模板保持，归档仅USR及其校验成员变化 |
| 导出 | 118文件、117项CONTENTS清单全部复核；清单自身SHA256 `78df550b3584d5218d06281a2983b7bfcfc91787b5a5676cabd7ce173fa71d1f`，无私钥 |
| 旧包保持 | 原4.14的112项清单全部重新核对通过 |

证据复用没有扩大原结论：82项完整CPU回归只绑定与4.14相同的AP／CP，源码差异严格限定为017编码器与构建器；本次分块7项和构建／Tab16项另行绑定新资源、源码及原XML。017固定tar／535项目录清单、独立重建、实际组件和103幅QEMU帧回执均重新核对；QEMU验证器再次检查CPIO、PNG和Qt／AP／CP退出，没有重启虚拟器。未把旧图标场景计入新资源的103帧，也未声称本轮重跑完整CPU或QEMU。

交付为[4.15目录](../../native24-combined/releases/4.15/README.md)，完整回执见`verification.json`、`evidence/runtime-evidence.json`、`evidence/packaging-tests.xml`、`evidence/previous-version-comparison.json`及`CONTENTS.sha256`。导出过程另有`.local/native24-update415-20261104-01/export-proof.json`。

当前整体仍为NOT_VERIFIED。用户已报告4.14仍重启，4.15没有实机日志、LDEC硬件、版本准入、升级／恢复、启动和实际成像验收；QEMU原E4和长列表标题抓帧边界继续保留。离线包校验通过不等于机身重启已消除。
