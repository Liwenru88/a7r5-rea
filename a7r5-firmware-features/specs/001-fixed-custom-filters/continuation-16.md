# 第十六批：原消息入口、双向HELLO和消息引用闭环

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-26`
- Status: `OFFLINE_NATIVE_HELLO_VERIFIED_NOT_INSTALLABLE`

## 本轮交付

完成T03e及T04b2c的限定离线范围：实现并在原AP/CP实际接收地址安装匿名分支，跑通原收发与私有HELLO双向兼容确认；补齐原完整AP请求对象和原CP消息池引用/释放。T03f补齐EVF通知截断及缓冲标志风险，但实际银行关联和最后图像帧尚未完成。T03/T04/T07及整套固件仍未完成，T08/T09保持未完成。

| 文件 | 改动 |
|---|---|
| `native/af_handshake.h/.c` | HELLO兼容确认、固定来源/版本/会话/掩码、截止时间、无回复轮询、CP首会话绑定及拒绝旧/不同会话 |
| `native/af_hs_ap406.c/.S` | AP接收入口私有分流、显式时钟配置；通用/SIMD/条件与浮点状态保存恢复；回原消息释放或原解析 |
| `native/af_hs_cp406.c/.S` | CP任务获取互斥前分流，调用原回复发送器并回原消息归还；原参数仍重放原互斥与分派 |
| `a7filters/native_handshake.py` | 双端研究ELF/原入口前像/真实分支、原OSAL/CP消息池及4组握手联验；默认关闭、PRESET无写拒绝及精确撤销 |
| `a7filters/ap_request.py` | 原基底发送器到完整请求/C++析构/OSAL/CP消费，发送失败和原futex等待边界 |
| `a7filters/cp_message_pool.py` | 原CP分配、完整任务分派、消息引用、原错误回复/发送失败释放及空闲块恢复；原端忽略HELLO的反例 |
| `a7filters/cp_notifications.py` | 原EVF通知24字节封装/低16位截断，原缓冲标志设置/查询；不认定帧完成 |
| `a7filters/cp_machine.py` | 锁定BSS描述符、平面镜像前缀整页的有限RW/NX开放，保留其他边界 |
| `a7filters/baseline.py` | 正式审计自动执行新消息/通知/完整请求证据；新增成对握手模块参数 |
| 新测试及`native_sanitizer.c` | 状态/截止/损坏/旧会话、执行前来源拒绝、BSS范围/NX和20000次HELLO探测 |

地址、字段、接口、状态与接入限制见[原消息与握手入口](handshake-ingress.md)。旧槽位/保存/UI/版本/原子输入核心未改；旧研究ELF保持。新增研究ELF使用现有测试内存ABI助手，没有链接真实设备服务。

## 实际验证

- [最终回归回执](../../../.local/fixed-custom-filters/pytest-16-verified.json)：163项通过，测试输出8.30秒，命令8.525秒，退出0；运行期间源码不变。
- [消毒器回执](../../../.local/fixed-custom-filters/native-sanitizer-16-final.json)：新增握手核心及原生核心重新编译/执行ASan+UBSan，20000次探测，编译0.938秒、执行1.148秒、退出0。之后仅改AP汇编和Python寄存器检查，C/头文件与消毒器输入保持，复用该有效范围；桥接C/S由目标ISA原入口联验覆盖。
- [最终完整审计](../../../.local/fixed-custom-filters/cp-ui-access-406-16-verified.json)及[命令回执](../../../.local/fixed-custom-filters/audit-command-16-verified.json)：82.968秒，重新验签指定修改4.06，736841帧、147成员、71目标及同包库/103资源；原24 AP分支、1218刷新和864快照消费保持。
- 握手4组：成功、截止时间收到回复、损坏请求、CP回复发送失败。后3组均为过期拒绝；原消息池均恢复。默认关闭、原AP通用寄存器/标志、完整SIMD/浮点状态、原CP参数委派及有效PRESET不写成像均验证。
- 原消息池5组、原完整AP请求3组、EVF通知3值及缓冲标志查询保持；单个消息最后引用和图像最后引用继续分列。

最终产物位于`build-16-handshake-verified/`，均只供隔离器：

| 产物 | 字节 | SHA-256 |
|---|---:|---|
| AP握手研究ELF | 71536 | `3dd1eb6fde047b6b0a67e49444818db0a25a7be2b6207d3c476950085562dc65` |
| CP握手研究ELF | 71032 | `85d741ebb5e68c192e41b377853e47f8382ed4126fc7cb6b0e02ce2103071ee8` |

[完整构建命令](../../../.local/fixed-custom-filters/build-16-handshake-verified/commands.json)保留14条编译/链接命令及源码指纹。AP研究基址`0x9040000`、CP研究基址`0x92000000`不代表机身可用装载位置。

## 本轮修正与证据保留

原完整请求初期探索在未绑定C++库重定位/`free`处停止；只补齐已核对同包符号和有界内存后端。原CP消息池夹具曾与既有消费窗口工作区重叠，移到独立范围后再联验；这些不是机身故障或产品恢复事件。

握手初期先拒绝不正确的预期机器码，按同一锁定CP实际前像纠正；随后原AP回复释放触及尚未映射的PLT页和同包OSAL内部PLT，补齐精确页/符号路由，没有把未知访问改成成功。

第一轮完整审计和163项回归通过后，新增完整SIMD哨兵检查实际失败：旧跳板仅保存通用寄存器不足以保护C代码使用的向量状态。先保存[失败回执](../../../.local/fixed-custom-filters/handshake-simd-16-red.json)，再补齐Q0～Q31、FPCR/FPSR；用新目录重建并重新运行受影响联验和回归。旧成功回执/ELF仍保留，但不作为当前汇编验收；最终使用`*-16-verified.json`及`build-16-handshake-verified`。

最终源码/文档/回执/输入/产物、历史不变性及链接核对见[verification-continuation-16.json](../../../.local/fixed-custom-filters/verification-continuation-16.json)。

## 复算

仓库根目录，回执使用新路径；不安装依赖、不修改相机或DAT：

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
  --report .local/fixed-custom-filters/next-private-hello-audit.json

./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short
```

重建请按构建回执使用新目录，保留既有结果。成对模块缺一、未启用研究、错误来源/前像或模块预算超限均拒绝。

## 尚未完成

新增入口目前仅确认协议兼容性，实际启动会话/时钟解析、AP/CP装载线程、UI事件、周期轮询、断线重建尚未接入。握手成功也不会应用纯参数或LUT。

银行到照片EVF/JPG的同版关联、必要消费者绑定、全借用者与最后图像帧仍未证明。LUT拟合还缺真实ISP域/格式/基底模型和量化误差依据；菜单也依赖真实应用/保存回执及合法机内存储。因此没有把这些缺口伪装成完成，下一步仍是离线接线与逆向，不能简单归为只差相机验收。

总体`NOT_VERIFIED`。未操作相机、USB、SSH或真实SD，未读私钥，输入DAT保持原修改4.06，未生成可安装固件，未暂存、提交或推送。
