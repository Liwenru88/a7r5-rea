# 第52批：原生Fsys集成回归与4.10研究候选封装

日期：2026-11-02。基于用户现有修改版4.06离线工作，不连接相机、不做CP／ISP硬件模拟。本批完成可重复封装；完整功能与设备验收仍为`NOT_VERIFIED`，不能据此宣称安全可刷。

## 交付结果

候选：[4.10研究DAT](../../../.local/fixed-custom-filters/integration52-release410-v2/update410/BODYDATA.DAT)。大小754525608字节，SHA256：

```text
622b8aeb1074853f78d29167043dfddfa607585a51470da993eb2e7398657230
```

这是4.06内容派生的研究版本号，不表示索尼官方4.10。正常研究签名验签、独立解密、全归档回读和分区校验均通过；没有修改更新器或绕过版本比较。原输入`/Users/wenruli/Desktop/索尼/BODYDATA.DAT`仍为`3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2`。源文件、故障4.09和失败输出目录均保留。

沿用既有32槽、中文原菜单、CUBE／AFD1双入口、八项编辑及保存／另存源码。12个原厂外观包括FL2／FL3保留，原六个自定义槽计入20用户槽。照片标记扩展仍包含，实际叠加未验收。产品库继续使用原生Fsys，实验软件SD目录端口没有进入产品启动库；此前QEMU软件闭环的范围见[第51批](integration-51-chinese-import-save.md)。

## 原生SD／Fsys补证

生产`af_fsys406_scan/read`及原生API绑定已有实现，本批未重写该生产适配器。新测试端口[fsys406_service_port.c](../../custom-filters/tests/fsys406_service_port.c)在宿主普通文件之上提供明确的Fsys接口夹具，使[仓库导入测试](../../custom-filters/tests/test_repository_import_service.py)第三种后端实际经过生产Fsys适配器、媒体提供者、稳定重读、转换任务、事务持久化和重新打开。

- 成功导入、转换取消、源摘要变化拒绝、中文／长文件名四个场景全部通过；原POSIX和通用提供者两组保持，共12个用例。
- Open／Read／Close使用高32位非零的64位token，防止错误截断成fd；Find私有结构、编码context与volume context的隔离保持生产检查。
- 同包原FindNext结尾返回2，Open／Read／Close和Find结构字段与当前适配器相符；没有将未知错误统一当成功或放宽介质快照检查。

另新增[原Fsys编码执行器](../../custom-filters/experiments/fsys406-software/verify_codec.py)，在纯AArch64 CPU软件环境执行同包`libInfraFsys.so`的两个原始UTF8函数，不运行构造器、卷初始化或设备I/O。32个字符、64次原函数调用涵盖中文、四字节字符和组合字符；输出UTF16／UTF8、缓冲区边界及返回的编码宽度全部核对。库SHA为`1986525ba65519a00ee5f41fbf40d2651bfcccb518bbb1e7e8e7fc0a58db7c5b`。

上述宿主卷端口不是原Fsys卷实现；纯编码器执行也不是完整文件系统运行。真实卡初始化、挂载、两物理槽及原Fsys卷读写均未执行，机身持久化耐久性未验收。

## 取景／JPG接入状态

当前原生CP模块重新交叉链接并完成FAT分区staging，51个挂点、69个修改窗口逐项校验，CP和整个FAT分区均可严格逆回原输入，其他文件／元数据保持。

| 项目 | 本次结果 |
|---|---|
| RX | 39192／40960字节 |
| 静态RW | 48744／49152字节；余408字节为既有启动尾，不是额外可用空间 |
| 原生挂钩合同 | 1280字节，51个挂点 |
| Capture／颜色／第二Gamma | 保留已证普通照片域、同源版本和原厂分组回退；未知路由仍委派原厂 |
| CP最终SHA256 | `91b8dd65b84eda2f9aa424ae3785afdc78cc689de3663c0aed268790440775ae` |

**CP最终字节与原4.09研究候选相同。** 本批是当前源码构建／静态重新核验和封装，没有新增最终EVF/JPG消费者或扩大Gamma格式。普通Capture及颜色接入的已有范围见[第46批](integration-46-capture-flow.md)；特殊2B请求、全部模式／基底、实际CP握手与最终像素不能由链接、版本快照或资源回池推断。T03f2父项和T12不勾选完成。

## 实际修复的封装阻塞

