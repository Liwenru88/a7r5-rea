# 第十三批：CP实时证据与纯参数适配

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-26`
- Status: `OFFLINE_PARAMETER_ADAPTER_VERIFIED_NOT_INSTALLABLE`

## 本轮交付

已完成T03a、T03b、T07b的限定离线范围。新增可执行CP证据和真正运行的纯参数ARMv7适配器；没有完成整套滤镜功能，也没有安装CP挂钩或生成固件。

| 落点 | 本轮变化 |
|---|---|
| `a7filters/cp_machine.py` | 锁定CP摘要、原代码RX、显式RAM范围/预算、未知内存报错；只提供明确的0x24互斥模型，无RTOS/硬件/设备转发；弱引用回调避免持有整份CP映像 |
| `a7filters/cp_realtime.py` | 执行运行期快照、四类消费者复制、13身份完成回调/汇总、队列拒绝、两种双缓冲尾部、JPEG回调/计数退役及浅复制反例 |
| `native/af_cp406.c/.h` | 原厂12基底→CP编号、八项字段覆盖、其他帧前缀字节保持；独立缓冲、非法/越界/重叠/LUT拒绝；字段匹配只作回读检查 |
| `a7filters/target_cp406.py` | 独立ARMv7 ELF与同包原AP/CP联验；12基底、八字段编码、原上下文与颜色/锐度派生通过，未安装实际CP分支 |
| `a7filters/baseline.py` | 增加`--cp-parameter-adapter`；必须同时启用研究模式，普通文件/尺寸门槛保持；正式回执绑定同一DAT/AP/CP来源 |
| `tests/` | 原20槽保存/版本机器码闭环接入参数前缀；补适配与执行器拒绝/生命周期边界、512地址预算回归及消毒器探测 |

细节、字段表、风险及具体接入改动见[CP接入证据](cp-access.md)。原AP挂钩C/S/链接脚本、原槽位/保存/版本实现、现有六款、FL2/FL3和冻结材料未改。

## 关键发现

1. 原`0x4b8dc0 → 0x898548`是运行期有锁复制入口，能把通知状态送入master，继而进入上下文和颜色/锐度派生窗口。外层调度、流身份与完整ISP尚未执行。
2. 原锁拒绝路径可能仍返回0；队列拒绝也清完成标记。两个现象都不能确认成像应用成功。
3. C4上下文浅复制保留根指针。原更新后，未改变的旧上下文会读到新参数；每帧必须拥有受保护的参数/动态字段，不能只保护预设银行。
4. JPEG回调会记录两个状态字并准备事件；退役可在计数2→1时给出ready=1。单个回调、ready或任务完成标记均不是最后帧释放。
5. UI普通基底号并非CP号，FL2/FL3是19/20。新适配器对照原AP转换通过，LUT继续明确拒绝，避免未经校验的载荷被当成可用滤镜。

## 实际验证

| 证据 | 结果 |
|---|---|
| `pytest-13-final.json` | 143项通过，2.16秒；主机C契约、两种目标ISA各20槽及新隔离器边界 |
| `native-sanitizer-13-final.json` | ASan+UBSan编译/运行退出0；20000次原生探测及20槽保存/引用/参数前缀闭环 |
| `cp-ui-access-406-13-final.json` | 736841帧、147归档成员、71目标及同包库/资源重新核对；原24 AP分支、1218刷新查询、864快照消费与资源加载保持；新增CP执行与12基底联验通过 |
| `build-13-verified/commands.json` | 从最终源码独立构建，ELF与已审计适配器逐字节相同；66996字节，SHA `ffaddb4c…3cde7b2` |
| `verification-continuation-13.json` | 源码/测试/文档、回执、产物、输入摘要、代码状态复用和链接检查 |

最初直接链接整个`af_slots.o`时缺少未使用函数的ARM内存ABI，已改为函数/数据分段和垃圾回收链接，只保留适配及校验代码。没有加入宿主或伪造RTOS ABI。最终重构建、回归、消毒器与同包联验均通过。探索用旧回执保留，正式结果不冒充首次即成功。

## 复算入口

仓库根目录运行；选新目录和回执路径，避免覆盖已有结果。仅构建本地研究ELF，不改DAT或相机。

```sh
af_build_dir=.local/fixed-custom-filters/cp-next-build
mkdir "$af_build_dir"
for af_source in af_cp406 af_slots
do
  clang --target=armv7a-none-eabi -mthumb -std=c11 -O2 \
    -ffreestanding -fno-builtin -ffunction-sections -fdata-sections \
    -fno-stack-protector -Wall -Wextra -Werror \
    -c "a7r5-firmware-features/custom-filters/native/$af_source.c" \
    -o "$af_build_dir/$af_source.o"
done
/opt/homebrew/opt/lld/bin/ld.lld -Ttext=0x92000000 \
  --entry=af_cp406_overlay --undefined=af_cp406_matches --gc-sections --build-id=none \
  "$af_build_dir/af_cp406.o" "$af_build_dir/af_slots.o" \
  -o "$af_build_dir/cp-parameters.elf"

PYTHONPATH=a7r5-desktop/prepared/engine/site:a7r5-firmware-features/custom-filters \
  ./.venv/bin/python -B -m a7filters.baseline \
  /Users/wenruli/Desktop/索尼/BODYDATA.DAT --investigate \
  --cp-parameter-adapter "$af_build_dir/cp-parameters.elf" \
  --report .local/fixed-custom-filters/next-cp-audit.json

./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short
```

正式本轮同时启用`--investigate-ui`，并沿用逐字节未改的build-12 UI/AP研究ELF；完整参数及运行耗时见[audit-command-13-final.json](../../../.local/fixed-custom-filters/audit-command-13-final.json)。未重复构建未变AP模块或改QEMU清单。

## 未完成与下一条实际链路

T03/T07仍需取景/拍照流身份、同一帧所有消费者、原算法后段、真实IPC/会话及最后引用释放。新适配器不承担这些职责，不能直接塞进全局快照就视为完成接入。

LUT转换还缺各基底真实ISP模型、量化与误差测量；现有六表静态空间和ST限制不能直接扩为20槽。机内存储合法位置/容量，以及原厂菜单的完整4.06运行客体、SD浏览/预览取消/保存显示仍未闭环。解析、字节保存和纯参数适配不替代这些功能。

后续应先串起`0x23091c`颜色构造的调度与各流身份、独立记录`0x16afd14`的更新来源，再将JPEG请求等待/资源池归还接到真正帧所有者；期间继续利用本批原指令执行器，保留队列失败和共享根反例。模型、帧寿命与机内存储证据具备后，才能接入LUT拟合/菜单/实际回执。

总体状态仍为`NOT_VERIFIED`。未操作相机，未修改输入4.06，未产生可安装固件；实际设备验收仍需独立授权。
