# 当前修改4.06的原四核初始化窄探针

本入口服务于T03g。它只执行当前`18b265…` CP的必要原代码/ROM页，不提供机身后端、完整boot、AP peer、ISP或可安装产物。输入DAT只读，完整CP仅驻留审计进程；默认输出17段同源页共163840字节。相机、USB、真实SD与默认runtime均不参与。

## 重现四核、MMU/GIC及服务自然拒绝

先使用已有离线源码构建独立CP板，不修改默认模拟器。使用QEMU项目原有环境以复用其本地构建依赖，不安装系统包：

```sh
a7r5-qemu/.venv/bin/python -B a7r5-qemu/tools/build-cp-qemu.py
```

将输出的`cp-qemu-*`目录代入。以下命令必须使用新的输出目录：

```sh
PYTHONPATH=a7r5-firmware-features/custom-filters:a7r5-desktop/prepared/engine/site \
  ./.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/cp-init406/verify.py \
  --input /Users/wenruli/Desktop/索尼/BODYDATA.DAT \
  --qemu-build /绝对路径/cp-qemu-独立构建 \
  --output .local/fixed-custom-filters/cp-init406-new-run
```

CPU身份来自四个实际A35模型核的MPIDR，不使用MRC hook或修改屏障计数。研究调用器按原`5f0a50`消费的同ROM表设置SVC栈，分别调用原主核`5e7ad4`和原从核`5eb3b8`；主核继续原堆、属性、缓存、GIC顺序。GIC为已有标准QEMU GICv2模型，寄存器结果只对该模型成立。

服务查询采用先前原分配链已观测的`53cd40(0x2a,0x2a4,输出位置)` ABI。原`5e3b58`、`5c0104`建立静态上下文和事件标志；调用器按原主启动`5e3fd4`的条件启用IRQ。这是明确的研究CPU入口准备，未改CP字段、锁或服务返回。默认模式不运行OSAL构造，池空时应由原路径返回`0xfffffc01`、句柄0，目录锁正常释放；这表示真实拒绝，不是分配成功。

独占全局VM锁，只访问本次Unix QMP。无网卡、串口、磁盘或设备透传；所有路径在`finally`退出自有QEMU并释放锁。与GUI长客体必须串行。

## 源代码漏页拒绝

增加`--negative-omit-pool-page`可重现固定漏`53b`页的负例。正确结果是`PASS_EXPECTED_SOURCE_REJECTION`，其源审计结果仍为`INCOMPLETE_SOURCE`、首个未知入口`0x53b50c`。它不能用于解释缺源之后的锁、寄存器或返回值。

审计逐字节核对全局每个已翻译TB，包括跨页字节；每条输出的`exec`引用须关联到已批准TB。四核身份另外从原MRC观察器核对。TCG链式TB复用不一定逐次输出`exec`，因此本工具不声称记录了每核每一次动态TB事件。任何未知页、数据页执行、原字节变化、缺失翻译或预算结束均不能成为服务闭环PASS。

观察器阶段值互不冲突：1进入、2原MMU返回、18原堆返回、3属性、4缓存、5GIC、6服务查询返回；异常为`0x80+向量号`。仅最后PC或单一阶段值不能替代源审核及返回内容检查。

## 原队列、任务记录及OSAL构造后的查询

在四核命令中增加`--original-osal-init`。该模式使用`probe-osal.S`，输出36段必要源页共262144字节，不导出完整CP。先执行原`5e3b58`，随后按原启动调用者`5ccadc`的顺序执行`5cc05c`、`5bea00`、`5c6c38`和`5bf160`，由原指令建立主核队列及任务记录。完整原`53a52c`再建立池及180类资源，之后执行相同查询。未调用原调度切换，不把该窄调用称为完整boot。

实际查询返回0、产生资源句柄`0x92a4601f`；该句柄不能作为地址解引用，也不是`output_context+0x6b0`网格指针。池布局、原目录锁释放、四核身份、返回及完整翻译块字节一同核验。此模式的成功标签是`PASS_ORIGINAL_POOL_QUERY_CALLBACK_REJECTED`，其中的拒绝必须保留：构造函数最后`53a6c8→521f6c→5d6764→5d69f0`尝试登记回调，原`5c9034`识别当前初始化上下文为1，原检查返回`-1`，回调表保持源初值。不能把“函数完整返回”写成“OSAL完整初始化成功”。

该长构造只记录全局`in_asm`完整翻译块，四核MPIDR由观察器另行证明；不要求逐次`exec`日志。审核器仍拒绝未知代码页、跨页漏源及任何原字节不符。阶段32表示进入构造、33表示原函数返回；原构造尾返回单独存入观察器偏移40。

## 原四核RTOS调度前缀

增加`--original-rtos-init`，使用`probe-rtos.S`及`rtos_layout.py`列出的必要页。原`5e3fd4/5e3fe0`顺序启用IRQ并调用`5ea8ac(5)`，四核阶段计数由原指令自然到达`[5,5,5,5]`；原`5ccadc`再通过`5eb35c`启动其他三核，并进入原`5cd290→5cc1e8`调度。调用器按原`5f0a70..5f0ac8`的同ROM字段准备六种bank栈；这是明确的研究CPU入口准备。

检查点要求四核均位于原`5cc248..5cc294`空闲循环、四份原上下文及idle栈一致，且完整翻译源审计通过。通过标签为`PASS_ORIGINAL_FOUR_CORE_RTOS_IDLE_GROUP0_PREFIX`；它只证明该显式前缀，不表示完整启动或输出分配。原ROM异常向量按代码和数据分段准入，数据页执行也会被审核器拒绝。