1. 图像生成器已修复复杂记录偏移，但[ext2图像追加白名单](../../../a7r5-dat-tool/a7r5dat/ext2_image_append.py)仍绑定故障4.09摘要，严格门禁正确拒绝新资源。本批仅更新两份已知目标摘要，源摘要、inode、大小等保护保持；加入修正版／故障版摘要回归，先复现2个失败再修复。
2. [正常DAT封装器](../../custom-filters/experiments/packaging406/build_update.py)增加schema3＋照片标记范围的研究4.10白名单，并统一公共入口及内部范围检查。4.10错误范围与4.11继续拒绝，不改变官方更新器。
3. 新增[离线构建脚本](../../custom-filters/experiments/release406/build_candidate.py)：顺序执行AP预检、产品启动库、冻结清单、USR完整回读、正常DAT封装。每步保留命令、输出、退出码；失败目录保留。封装阶段使用项目已有DAT专用环境，避免根环境的密码库安装元数据缺失。
4. 新增[独立内容审计](../../custom-filters/experiments/release406/verify_candidate.py)：从最终DAT独立回读的USR重读UXD表，不复用图像生成器。两文件各3511个原载荷、其中各30个复杂载荷逐字节保持，新增编号图标各14个；合计60个曾出错的复杂偏移全部核对。四份产品DSO与冻结清单的大小／SHA一致。

两修正图像SHA分别为`f54f991e79c68da5d4c62b2605403af9b427c2526169b32426064a5e8ee9ce59`和`827a21b2d113436e2839baa5c2e3a9d9b03f422a13626ee37e25aadf35ae5667`。启动库97208字节，SHA为`cfec1cc78bb2f272cbd292296f2cc8bf88979e546be0033eb4038afc0b751be2`；该库含此前连续RX映射修复。封装不再使用已知错误图像摘要。

## 验证与回执

本批执行的验证组有重叠，不累加成全套测试数量：

| 范围 | 实际结果 | 证据性质 |
|---|---|---|
| 仓库三后端＋当时封装回归 | 38 passed，6.44秒，exit0；其中仓库12项、新Fsys4项 | 本轮工具执行输出；后续公共版本入口另补2项 |
| 最终`test_upgrade_package.py` | 28 passed，0.07秒，exit0 | 本轮定向回归输出 |
| 图像与ext2追加回归 | 10 passed，0.66秒，exit0 | 本轮定向回归输出 |
| 启动依赖／产品构建 | 66 passed，11.48秒，exit0 | `integration52-software-v2/commands.json`保留完整命令与输出 |
| 原编码器、CP链接／staging | 纯编码器通过；51挂点／69窗口和严格正逆通过 | 独立回执，不等同CP运行 |
| 完整封装 | 五步exit0，研究验签／解密／归档回读通过 | `integration52-release410-v2/commands.json`及最终包回执 |
| 最终内容独立审计 | 原载荷、60复杂记录、四DSO、原DAT均通过 | `integration52-final/verification.json` |

没有在本批重跑全测试集或QEMU。此前三次QEMU正常退出、169帧中文导入／保存仅为显式软件SD／软件协议对端范围，不能视为本包的原生SD或CP效果验收。初次过期图像摘要拒绝、4.10公共入口拒绝、密码库元数据缺失及测试夹具问题均保留，没有改写为成功。

- [构建总回执](../../../.local/fixed-custom-filters/integration52-release410-v2/verification.json)
- [最终DAT校验](../../../.local/fixed-custom-filters/integration52-release410-v2/update410/verification.json)
- [独立内容审计](../../../.local/fixed-custom-filters/integration52-final/verification.json)
- [原编码器执行](../../../.local/fixed-custom-filters/integration52-fsys-codec/verification.json)
- [CP分区正逆回执](../../../.local/fixed-custom-filters/integration52-cp-staged/verification.json)

复现时使用全新输出目录，不覆盖已生成的回执：

```sh
.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/release406/build_candidate.py \
  --source-dat /Users/wenruli/Desktop/索尼/BODYDATA.DAT \
  --source-workspace .local/fixed-custom-filters/integration52-source406 \
  --software .local/fixed-custom-filters/integration52-software-v2/verification.json \
  --cp-receipt .local/fixed-custom-filters/integration52-cp-staged/verification.json \
  --output .local/fixed-custom-filters/integration52-release410-rebuild
```

本批达到“可离线封装并独立校验研究升级包”。真实SD、真实AP／CP启动协商、最终EVF／JPG像素、机身启动稳定性与升级接受均未确认，不是仅凭文件签名就完成了滤镜全功能验收。`device_installation_approved=false`，本轮没有执行或安排刷机。
