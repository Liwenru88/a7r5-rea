# 4.17 相对偏移调参封包

入口固定绑定 AP `eaf0b742…`、CP、两份图标、正式十二款配方和既有研究公钥，不接受旧 4.17 AP `27bc6eb0…`。共享封包代码由旧交付源码迁入本目录，原始来源为 Git `d557c16` 中 4.17 source 内的 release415/build.py；保留分区几何／无关内容审计、完整预期明文、逐帧验证、独立解包和 OpenSSL 验签。

从仓库根目录执行，输出必须是 `.local` 下不存在的目录。先按[相对偏移说明](../相对偏移调参说明.md)重建并完成回归，再执行：

```sh
a7r5-dat-tool/.venv/bin/python -B \
  a7r5-firmware-features/native24-combined/release417/build.py \
  --baseline "$PWD/.local/native24-upstream-parameters-20261105-175845/baseline" \
  --runtime "$PWD/.local/native24-relative-20261105-192203/final" \
  --rebuild "$PWD/.local/native24-relative-20261105-192203/rebuild" \
  --output "$PWD/.local/native24-relative417-package-new"
```

`evidence_gate.py` 固定本轮六份核心回执摘要，验证证据目录清单、构建源码和外部依赖、四组件摘要、31 项回归与原始 XML，以及上游 48 次 E4／432 条消息比对。源码和四组件未变时复用已完成的 CPU 证据，不重复执行。QEMU 复用数量为 0，不使用旧版本的画面作为本轮验证。

封装器另执行本目录测试及 DAT／ext2 工具测试，使用临时测试签名身份；实际封包仍使用既有研究密钥。交付不包含私钥。输出有 `INCOMPLETE.json` 时该次构建没有完成，保留现场；只有完成全部回读和验签后才生成 `delivery/` 和 `COMPLETED.json`。

交付说明为 [PACKAGE-README.md](PACKAGE-README.md)，限制见 [KNOWN-ISSUES.json](KNOWN-ISSUES.json)。仍采用版本 4.17，应按交付 SHA-256 区分此前同版本内容；没有验证实体机同版更新准入，也没有修改版本检查策略。所有入口仅操作本地普通文件，无相机、SD 卡或网络入口。
