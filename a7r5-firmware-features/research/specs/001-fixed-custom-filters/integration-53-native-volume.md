# 第53批：原Fsys卷、短别名修复与特殊照片路由

日期：2026-11-02。继续基于修改版4.06，不连接相机、SSH、USB或物理SD，不做CP／ISP硬件模拟。完成T11i1、T11i2限定离线子范围；特殊Gamma来源、真实介质与像素仍未闭合，整体`NOT_VERIFIED`。

## 已修复的实际导入缺陷

此前宿主Fsys端口总把返回名称指针设为长名，掩盖了原FAT短名挂载的差异。本批实际执行原`libInfraFsys.so`，发现：

- 原Fsys初始化、挂载、目录和短名写入可运行；UTF8策略核验通过。
- 短名卷的Find返回`result+0x5AA`，同时在`+0x5B7`填完整UTF8长名。夹具中短别名为`AF000001.BIN`，长名为`暖光.cube`；旧代码按`.BIN`分类，最终列表为空。
- 原`0x40554..64`依据每卷`+0x65A8`选择公开名称指针。该标志由`0x3174C..54`取挂载bit10设置，exFAT类型3另在`0x428E8..F8`自动启用。不能把普通FAT挂载0的行为当成UTF8转换器失效。

生产修复落在[af_fsys406.c](../../custom-filters/native/af_fsys406.c)及其头文件：在已有完整UTF8策略下，以原结果内长名显示、分类，同时按值保存13字节短别名作为该文件的实际只读查找／Open路径。每次重读同时比较长名、短别名、大小、原日期／属性和介质快照；重复别名、非法别名、浏览后别名变化均拒绝。不改全局挂载模式、不重新挂载相机、不修改原Fsys库；AFD1、媒体提供者和菜单ABI不变，新增字段仅属于启动库驻留的易失状态。

使用[回归测试](../../custom-filters/tests/test_fsys406_alias.py)先复现3项失败，再修复；最终与原Fsys、日期、UTF8及仓库服务回归共63项通过（5.24秒、exit0）。新增用例覆盖长名展示／短名打开、别名变化不发布、非法别名和重复别名拒绝。原双遍内容比较、SHA和取消检查保持。

## 原卷软件运行与完整导入服务

新实验位于[fsys406-software](../../custom-filters/experiments/fsys406-software/build_volume.py)。固定原Fsys库SHA为`1986525ba65519a00ee5f41fbf40d2651bfcccb518bbb1e7e8e7fc0a58db7c5b`，没有用宿主函数替代Mount／Find／Open／Read。独立进程仅通过原`mcmn_param_init`参数选择库内现有普通文件后端；客体`/image_mmca`是4MiB合成VFAT文件。测试配置不进入产品启动库，不启动CP／ISP。

两次最终运行分别使用FAT短名模式0及长名模式`0x400`，清单和同一产品仓库DSO固定：

| 步骤 | 两次运行实际结果 |
|---|---|
| 原Fsys Init／Mount | 返回0；原UTF8策略通过 |
| 原短名写入／Flush／Close／Unmount／Remount | 返回0；合成卷中的PROBE.BIN内容保持 |
| 生产适配器扫描 | 3个文件，包括中文、长名CUBE和中文`.a7filter` |
| 原Fsys双遍读取 | 三文件长度／SHA与宿主独立期待一致；原CUBE解析／求值与AFD1解码通过 |
| 取消与介质变化 | 返回取消／STALE，输出元数据不发布 |
| CUBE完整导入服务 | 原卷读取后进入产品参考联合拟合器，保存C07、kind1、generation1，名称“暖光” |
| 电脑参数文件入口 | 同一原卷提供者进入生产AFD1导入，保存C08、kind0、generation1，名称“电脑参数示例” |
| 关闭及重新打开仓库 | C07／C08存在，保存预设逐字节一致 |
| 独立导出卷审计 | 原Fsys卸载后QMP导出；客体SHA与主机一致，fsck及独立FAT／VFAT读取核对5文件通过 |
| QEMU退出 | 两次均为受控QMP退出0 |

运行目录尾缀为`m2k0wma2`和`fxmhu4i1`，完整回执见[原卷独立审计](../../../.local/fixed-custom-filters/integration53-fsys-final/verification.json)。这是**原Fsys卷代码实际软件执行**，比此前仅宿主端口或纯UTF8函数的范围更完整。

