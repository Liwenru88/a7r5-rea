# 第十七批：原任务启动、单调时钟、事件轮询与缓冲身份

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-26`
- Status: `OFFLINE_TASK_RUNTIME_VERIFIED_NOT_INSTALLABLE`

## 本轮结果

完成T04b2d的限定离线范围：原AP通信任务第一次接收时自动取得非零随机会话和单调时钟、通过原OSAL发送HELLO；原CP任务启动点初始化未配置握手；原接收循环执行有限等待、超时轮询及空消息分流。保留原厂消息与消息释放，不用原future无限阻塞。15组目标入口联验、177项回归和完整修改4.06输入审计通过。

T03f新增原缓冲占用/拒绝/归还/再占用证据与两项反例，仍未证明银行到照片EVF/JPG的版本关联和最后图像帧。T03/T04/T07整体、T05实际持久化、T08b拟合和T09实际菜单仍未完成；本轮没有生成可安装固件。

## 主要改动

| 文件 | 行为 |
|---|---|
| `native/af_runtime.h/.c` | 单一通信拥有者的一次启动、1000毫秒截止、50毫秒有界接收、单调性检查及首故障保持；无自动重建 |
| `native/af_runtime_ap406.c` | 固定AP原系统导入、8字节随机源短读/EINTR/关闭检查、dlsym解析CLOCK_MONOTONIC、原分配/发送/接收和空错误退避 |
| `native/af_hs_ap406.c/.S` | 条件连接新运行时；原接收调用分支，有消息/空消息分别回原分派/循环，完整通用/SIMD/浮点/条件状态保护 |
| `native/af_hs_cp406.c/.S` | 原任务序言挂钩；只初始化状态0，已绑定会话不重置；保持原队列和任务序言 |
| `a7filters/native_runtime.py` | 原线程注册器、四处匿名分支、原OSAL、目标系统导入及15组运行时场景；符号/前像/寄存器/撤销检查 |
| `a7filters/cp_notifications.py` | 原句柄占用/−10拒绝/归还/再占用，旧归还重放及全局标志覆盖反例 |
| `a7filters/baseline.py` | 新增成对运行时研究模块参数，研究模式/文件预算/来源检查；与旧所有模块联合审计 |
| 定向测试与`native_sanitizer.c` | 一次启动、截止/时钟回退、失败关闭、非空消息所有权、源组件及CLI门控；20000次运行时探测 |

原入口、系统导入、状态、消息所有权和缓冲反例见[运行时接入证据](runtime-access.md)。已有32槽UI、普通目录保存、完整预设及银行/帧核心保持原范围。

## 实际验证

| 证据 | 结果 |
|---|---|
| [最终回归](../../../.local/fixed-custom-filters/pytest-17-final.json) | 177 passed in 7.09s；命令7.330秒、退出0，执行期间源码不变 |
| [ASan/UBSan](../../../.local/fixed-custom-filters/native-sanitizer-17-final.json) | 20000次输入/状态/HELLO/运行时探测及已有持久化/版本/整预设/13消费者/3银行/64帧契约；编译0.997秒、执行0.511秒，退出0 |
| [完整同包审计](../../../.local/fixed-custom-filters/cp-ui-access-406-17-final.json)与[命令](../../../.local/fixed-custom-filters/audit-command-17-final.json) | 151.514秒；指定修改4.06重新验签，736841帧、147成员、71目标和103资源，输入开始/结束身份保持 |
| 同报告`native_task_runtime` | 原`IWrapperImaging`登记、双端启动/接收挂钩，15组自动会话/超时/随机源/时钟/分配/发送/接收失败及旧CP会话拒绝；原消息保持，完整寄存器哨兵及四处撤销通过 |
| 同报告`cp_native_notifications.buffer_claim_reuse` | 同句柄占用/拒绝/再占用、旧归还重放可清除新占用；无关句柄占用可清全局标志，而旧头仍为归还标志 |
| 原有联合验证 | 第十六批4组HELLO、原消息池/完整AP请求，以及原24处AP界面分支、1218刷新和864参数快照消费保持 |

15个运行时场景分别为成功、无消息截止、短读/EINTR、随机源打开失败、零会话、EOF、关闭失败、时钟符号缺失、时钟错误、非法timespec、分配失败、发送失败、接收错误、时钟回退和CP拒绝其他会话重启。系统服务、跨CPU搬运、锁/线程和驱动结果均明确使用后端，不执行宿主设备或目标系统调用。

最终研究模块位于`build-17-runtime-final/`，研究基址沿用`0x9040000/0x92000000`，不能解释为机身装载许可：

| 产物 | 字节 | SHA-256 |
|---|---:|---|
| AP运行时ELF | 77168 | `8a2ec37a5f9e1ff1738582e3e1cbd21268459397bb635b3133a93058bc786903` |
| CP运行时ELF | 71188 | `196da0a566e553230d1e0b9437ae385ed3cf2032804c788b74236ac122297beb` |

[构建回执](../../../.local/fixed-custom-filters/build-17-runtime-final/commands.json)记录16条编译/链接命令与原生源码指纹。源码/文档/产物/历史/引用终检见[批次指纹](../../../.local/fixed-custom-filters/verification-continuation-17-final.json)。

## 本轮发现及修正

初版运行时在接收返回错误且无消息时立即回原循环，缺少退避。新增原入口断言实际失败并保留[失败回执](../../../.local/fixed-custom-filters/runtime-idle-17-red.json)后，接入原usleep导入请求50毫秒退避，在新目录重建并通过最终完整审计；初版研究ELF和回执继续保留，不作为当前接线验收。

第一轮175项回归和完整审计通过后，终检发现核心在时钟回调缺失时返回错误但未设置故障，私有回复会沿用旧时间值。新增两种缺失形式的回归实际失败并保留[复现回执](../../../.local/fixed-custom-filters/runtime-clock-port-17-red.json)，随后修正为关闭握手，重新构建并执行177项回归、ASan/UBSan和完整原入口审计。最终仅采用`*-17-final.json`与`build-17-runtime-final`；前一轮成功结果保留为历史，不能代替当前代码验收。

线程注册探测最初在未映射原启动状态页时停止。依据原`0x3552d94`的实际写入，仅补充`0x5c75000`源页，随后原窗口完成；没有放宽未知地址处理或伪造整个线程/TLS启动。

句柄重用反例中“旧归还”是显式夹具重放，证明原接口无法辨识版本；没有观察真实迟到回调，也没有证明像素分配器重用或DMA结束。AP发送失败后的缓冲所有权仍未查明，没有猜测free。随机64位会话有碰撞概率，不能代替严格的重建代号及帧排空协议。

## 复算

仓库根目录，输出选择不存在的新文件；不安装依赖、不修改DAT：

```sh
PYTHONPATH=a7r5-desktop/prepared/engine/site:a7r5-firmware-features/custom-filters \
  ./.venv/bin/python -B -m a7filters.baseline \
  /Users/wenruli/Desktop/索尼/BODYDATA.DAT --investigate-ui \
  --ui-adapter .local/fixed-custom-filters/build-12/ui-adapter.elf \
  --ap-ui-module .local/fixed-custom-filters/build-12/ap-ui-hooks.elf \
  --cp-parameter-adapter .local/fixed-custom-filters/build-13-verified/cp-parameters.elf \
  --cp-atomic-adapter .local/fixed-custom-filters/build-15-final/cp-atomic.elf \
  --ap-handshake-module .local/fixed-custom-filters/build-16-handshake-verified/ap-handshake.elf \
  --cp-handshake-module .local/fixed-custom-filters/build-16-handshake-verified/cp-handshake.elf \
  --ap-runtime-module .local/fixed-custom-filters/build-17-runtime-final/ap-runtime.elf \
  --cp-runtime-module .local/fixed-custom-filters/build-17-runtime-final/cp-runtime.elf \
  --report .local/fixed-custom-filters/next-task-runtime-audit.json

./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short
```

## 剩余门槛

| 剩余项目 | 当前具体缺口 |
|---|---|
| 运行时实接入 | 完整装载、原线程/TLS及栈、系统服务/驱动超时；AP发送失败缓冲所有权；可信双端重建与银行/帧排空 |
| 银行到EVF/JPG | 照片模式必要消费者、完整不可变银行集合取得、`0x165d758/0x165d820`到显示/编码对象及每个借用者的同版关联 |
| 最后图像帧 | 真实拥有者/借用者终点、失败/取消、显示/编码/DMA与缓冲管理器完成；原句柄/标志不可作确认 |
| LUT拟合 | 原ISP输入/输出域、原生格式、12基底模型和量化行为；这些未查明前无法交付有效拟合或误差保证 |
| 菜单与保存 | 合法机内路径/容量、真实菜单/SD与原工作槽事件、真实应用回执；预览取消提交新恢复版本，保存回读与成像确认分开 |

这些仍包含离线逆向和实现工作，不能概括为“只差相机测试”。总体保持`NOT_VERIFIED`。未操作相机、USB、SSH或真实SD，未读私钥，输入DAT保持原修改4.06，未生成安装候选，未暂存、提交或推送。
