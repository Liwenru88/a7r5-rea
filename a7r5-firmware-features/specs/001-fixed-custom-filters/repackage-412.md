# 研究4.12：同载荷版本封装

日期：2026-11-02。按用户明确要求生成独立4.12包，任务 `T11v412` 的离线封装范围完成。没有连接或操作相机。`T11ui59` 未完成：integration58进入创意外观导致实机重启的故障未修复，此包不推荐实机安装。

## 交付身份

- 文件：`.local/fixed-custom-filters/repackage412-release/update412/BODYDATA.DAT`
- 版本：研究4.12，不是索尼官方固件。
- 长度：754525608字节。
- SHA-256：`19d8bfb81da4dc70f82daa94cbc9f33cd0fc4015dc48cba79c553f8be14840b6`。
- 同目录：`BODYDATA.DAT.sha256`、`verification.json`、`COMPLETED.json`、`KNOWN-ISSUES.json`、`README-研究测试说明.md`。
- 最终核对：`.local/fixed-custom-filters/repackage412-final-audit.json`。

基于唯一原修改版4.06输入，保留原输入及integration58。AP、CP、四个动态库和70份资源均与integration58一致；重新生成的USR仅ext2写入时间 `s_wtime` 不同。包头版本改为4.12后正常研究签名，不修改更新器或信任规则。不新增同版本重装、降级或恢复能力，不代表机身更新器已接受此版本。

## 改动与验证

封装器只将用户指定的4.12加入明确版本／照片标记范围表，保留4.11拒绝行为；完整构建和独立内容检查入口增加 `--version`，默认仍为4.10。产品运行代码没有变化。由于封装源摘要发生变化，重新生成软件门禁及五阶段封装回执，没有改写或伪造旧回执。

| 证据 | 实际执行结果 |
|---|---|
| E-413 | `test_upgrade_package.py`：32 passed，含4.12正确范围接受、错误schema／范围拒绝和公开构建入口校验 |
| E-414 | `software31/verify.py --recipe-bridge --capture-copies --bootstrap-only`：70 passed，exit0；新回执 `repackage412-software/verification.json` |
| E-415 | `release406/build_candidate.py --version 4.12`：五阶段exit0，研究验签／独立解密／完整归档回读／75项USR内容及CP正逆检查通过 |
| E-416 | `release406/verify_candidate.py --version 4.12`及最终核对：60条原复杂图像载荷保持，四库及全部75项USR内容／CP与integration58相同，旧DAT未变；最终摘要匹配 |

上述输出均位于 `.local/fixed-custom-filters/`，构建完整argv、输出及退出码见 `repackage412-release/commands.json`；DAT专用环境为 `a7r5-dat-tool/.venv/bin/python`，未混入prepared/site密码库。

## 已知故障

此包功能代码与故障候选相同，仍可能在实机进入创意外观时重启。已知故障已写入包旁说明及 `KNOWN-ISSUES.json`。同包AP软件环境未复现的证据不能替代实机恢复或真实CP／存储验证，见[故障59离线记录](incident-59-creative-look-reboot.md)。本轮没有新增QEMU、CP／ISP硬件模拟或实机测试，不宣称修复或完整功能验收。
