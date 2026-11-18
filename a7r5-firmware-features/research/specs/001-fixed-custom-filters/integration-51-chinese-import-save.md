# 第51批：中文、双入口导入与保存的软件闭环

日期：2026-11-02。范围：修改版4.06派生代码的离线实施与QEMU软件运行；不操作相机，不新增CP／ISP硬件模型。

## 本批实现

`custom-filters/experiments/boot-menu406/`补齐中文初始化、软件SD端口、虚拟机身仓库和只读记录导出／恢复。实际执行原厂AP和当前UI／仓库DSO，复用原厂菜单、文件选择、槽位选择、八项调参及保存状态机，没有另画一套测试界面。

- `chinese-ui.inc`：在原UI首次CreateScreen线程调用同包原厂语言银行和setter，读取语言25确认；恢复被客体/tmp挂载遮住的三份同源字体。中文名称经生产标签拥有者到原文字组件显示。
- `qemu-storage.inc`：仅编入生成的实验启动库，把两个明确的软件目录接到既有提供者接口；扫描、文件稳定读取、二次摘要核对和仓库导入仍用生产代码。产品Fsys路径没有替换。
- `build.py`：新建16MiB FAT16镜像；`run.py`将它装入隔离客体RAM块设备并挂载为/setting。真实Linux挂载信息、设备号、root权限和容量满足未修改的`af_storage406_open`检查，不伪造/proc或存储成功回执。
- `store-export.c`／`store_records.py`：只读导出标记及20槽双银行的实际原字节；客体生产codec与宿主独立CRC／SHA核对后才能恢复到另一全新客体。没有导出任意路径或修复坏记录的接口。
- `run.py`：保留每次固定按键及新帧屏障；TCG拟合时允许有界重试原取帧助手的2秒超时，最长45秒，不重发按键、不显示旧帧、不忽略固件异常。串口原始日志保留，解析时仅沿用现有UDIF日志去噪。
- `test_ap_ui_dynamic.py`／`test_ap_ui_import_targets.py`：补齐旧服务夹具缺失的原5591行登记结果，修正旧六用户槽“可选择但必须确认替换”及扩展禁用后原厂委派的过期断言；没有放宽生产检查。

软件协议对端保留真实HELLO编解码与原AP接收入口，另支持软件参数／配方校验。当前菜单验收实际证明HELLO路径；没有以ACK证明CP图像消费，也没有执行CP／ISP硬件模拟。

## 实际工作流结果

主运行：`boot-menu51-workflow-v2/execution/runs/native-boot-menu406-kugv5ljt`。

| 操作 | 观察到的结果 |
|---|---|
| 中文菜单、文件与名称 | “自定义滤镜”“01_照片基准.cube”“电脑参数示例”等实际原厂像素正常，无缺字框 |
| 卡1导入CUBE至C07 | 菜单显示“已导入”；记录generation1、converter2、1943B AJR2配方、源LUT和载荷SHA完整 |
| 卡1导入.a7filter至C20 | 生产AFD1解码和保存成功；本次使用明确的纯参数电脑文件，名称及八值原样保留；没有将其冒充完整电脑拟合LUT文件的本次QEMU验收 |
| 完整AFD1/AJR2导入至C09 | 补充运行从SD文件浏览选择“04_完整配方.a7filter”，生产导入器保存成功；目标AFD1载荷与来源原字节一致，其他槽不变 |
| 切换卡2并取消 | 能显示“03_第二卡.cube”，返回显示“已取消”；全部文件、版本及缺失银行与取消前一致 |
| 原厂创意外观调参 | C20的八项从`[1,2,0,0,0,4,3,1]`改为`[2,3,1,1,1,5,4,2]`，中文参数页面与底部快照一致 |
| 保存前检查 | 管理页出现C20及星号；实际记录仍为旧值，没有隐式保存 |
| 显式保存 | 显示“已保存”，新增C20_B generation2，saved为新八值，initial仍为导入八值，C07不变 |
| 另存为C08 | 显示“已另存为”；新增“自定义C08”，保存八值为工作版本，源C20保留 |