媒体模型快照仍为明确夹具；仓库存储使用客体普通私有目录，未冒充机身`/setting`准入、物理卡通知或掉电耐久性。本批`.a7filter`为纯八参数文件，完整AJR2文件的QEMU菜单路径另有第51批证据；不能把本批升级为AJR3完整配方或照片精度验收。恒等CUBE只用于验证本次参考模型转换和事务，不推断任意LUT的实拍误差。

## 特殊2B照片路由：新增证据及仍缺部分

[photo-routes406/audit.py](../../custom-filters/experiments/photo-routes406/audit.py)只执行原CP的纯任务分派、表复制与位掩码窗口，在任何系统／图像helper入口前停止；没有执行CP硬件、ISP、生产器或Gamma提交。固定CP身份错误实际被拒绝。

实际11项分派证明：

- `4694C4`与`469620`的state0分别到`46F1C4`、`4700CC`；state1到`AE80CC`，state2到`AE843E`，state3在原栈内调用`46DA78`。不能按线性反汇编文本顺序代替TBB真实分支。
- `4696D0`正常序列的state1到`480DE4`，state2到`470314`，保持原任务参数。
- 原两个特殊调用窗口确实向`46F3AC`传`0x2B`；其他已证调用传`0x7F`或`0xEB`。
- 原`46F57A`只有`mask&0x80`时才进入`AEC71A`，`0x2B`与`0x7F`均跳过。本批按原指令执行该判断，没有由宿主重写条件。
- 原阶段11选择器`AE4496`从`[A+5994]+14`取计划选择值。选择2／4经原表复制得到两个特殊callback；该字段不是`A+218`。本批没有重新证明历史“请求type4／type9”称谓与所有运行期计划的对应关系。

详见[当前路由回执](../../../.local/fixed-custom-filters/integration53-photo-routes-v2/verification.json)。这些证据明确了入口和Gamma绕过条件，**没有证明特殊路径此前由哪个生产者写入Gamma银行、该银行是否属于同一A／Q及滤镜版本，或最终consumer是否在该路径启用Gamma**。

因此本批不新增无条件Gamma补发，不将普通SCNYC的先后关系套到特殊请求，也不宣称两特殊路线的完整LUT已生效。要安全关闭此缺口，仍需要原特殊计划的Gamma写入→同Q银行→consumer选择的完整来源依据；实际运行选择依赖原模式／backend状态，当前没有对应运行快照或链路回执。禁止设备操作的边界保持，未尝试读取相机来补数据。T03f2及T11i父项保留未完成。

## 新研究包与验证

已把短别名修复编入新的产品启动库97848字节，SHA为`ac6c92c9e3d7f62854544fbcc14926728a157828ded54c319c0f1580b67efdff`。UI／请求／仓库DSO及AP字节保持，中文菜单、32槽与原厂12外观保护沿用既有实现。原Fsys库未修改。当前CP重新构建并严格正逆，51挂点／69窗口和原容量保持，最终CP字节仍与第52批相同。

- 启动依赖及产品构建：66 passed，11.09秒、exit0；与63项为分别记录的定向组，不冒充完整测试集。
- 原Fsys／生产服务完整软件运行：两次正常QMP退出；独立VFAT文件审计通过。
- 当前CP原分派／掩码：11分派、4调用mask、4Gamma条件、2计划选择窗口及错误身份拒绝通过；未运行系统／图像端点。
- 最新4.10研究DAT：754525608字节，SHA256如下；正常研究签名、独立解密、全归档回读、四产品DSO与60处复杂图像载荷独立审计通过。

```text
36cf5ff87c9e1f2baac0ac531e22abbaf50c70cf7b5443dc156c9cc31f59619a
```

[新研究候选](../../../.local/fixed-custom-filters/integration53-release410-v2/update410/BODYDATA.DAT)；[包回执](../../../.local/fixed-custom-filters/integration53-release410-v2/update410/verification.json)；[内容审计](../../../.local/fixed-custom-filters/integration53-final/verification.json)。第52批包和所有失败目录保留，没有覆盖原输入DAT。第一次本批封装因CP构建回执包含已变化的Fsys头文件而被严格门禁拒绝；重新构建当前CP并生成新回执后封装通过，没有豁免来源检查。

其他保留失败包括：实验编译误列仅头文件模块、串口后台命令末尾语法、短名模式中文创建被拒和旧适配器空列表、任务审计最初错列TBB顺序／在途栈假设。失败均单独保留，最终声明仅引用当前通过回执。

本轮未重跑原厂菜单像素验收：原UI／AP／中文资源未变，复用第51批的软件菜单证据；这不能代替新产品启动库的真实机身启动或最终取景／JPG。最新候选仍是研究包，不是完整实机验收版，`device_installation_approved=false`。
