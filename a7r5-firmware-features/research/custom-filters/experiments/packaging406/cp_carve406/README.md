# 修改版4.06 CP：固定保留布局

此分支只做交叉链接、主机侧验证和可逆内存补丁，不写出完整CP或DAT，不安装、不操作相机，也不执行ARM指令。

当前`--native-integration`使用独立的`capture-color-22-v1`布局：RX十页`2AEA000..2AF4000`，RW/XN十二页`2AF4000..2B00000`，冷源`11C8000..11D2000`，原SOLID大小显式减为`29C2000`。该选择是Capture完整配方缓存接入后的固定容量，不是任意页数接口；原栈、L1/L2、RW起点、六资产及声音保持。其余四页基线和`--native-capacity`二十页分支继续兼容，下面的四／二十页说明仅适用于对应分支。

当前实际冻结模块为RX38344/40960B、静态RW48744/49152B，另一次申请Capture普通堆63072B（54880B旧记录＋8192B配方缓存）。18个共用`719EF6`调用点按13个BL和5个B.W保留原控制流，旧`48E842`保持；50挂点、七段物理486B加2B零pad与原factor组成1176B只读合同。完整构建与67窗口纯内存精确正逆见`.local/implementation46-final-native-v4/`；这是源码／链接与离线内存证据，不是可安装固件或像素验收。AJR2/AJR3及Gamma格式未扩大。

固定源为CP SHA256 `18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97`。原SOLID区域大小字`0xe7d168`从`0x29d8000`减为`0x29d4000`，显式扣出尾部四页：`0x2afc000..0x2aff000`为RX，`0x2aff000..0x2b00000`为RW/XN。原STACK从`0x2b00000`开始，原BSS、L1、L2和模式栈不移动。旧BSS尾仅保留292字节至`0x1a3ac64`，phase仍为`0x1a3ac60`。

新增独立`--native-capacity`（Python参数`native_capacity=True`）严格选择固定二十页分支：RX八页`0x2aec000..0x2af4000`、RW/XN十二页`0x2af4000..0x2b00000`，SOLID大小减为`0x29c4000`，冷源为`0x11ca000..0x11d2000`。只允许四页和二十页这两种布局，不提供任意地址或页数。二十页模块的RW PT_LOAD实际保留并初始化全部49152B，`rw_statics_bytes`另记真实静态对象用量；预留空间不表示native consumer已经接线。

四页基线编译显式使用`AF_JOINT_ASSET_LEGACY_ONLY406=1`，回执`native_asset_schema=1`；该decoder只接受AJR1，排除16区能力及额外字段/传输分支，以保持原容量。二十页分支不加该宏，回执schema=3，支持兼容AJR1的AJR2原生tone/seed及显式AJR3的16区矩阵。内存计划同时核固定布局、schema和真实asset编译命令flag，不能仅改回执声称支持新格式。旧载荷仍1943B／28帧，新载荷2483B／35帧且需独立SECTOR_MATRIX协商；不改变成像／安装准入仍未通过的状态。

默认冷源仅借原必清BSS中的`0x11cf000..0x11d2000`，扩容分支使用同一原必清范围内的`0x11ca000..0x11d2000`，均与原候选源及旧六槽源分离。prepare在原`0x5e3ed8`，复制早于原清零；TTBR0须精确为`0x1a3c000`、TTBCR须精确为零、SCTLR.M须开启，identity section须精确为`0x02a10c12`。未知条件一律phase0。phase1只表示复制和RW初始化，不允许执行新代码；原extraMap用type2真正建立VA→PA：RX flags15、RW flags12。cache阶段再次核MMU、原32KiB池内coarse低位、所选布局的全部页PA及RX/RW-XN、完整目标CRC，随后Icache维护，最后才能phase2。未消费descriptor或坏源均不会开放执行。type1只改已有映射属性，不能代替物理映射。

必须同时扣减SOLID大小和建立custom映射。若仅映射原SOLID尾，原倒序空尾扫描会立即碰到已映射页，使空尾变为零。扣减后原扫描依据新base+size，四页分支保留正的`0x59c000`原空尾，二十页分支保留`0x58c000`。