此模式尚未装载、解析TOMCO，所得组0不能视为当前包的真实配置。同源CPIO内原`cp/tomco.txt`为686字节，SHA-256为`524bb8c841f29e609e7606d56e6d393023afa8e0d3f61acbce7f957572323115`，明确包含`usrrtn_cfggrp=2`及`wdt_on=1`。真实配置的验证应使用后文原TOMCO模式，不能由主机直接写`195e9dc=2`，也不能使用关闭看门狗的旧配置变体。组2下的原任务、服务目录及成像输出尚未由此检查点证明。

## 原TOMCO解析及明确的看门狗模型边界

```sh
PYTHONPATH=a7r5-firmware-features/custom-filters:a7r5-desktop/prepared/engine/site \
  ./.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/cp-init406/verify.py \
  --input /Users/wenruli/Desktop/索尼/BODYDATA.DAT \
  --qemu-build /绝对路径/cp-qemu-独立构建 \
  --original-tomco-init --tomco-cpio /绝对路径/同源/source.cpio \
  --output .local/fixed-custom-filters/cp-tomco406-new-run
```

CPIO必须匹配`c01948220e1cced7f4e1d6a6dd28221c587050214d32cc405291cc00d2f1ed80`；程序只取原686字节TOMCO，放在原解析器要求的`100000`，不改启动组、看门狗开关或任一原回调。`probe-tomco.S`在原MMU/GIC顺序后补原主启动`5e3fa4/5e3fb4`调用的`5ec438/5ec4f4`，由原指令建立软件定时器前提，然后进入同一原`5ccadc`。

此模式加载完整原初始化数据段`[107f000,1196f5c)`、长度`117f5c`，文件偏移`f77000`，SHA-256为`8bfed4eda1ab8adef4266b58b25e7a82fea745554873379ea456d3f1979579de`。其物理源与目标由`loader.py`核对；该段不可执行，不能拿零RAM代替未载入的静态函数指针。包括必要代码/ROM、该数据段和TOMCO的输入共1540618字节，仍未导出完整CP。

实际原调用链为`5ccb2c→5d842c→5d8488→5e3740`。原扫描器从`100000`取键/值，遍历`FBE070..FBE134`回调；原`60b1c0→5f4570`转换组值，原`60b1fc`写`195e9dc=2`。扫描返回后继续原`609324`，原`5ec614`成功登记软件定时器，队列头`1676f44=10a4880`、回调`60948c`；原配置仍为`wdt_on=1`、超时设置7。

当前模型在原`609e18`执行`STR r5,[r4,#-0x5c]`，其中`r4=f13883a0`、`r5=40000`，产生`DFAR=f1388344`的DataAbort。工具保存该真实边界后正常QMP退出：`TOMCO_parse_evidence=PASS`与`execution_source_audit=PASS`分别只代表原解析和翻译源范围，整体状态为`BLOCKED_ORIGINAL_WDT_MMIO`，进程返回1。不能据此宣布USER_TSK_INIT2、银行分配或成像链路完成。

继续需要该SoC看门狗/复位/时钟寄存器的真实模型与必要状态依据。原后续还访问`f1388348`、`f1052000`和`f13883a0`；本工具不将这些地址映射成普通零RAM、不关闭看门狗、不跳初始化回调，也不将标准GIC模型的成功视作其他外设已实现。

历史独立候选`tomco-rtos-v1/v2`漏初始化数据，原回调字段被零RAM代替，不能作为固件故障证据。v2的软件定时器登记分支静态返回`-17`；先前从BUG处读取的`r0=-2`已经过日志函数，不能归因于登记返回。v3仅补一个数据页，未作为完整数据准入；v4补原完整段并复现上述MMIO边界。v4旧私有运行器继承的“未加载TOMCO/组2尚未解析”布尔不适用本次输入，最终正式模式的回执已消除此矛盾。旧文件保留，不能用历史元数据覆盖实际源字节与原执行范围。

## 独立复算池生产前缀

```sh
PYTHONPATH=a7r5-firmware-features/custom-filters:a7r5-desktop/prepared/engine/site \
  ./.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/cp-init406/verify.py \
  --input /Users/wenruli/Desktop/索尼/BODYDATA.DAT \
  --output .local/fixed-custom-filters/cp-pool406-new-run --pool-prefix-only
```

此模式不启动VM，在独立Unicorn中执行原`53a52c..53a606`前缀。构造输入来自原无参函数的固定地址及`c2bfc0`的180项尺寸表，原`baa3d4`产生10999个64字节节点，池地址`1bf4240`、大小`abdc0`。程序独立复算尺寸、遍历全部链表，限制写入区域及总写数。该实例不与四核客体共享状态，不能据此宣称后者的池已初始化。

原配置表中该函数名为`OSAL_UIPC_INIT`，记录`e7a984`的函数指针为`53a52d`、组掩码`fffffffe`、核掩码1。组0不选择它；本工具没有伪造真实启动组，也未据显式调用宣称完整boot。完整构造已在四核模式实际执行，但最后回调登记仍拒绝；真实服务提供者状态、`230c10`输出发布及最后图像消费者仍待继续接入。

`loader.py`另执行原header复制与数据参数窗口：源字段`f57000`相对原影像基址`128000`，实际源物理地址和目标VA均为`107f000`。因此所需`.data`页使用当前flat驻留内容；不按错误的独立VA再覆盖。该参数证明与完整启动分别记录。