CUBE夹具为恒等sRGB LUT。该次固定参考模型43个验证色的ΔE76统计均为0、clipped=0。这个结果只证明恒等用例在现有参考域的转换和记录报告，不能用于推断任意LUT误差或真实照片准确度。

独立恢复运行：`boot-menu51-final-recovery/execution/runs/native-boot-menu406-zdhnoy02`。把上述5份实际文件（标记、C07_A、C08_A、C20_A、C20_B）放入全新VFAT，由自然启动的生产仓库恢复，没有重新导入SD文件或设置目录内存。再次导出时5份文件逐字节相同，36份缺失银行状态相同；原厂创意外观界面显示C07中文LUT名称、C08另存名称及C20已保存的完整八值。

两个主运行共140帧；完整配方补充运行`boot-menu51-full-prepared/execution/runs/native-boot-menu406-wpfxevkr`再核对29帧，共169帧，三次QMP退出均为0。均保留自然启动准入、中文setter、实际菜单及原始帧。审核脚本`audit_storage.py`输出`.local/fixed-custom-filters/boot-menu51-final/verification.json`；`audit_prepared.py`追加输出`full-prepared/verification.json`，不覆盖先前回执。另有49项定向宿主／AP指令服务边界回归通过（6.33秒、exit0）和3项覆盖确认回归通过（0.54秒、exit0）。

完整配方夹具来自本次实际CUBE转换记录的AFD1原字节，用于验证完整配方文件格式与菜单导入，不声称它是电脑高精度求解器的精度对照。本次实际覆盖converter2/AJR2；converter3/AJR3菜单导入仍未在QEMU中重测。

实际恢复画面：[C07中文LUT名称](../../../.local/fixed-custom-filters/boot-menu51-final-recovery/execution/runs/native-boot-menu406-zdhnoy02/menu-035-UP.png)、[C20保存后的八项参数](../../../.local/fixed-custom-filters/boot-menu51-final-recovery/execution/runs/native-boot-menu406-zdhnoy02/menu-020-RIGHT.png)。同次原列表还实际显示FL2／FL3；这证明列表保留与可选，不证明实拍效果。

## 重现与交付边界

使用现有根环境构建、现有QEMU环境运行，不安装新依赖。每次构建使用全新输出目录；保持TTY，发送固定JSON按键，以STOP结束。具体开关和只读导出／独立恢复方法见[实验说明](../../custom-filters/experiments/boot-menu406/README.md)。

```sh
a7r5-qemu/.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/boot-menu406/audit_storage.py
a7r5-qemu/.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/boot-menu406/audit_prepared.py
```

审核目录只创建一次；再次审阅可读取其冻结回执，不覆盖原证据。

产品启动库仍为97208B，SHA256 `cfec1cc78bb2f272cbd292296f2cc8bf88979e546be0033eb4038afc0b751be2`。实验库包含SD目录端口，SHA不同，不能部署相机；清单分别记录两者身份。原厂AP、12个外观包括FL2／FL3、输入DAT及默认QEMU清单没有因本批验证而改写，没有生成或刷写新的升级包。

保留的失败包括：缺少内核utf8 NLS导致第一次虚拟VFAT挂载失败、只读导出器编译列表误列内联头文件、5秒输入等待及2秒客体取帧窗口不足、退出码行／串口UDIF插入导致严格导出解析拒绝、单实例QEMU锁拒绝第二实例。均未删除或改写为成功；最终主运行使用修正后的独立运行器。最初6项旧测试因过期夹具／断言失败，修正后相关49项通过。

本批完成的是中文、CUBE及AFD1（纯参数／完整AJR2）双入口、八项显式保存／另存／取消和独立恢复的QEMU软件闭环。原生Fsys中文文件名／真实SD、实际机身持久化耐久性、真实CP版本握手和EVF／JPG像素、AJR3文件的本次QEMU菜单导入及电脑优化精度对照仍未据此验收。整体保持`NOT_VERIFIED`，T12继续禁止执行。