`build.py --output <全新目录>`构建完整CP配方桥、传输、AJR1解析、SHA及纯参数入口，保持`AF_RECIPE_BRIDGE406`，仅本分支定义`AF_CP_CARVE_BRANCH406`。gates位于原408B RX尾前部，快照入口由实际ELF symbol传给模块，最终再次比对；不使用固定旧快照地址。默认模块须RX≤12288、RW≤4096；`--native-capacity`须RX≤32768、RW驻留49152。两者原尾≤408，无未解析符号和运行期重定位。

实际目标准入由`guard.inc`的Thumb代码实现，与gates共享literal，两个布局都不超过408B；`guard.c`保留相同顺序的主机控制参考，二者明确区分。root helper成功时r2为精确原L1根，prepare/cache直接读取`[r2+A8]`。逐页循环先校验全部RX，再由expected PTE的bit0切换至全部RW；RX低位为0、RW低位为1，只有完成RW计数才到完整CRC，不从实际输入PTE推断区间。首PTE偏移四页为3EF、二十页为3AF，均在原同一coarse表内结束。验证逐一破坏每页权限低位和PA、包括最后一页RW，并独立静态核实际指令/回边，没有执行ARM。start覆盖原PUSH/ADD共4B，HS用B.W+NOP覆盖完整MOVS/BLX共6B。HS旧r0在原分流及私有返回路径均先被重写，因此该入口的phase检查可使用r0；r1不改动。

默认snapshot仍只覆盖`89856C`完整MOVW4B，保留原MOVT。可选`--capture-input`仅为本分支加入`af_cp_input406.c`和`AF_CP_CAPTURE_INPUT406`：挂点改为`898568`原BLX4B，保留原MOVW/MOVT及其余118B窗口。tail以r3查phase，r0/r1/r2原copy三参不变；phase0调用一次原memcpy后续`89856D`，phase2进入`af_cp_override406_snapshot_copy_gate`，同锁先busy、原copy、覆盖九值、最后发布副本版本，再回原MOVW/MOVT及原解锁。构建和内存计划显式记录真实`snapshot_patchsite`，拒绝跨模式元数据混用。

`--capture-input`仅接DBC snapshot版本伴随。新增独立`--capture-copies`会隐含它，并将四个原BLX用4B Thumb BL改到同一永久尾：`898568/4BAAB6/4BBA78/4BC002`。真实LR分别为`89856D/4BAABB/4BBA7D/4BC007`；phase0直接尾调原ARM memcpy，保留原LR和三参，CRC失败或暖启动回退不需动态修补。phase2进入`af_cp_copy406_gate`，push24后按原LR分派；primary读原SP+B0（当前SP+C8），secondary读原SP+14（当前SP+2C），未知LR走不猜VD的原复制回退。原调用帧证据位于`.local/input406-hook-sites/vd_cfg.json`。

两种capture模式均显式保留`af_cp_override406_read_input`只读资格ABI；原始state getter没有使用者时允许GC。该ABI存在不表示已有原生成像消费者。各模式metadata明确实际patchsite、copy_sites、core symbol及固定capacity_layout，内存计划逐条独立解码BL并核四个返回上下文。两种布局均用同一原408B尾准入；权限和CRC条件没有因容量增加而放宽。

这些仍是离线源码、链接和内存补丁方案，未向相机安装。source→bank及实际消费者资格、CPU输入副本退休仍需分别接通。DBC不含DC0头，不能从snapshot三个copy参数虚构native VD；三条E70使用已核原调用帧中的VD。

`memory_plan.create_plan(cp_bytes, build_dir)`严格核对固定源、实际编译输入、ELF、载荷、原挂钩和旧六槽保护区，仅返回补丁记录。`transform(cp_bytes, plan, reverse=False)`只返回内存副本；逆变换必须恢复完整原摘要。没有写出完整镜像的API。

验证命令：

```sh
.venv/bin/python -m pytest -q a7r5-firmware-features/custom-filters/tests/test_cp_carve406.py a7r5-firmware-features/custom-filters/tests/test_cp_recipe406.py
```

这条路线解决的是装载空间和桥接代码的离线落点。没有绑定真实原生消费者时仍拒绝FULL_RECIPE协商；沿已确认REQ-008保留原厂分组发布和失败回退，不新增整配方发布门禁，也不以容量通过宣称取景/JPG成像已经完成。原mapper、区域表和启动证据位于`.local/implementation38-placement/`。
