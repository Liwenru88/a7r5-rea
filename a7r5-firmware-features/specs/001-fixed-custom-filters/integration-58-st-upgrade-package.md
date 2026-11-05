# 第58批：ST验证门禁下的完整更新包

> 2026-11-02 故障更新：用户已报告 integration58 实机进入“创意外观”会死机重启，停止推荐继续测试此候选。故障尚未修复；同包 AP 软件环境未复现不能排除实机问题。以下保留历史封装记录，最新状态见[故障59记录](incident-59-creative-look-reboot.md)。

日期：2026-11-02。T11st58本地打包交付完成。基于唯一修改版4.06，使用第57批带ST连续验证门禁的构建回执，完整执行AP／CP／USR组合、研究签名、独立解密和完整回读。未操作相机，不做CP／ISP硬件模拟，未扩大基底、特殊分支或Gamma格式。

## 交付文件

| 项目 | 结果 |
|---|---|
| 更新包 | [BODYDATA.DAT](../../../.local/fixed-custom-filters/integration58-release410/update410/BODYDATA.DAT) |
| 版本／修订 | 研究4.10／integration58，不是索尼官方4.10 |
| 长度 | 754525608字节 |
| SHA-256 | `b1f3f35c7cd614fdc07b94971323cda5b25a14de6fbbc9e94ecf582bc8d17c37` |
| 校验文件 | [BODYDATA.DAT.sha256](../../../.local/fixed-custom-filters/integration58-release410/update410/BODYDATA.DAT.sha256) |
| 随包说明 | [README-研究测试说明.md](../../../.local/fixed-custom-filters/integration58-release410/update410/README-研究测试说明.md) |
| 最终审计 | [verification.json](../../../.local/fixed-custom-filters/integration58-final/verification.json) |

当前包包含现有固定32槽、中文菜单、双入口导入、八项编辑／保存和原厂成像组件接入，以及此前合并的照片标记扩展。首轮ST的连续软件参数链证据详见[第57批报告](integration-57-st-photo-chain.md)。包内含有某项功能不等于该功能已在真实机身验收。

## 本次封装与验证

执行命令：

```text
.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/release406/build_candidate.py
  --source-dat /Users/wenruli/Desktop/索尼/BODYDATA.DAT
  --source-workspace .local/fixed-custom-filters/integration52-source406
  --software .local/fixed-custom-filters/integration57-software-gated/verification.json
  --cp-receipt .local/fixed-custom-filters/integration56-cp-staged/verification.json
  --output .local/fixed-custom-filters/integration58-release410
```

上面按参数分行展示，实际完整argv、耗时、标准输出和退出码见[commands.json](../../../.local/fixed-custom-filters/integration58-release410/commands.json)。DAT阶段由工具使用专用`a7r5-dat-tool/.venv/bin/python`，没有混用prepared/site的密码库元数据。

| Evidence | 回执／命令 | 结果及范围 |
|---|---|---|
| E-409 | [完整更新回执](../../../.local/fixed-custom-filters/integration58-release410/update410/verification.json)及COMPLETED.json | 五阶段exit0：AP预检、启动库链接、冻结清单、USR检查、DAT签名与回读；研究签名有效、独立解密逐字节一致、全归档重新读取，实际使用ST门禁true的同源软件回执 |
| E-410 | `release406/verify_candidate.py`；[内容审计](../../../.local/fixed-custom-filters/integration58-content-audit.json)及[最终审计](../../../.local/fixed-custom-filters/integration58-final/verification.json) | 最终CP、四DSO及两UXC共60条原复杂载荷核对；原包／旧候选保持、当前来源401／114／361／113／29项匹配；新旧USR唯一差异定位到`s_wtime`，未发现额外功能内容变化 |

来源未变，复用第57批445 passed／10旧配置skip、70 passed带门禁构建、4个ASan／UBSan场景和7次原CP纯软件构表证据，本轮未重复执行相同测试。CP继续使用RX39280／40960、静态RW48744、51挂点／69窗口的已严格正逆构建；最终CP SHA `ef616a6581dac99106380a4f56da9d88093680cf524f72b0eb0b502cea58fc99`。

原输入`/Users/wenruli/Desktop/索尼/BODYDATA.DAT`的SHA保持`3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2`；原更新器和信任规则保持，没有新增同版本重装或降级能力。

## 为什么与第56批的SHA不同

AP及75项USR内容（AP、四DSO、70资源）和CP均与第56批一致。本次生成的USR分区仅`0x430..0x433`的ext2 superblock写入时间`s_wtime`改变，其中实际改变两个字节`0x430／0x431`；其他所有USR字节一致。旧时间值1793604570，新时间值1793614642。

因此USR校验、签名和加密后的DAT摘要变化。此次是最新ST门禁下的完整重新封装，不是新增机内滤镜修复；仍保留第56批及其他旧包，不覆盖任何历史产物。

## 尚未取得的证据

T03native55、T03f2和T12更广范围继续未完成。ST的软件参数链已通过，但真实启动／MENU／AP-CP任务、原SD和机内持久化、取景／JPG像素、实际误差和照片标记叠加均未验收。本轮没有用重新封装提升这些状态，也没有操作相机补证。

此包作为后续受控ST实机联调候选交付，不作为已经确认安全刷入或全部功能可用的正式固件。刷入前需要确认机身当前版本与接纳条件及恢复通道；现场可能仍需修复代码。具体顺序及停止条件在随包说明中列出，不重复开展全基底扩展。
