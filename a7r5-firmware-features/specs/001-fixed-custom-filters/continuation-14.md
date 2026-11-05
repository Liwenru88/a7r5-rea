# 第十四批：原AP/CP消息联验与JPEG持有关系

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-26`
- Status: `OFFLINE_NATIVE_MESSAGE_CHAIN_VERIFIED_NOT_INSTALLABLE`

## 本轮交付

完成T03c的限定离线范围：原AP封装与原CP任务/表分派到参数消费联验，参数银行发布定位，以及照片JPEG最后请求和持有关系验证。T03/T04b/T07整体仍未完成，LUT拟合与实际菜单仍未接入。没有把隔离ioctl后端当作物理通信，也没有安装固件挂钩。

| 文件 | 实际变化 |
|---|---|
| `a7filters/ap_cp_messages.py` | 同包原AP发送器、分配助手、OSAL库ioctl封装、来源字段、原CP消息任务/表分派、运行快照与颜色/锐度窗口联验；发送失败和非原子更新反例 |
| `a7filters/cp_frame_stages.py` | 原LiveView阶段对象/虚表类型、照片CapRsrc_JPG虚表；8组颜色/锐度银行独立发布、5组最后JPEG请求成功/失败及持有/归还路径 |
| `a7filters/cp_machine.py` | 仅对锁定初始化数据段的显式整页开放匿名RW/NX；阻塞互斥模型未获锁即停机 |
| `a7filters/baseline.py` | 同一已验签DAT读取并核对`libosal_uipc.so`，正式审计自动执行上述联验；原71项目标基线保持 |
| `tests/test_ap_cp_messages.py`、`test_cp_realtime.py` | 错误库/消息长度/错误CP在执行前拒绝，数据段边界/权限/描述符及阻塞锁失败验证 |

完整地址、字节格式、失败路径、执行和夹具边界见[消息及帧接入证据](communication-frame-access.md)。本批未改任何原生C、汇编、链接脚本、既有研究ELF、冻结材料或输入DAT。

## 对实际接入的影响

1. 找到两端相同队列`0x90030001`和来源`0x80020002`，消息封装与原CP接收已联合执行；物理IPC、完整future请求/回复与新版本握手仍未验证。
2. 9条原命令之间可产生新基底/新对比度与旧其他参数的快照。整预设切换需要原子输入，不能把连续发送当作事务。
3. 颜色与锐度银行分别按待处理位发布到操作上下文，没有同版本校验。输入原子化后，仍需所有必要消费者成功及输出银行统一发布。
4. 高光/阴影/褪色经原分派器设置额外`0x19c999d`标记；只覆盖前缀会绕过这一副作用，其下游消费仍待证明。
5. 最后JPEG请求成功后，独立持有计数仍可为1；请求完成和JPG资源归还均不能转为整帧/参数版本释放。

已将这些条件保留为实际CP接入门槛。没有新增未经证明的命令ID或把未知消息当作握手成功；第十三批纯参数适配器仍只承担编码及限定消费验证。

## 验证结果

- [pytest回执](../../../.local/fixed-custom-filters/pytest-14-final.json)：149项通过，6.37秒；实际编译C，两种目标ISA的20槽保存/版本/前缀闭环保持。
- [完整审计回执](../../../.local/fixed-custom-filters/cp-ui-access-406-14-final.json)：指定4.06重新验签，736841帧、147成员、71目标、同包OSAL/其他库及103资源；原24 AP分支、1218刷新查询、864快照消费与资源加载保持。
- [审计命令](../../../.local/fixed-custom-filters/audit-command-14-final.json)：46.649秒，退出0；执行期间源码不变。
- 原C及其头文件/原生测试逐字节未改，复用E-108的ASan/UBSan 20000次探测，不重复跑相同成功范围。
- 最终源码/文档/回执/输入指纹及链接核对见`verification-continuation-14.json`。

最初原CP表写入与额外标记触及隔离器未开放的映射，执行器实际报错停止。核实初始化数据段及真实`0x969df8`写入后，只开放已声明数据页/标记页，再执行通过；没有把未知访问改成返回成功，也没有开放代码写权限。探索回执保留，正式审计使用最终源码。

## 复算

仓库根目录运行，使用新回执路径，沿用未改的研究ELF。只在内存执行，不生成安装包。

```sh
PYTHONPATH=a7r5-desktop/prepared/engine/site:a7r5-firmware-features/custom-filters \
  ./.venv/bin/python -B -m a7filters.baseline \
  /Users/wenruli/Desktop/索尼/BODYDATA.DAT --investigate-ui \
  --ui-adapter .local/fixed-custom-filters/build-12/ui-adapter.elf \
  --ap-ui-module .local/fixed-custom-filters/build-12/ap-ui-hooks.elf \
  --cp-parameter-adapter .local/fixed-custom-filters/build-13-verified/cp-parameters.elf \
  --report .local/fixed-custom-filters/next-comm-frame-audit.json

./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short
```

## 尚未闭环

实际AP工作槽事件到完整请求/回复、物理IPC与版本握手，EVF/拍照上下文身份、所有银行消费者、全部资源持有退役和最后帧引用仍缺证据。下一条具体释放链是`0xae4170 → 0x462734 → 0xae2afa/0xae2bda`及`0x47ff64`后的多资源清理；仅JPEG池归还不足以安装版本释放挂钩。

LUT拟合缺各基底的真实ISP模型、原生格式/量化和独立误差测量；实际机内存储和菜单缺合法位置、完整4.06运行客体及真实页面/SD动作。原生解析、普通目录保存、消息窗口均不能替代这些功能，不能将现有产物称为可用32槽固件。

总体`NOT_VERIFIED`。未操作相机、USB、SSH或真实SD，未读取私钥，指定修改版4.06与现有六款/FL2/FL3保持；未生成可安装固件。
