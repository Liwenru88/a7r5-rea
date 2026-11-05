# 4.15离线升级包入口

固定017图标4KiB分块修复组件，沿用原研究签名及原更新器。保持4.13／4.14与017审查归档原样，没有SSH、USB或安装入口。

使用现有DAT专用环境，在仓库根目录执行；输出必须是新的.local目录：

```sh
a7r5-dat-tool/.venv/bin/python -B \
  a7r5-firmware-features/native24-combined/release415/build.py \
  --output .local/native24-update415-new
```

证据门禁分别保留原范围：82项完整回归只按相同AP／CP复用，允许的源码差异仅限已验证的图标编码器及构建器；23项本次定向回归和103原帧绑定017新资源。目录清单绑定固定审查tar，未知组件、源码漂移、旧4.14图标、不完整回归和QEMU来源漂移均拒绝。

封包后完整逐帧验证、独立解包、核对USR全部文件／inode和分区几何、只读e2fsck、完整预期明文／归档、四组件及OpenSSL验签。成功后才产生delivery；私钥仅在既有受限路径使用，不输出、不复制。整体机身验收仍未完成。
