# 第50批：自定义滤镜启动修复与原厂菜单软件运行

2026-11-02，T11f离线范围完成。用户明确要求离线修复、QEMU运行，不做硬件模拟。本批没有连接相机，也没有改变此前机身写入或只读恢复失败的现场。

## 结论与根因

真实AArch64启动库在QEMU中自然执行：早构造观察器取得原厂5591项登记回执；晚初始化消费成功，随后返回`AF_STALE`，尚未装UI或requests。只读观察证明132项原指令匹配，但原AP的RX长区间已被多条连续RX映射覆盖，旧`protection()`只认单条VMA。

自己的两处早／晚挂钩写入及恢复已经执行mprotect/COW；Linux可以保持分裂后的VMA，不保证重新合并。因而扩大maps数组后仍可能在这里被误拒。这是QEMU真实执行证明的产品缺陷；用户“试了仍无功能”没有提供新启动状态，本批不据此断言最新机身一定停在同一行。

修复在`experiments/packaging406/loader/af_bootstrap406.c`：逐段推进请求区间，只接受完整连续覆盖且每段权限相同；空洞、权限切换、零长／溢出和失败快照仍拒绝。保留既有容量2048、总量／排序检查、来源摘要、132原前像、正常登记和HELLO。没有强制publish、跳过握手或额外打开原厂禁用模式。

## 本地产物

`.local/fixed-custom-filters/boot-menu50-loader/libaf_bootstrap406.so`，97208字节，SHA256：

`cfec1cc78bb2f272cbd292296f2cc8bf88979e546be0033eb4038afc0b751be2`

与先前修复库相比，UI／requests／repository三模块、42窗AP、资源表及导入导出／依赖版本保持。没有生成新DAT，原4.08／4.09故障包继续停止试用。旧设备脚本冻结了95864B及旧摘要，且已有原子替换后无法恢复只读的问题；不能直接拿它部署本候选。后续机身操作仍需新前像、保留原inode及正常关机策略，不在此批进行。

## QEMU如何运行

新增`experiments/boot-menu406/{build.py,run.py,audit.py,software-peer.inc}`，输出全部位于全新`.local/fixed-custom-filters/boot-menu50-*`，不切换模拟器默认清单。

复用固定QEMU、原4.06 Linux和已验收的virt基础平台，以及既有UIPC／Backup／GPE软件服务。没有新增CP/ISP／传感器／拍摄硬件模型。QEMU宿主仍需基础虚拟CPU、时钟与Linux平台；这里的“软件运行”指执行用户态原AP，不是另做一套网页或硬编码菜单。

分三个对照：

1. 旧库：自然登记后STALE、prepared=0，132原前像无差异，长区间不存在单一覆盖VMA。
2. 修复库、无私有对端：prepared=1、56界面挂钩和3启动挂钩安装，因缺对端仍installed=0；保持原关闭策略。
3. 修复库、软件协议对端：仅接管目的ID匹配且size=128／wait=0的私有分配与自己持有的消息。原厂其他消息原样交给既有服务；真实生产`af_hs_server`校验CRC、源码身份、会话和能力，消息经原AP接收／解析挂钩，正常UI拥有者发布。没有设置preset_ready／admission字段，没有直接调用publish。

该对端只实现HELLO，不实现13个图像消费者，不是CP成像仿真。客体`/setting`为tmpfs，不符合真实vfat合同，存储绑定如实失败；不伪造设备／挂载证据，不把管理页出现等同导入保存成功。

## 已运行的结果

- 失败复现1 failed／3 passed；修复后映射与启动28 passed。
- 当前启动依赖66 passed、实际装载检查13 passed，额外既有协议检查7 passed。统一软件构建明确不编译未交付的旧AP/CP裸ELF探针；先前广范围3项缺参考资料错误未被本结果覆盖。
- QEMU原厂M模式的创意外观实际画面：FL2、FL3、前六自定义槽及新增C07～C20均可逐项导航；C20下移回ST，额外原生特殊记录未被计入32个可见外观。
- 原厂Color/Tone页出现`Custom Filters`入口，能进入Save／Copy／Load管理页；不可用动作明确显示Unavailable。没有私有文件系统绑定成功，不测试保存成功提示。
- 两次交互记录共74个按键帧；9关键PNG从原始帧重生成逐字节一致。已人工查看FL2、FL3、C07、C20、回绕ST、管理入口／管理页及M模式画面。
- 两次主运行没有异常监视器记录，以显式STOP及QMP quit正常退出0；不是仅“看见进程还在”。

关键回执：`.local/fixed-custom-filters/boot-menu50-final/verification.json`。管理主运行尾缀`native-boot-menu406-5ejlrtz7`；32槽主运行尾缀`native-boot-menu406-v508qm9v`，均在`boot-menu50-peer-v2/execution/runs/`。

运行示例（使用已有Pillow的QEMU项目环境，不新增依赖）：

```sh
a7r5-qemu/.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/boot-menu406/run.py --manifest .local/fixed-custom-filters/boot-menu50-peer-v2/manifest.json --interactive
```

交互端保持TTY，以逐行JSON发送UP／DOWN／LEFT／RIGHT／ENTER／MENU／MODE_M／SNAPSHOT／STOP。每次按键取得新序列原始帧，不执行任意用户shell。离线总审计：

```sh
a7r5-qemu/.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/boot-menu406/audit.py
```

## 保留的失败与验收边界

早期运行保留输出目录／UID解析错误；软件对端第一版过宽拦截原厂小消息导致客体异常，后续收窄后原MENU流程通过。根Python环境缺Pillow，改用项目现有QEMU环境；非TTY的控制输入EOF不作为成功，后续显式STOP的两次主运行通过。没有删除这些失败或改写原回执。

当前通过的是英文原厂菜单的软件执行与修复回归。中文显示、真实机身启动、原SD导入／持久化、完整LUT误差和实际EVF/JPG仍未在本批验收。T11f的完成不等于全部功能或T12完成；整体保持NOT_VERIFIED。
