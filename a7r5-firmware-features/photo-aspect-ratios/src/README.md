# A7R5 十档纵横比历史研究记录（修订 2）

本文件保留修订 2 及更早的地址、QEMU 和回归记录，用于溯源。当前修订 3 的菜单取消、持久化、RAW／HEIF 局部裁切、元数据及分区布局以 [实施与复验](../实施与复验.md) 为准；下文旧的 CP HEIF 共享区修改和定长 MPR 方案已被替换。

目标是保留原厂 3:2、4:3、16:9、1:1，再加 17:6、65:24、5:4、7:6、1.91:1 和 2.35:1。新增比例使用同一份整数表计算取景和裁切。1.91:1 用 191:100，2.35:1 用 47:20。

已接入 AP 原厂纵横比菜单、消息发送和照片取景遮罩，补齐横竖两套文字及图标资源。CP 逐张照片锁存和 AVCAM JPEG／HEIF 请求适配使用独立研究组件。编码回放已运行到原生消费者的尺寸和有效区域输入。本目录产物用于离线验证，默认固件构建入口保持原配置。

## 已实现与验证

| 环节 | A7R5 落点与离线验证 |
| --- | --- |
| 比例与几何 | `geometry.c` 用十档整数比例计算居中矩形，竖向取景对调分子分母。编码请求按参考对齐规则检查画布范围，仅改有效区域。对 9504×6336 夹具，1.91:1 和 2.35:1 分别得到 9504×4976 和 9504×4048。 |
| AP 菜单 | 描述符 `0x586b990` 保留原四行并注册六个私有选项。私有行号 `0x1600..0x1605` 与创意外观附加行分开。原厂比例属性仍在 0–3。原厂列表的确认调用 `0x21e1cd4` 对新增行发布私有编号并调用原厂 3:2 提交入口。 |
| 资源 | 68 个横竖语言资源追加相同的六个数字标签，两个图标银行各补齐六个 76×40 菜单图标和十二个 70×60 图标。原有图标载荷和文本逐字节保留。新增 F0 压缩流用独立解码器检查 4 KiB 分块。 |
| AP 消息 | `0x3565f78` 冻结单次 `0x402d` 消息的私有选择，`0x3566a44` 改写已核对的字节。原厂四档的 wire 分别为 2、1、0、3。私有 4–9 用 0xe0–0xe5 发送，CP 将原生消费者所见值归一为 3:2。两种装载基址下执行了原厂转换指令和新增跳板，底层发送用夹具。 |
| AP 取景 | 两套原生照片拍摄页分别在 `0x1d9ba18`／`0x1e179e0` 创建控件，在 `0x1d1574c`／`0x1d15664` 处理方向重建。根据固定描述表和原厂构造成本检查全部控件容量。使用控件实例、生命周期代次和选择代次拒绝过期几何。只在新增照片比例下覆盖原厂 guide 参数，绘制仍使用原厂坐标转换和图元输出。 |
| CP 生命周期 | `0x33f322` 接收比例，`0xadf128` 锁存已确认的静态拍摄快照，`0xadd846` 按请求编号写入任务旁表，`0xaddd5a` 复制拍摄任务时继承或清除比例，`0xae08da` 归还任务前清理。 |
| CP JPEG | `0x473562`、`0x472a0e` 改主图和场景图请求副本，`0x46e07e` 调整缩略图请求且维持 160×120 画布。尺寸通知位于 `0xae77d8` 和 `0xae7822`。JPEG 分支要求主图有效区域可裁，RAW-only 委派原处理。 |
| CP HEIF | `0xae78ae` 复制原生 `0x25c` 字节后处理三组有效区域。主图、场景图和缩略图均合法后才改消息，同时只更新 HEIF 槽的尺寸。两种 RAW＋HEIF 槽序、损坏区域和 AVCAM 原生接收均有回放。 |
| AVCAM | JPEG 两次格式构造调用 `0x1f40ec`／`0x1f4110` 按槽吸收消息尺寸，原双槽和单槽 setter 的入口不变。HEIF `0x2066b4` 和 `0x20684c` 接收已裁切的区域并调整场景图和缩略图输入，原生比例、无 HEIF 标志和非法主图回到原有分支。保留 LIRO 头和镜像长度。 |
| 拍后回放 | AP `0x2dbf3b0` 识别 18 组 A7R5 自定义成片宽高，其他输入交回原匹配函数。libmpr 在 `libjpeg::get` 的 `0x270ddc` 出口为同一尺寸表补齐读侧布局，文件长度、实际宽高、原生已识别比例和 RAW 读取路径保留。 |

CP 新 RX 位于 `0x118000`，启动继续调用原 mapper，并单独清零矩阵尾部后的 512 字节任务状态。回放检查了实际启动代码、RX 页表权限、状态初始化和组件逆还原。AVCAM 使用首个代码页中的 `0xa80` 空白区，静态核对原厂第零页引用集中在 `0x9f0..0xa08`。AVCAM 的完整启动、硬件编码与回放解码仍需后续验证。

## 离线复现

从仓库根目录执行。构建入口校验完整输入摘要。默认测试可使用本机已提取的研究输入。换机器时通过环境变量指定相同摘要的组件和资源。

```sh
feature=a7r5-firmware-features/photo-aspect-ratios/src
export A7R5_ASPECT_AP_INPUT=/path/to/native24/appFw.so
export A7R5_ASPECT_CP_INPUT=/path/to/native24/cpapp-b.bin
export A7R5_ASPECT_STOCK_AVCAM=/path/to/stock/AV-CAM.BIN
export A7R5_ASPECT_STOCK_USR=/path/to/nflasha15
export A7R5_ASPECT_NATIVE24_IMAGES=/path/to/native24
out="$(mktemp -d)"
.venv/bin/python -B "$feature/build_ap.py" --ap "$A7R5_ASPECT_AP_INPUT" --output "$out/ap"
.venv/bin/python -B "$feature/build_cp.py" --cp "$A7R5_ASPECT_CP_INPUT" --output "$out/cp"
.venv/bin/python -B "$feature/build_avcam.py" --avcam "$A7R5_ASPECT_STOCK_AVCAM" --output "$out/avcam"
.venv/bin/python -B "$feature/build_resources.py" --usr "$A7R5_ASPECT_STOCK_USR" --native24 "$A7R5_ASPECT_NATIVE24_IMAGES" --output "$out/resources"
.venv/bin/python -B -m pytest -q -p no:cacheprovider "$feature"
```

## 离线验证与成片边界

普通整合 AP／CP 和另一份已知整合 AP 加镜头 AF 的 CP 组合各通过 19 项回放及资源测试。新增取景回放执行原厂指令至图元坐标写入，覆盖两套拍摄页的容量边界、方向重建、退出新增比例及录像。对于 600×400 的取景矩形，2.35:1 横向两条遮罩各高 72 像素，旋转后各宽 72 像素。

隔离 QEMU 使用 `A7R5_ASPECT_MENU_WIRE=1` 验证实际 AP 发送的比例请求格式。逐一确认六个新增档位，重新打开菜单后均保留刚选中的档位，再切回原厂 1:1 和 16:9。此前的菜单确认断言来自虚拟服务只接受固定 3:2 请求形态。现在按固定包长、标识和后缀校验菜单形态，并沿用虚拟服务回执。

拍摄页的 AP 界面帧已对照 3:2、1.91:1 和 2.35:1。在 640×480 的输出中，1.91:1 的两条横边分别位于第 46–47 行和第 380–381 行，2.35:1 分别位于第 78–79 行和第 348–349 行，3:2 帧没有这组横边。QEMU 随后启动取景流时仍遇到未注册的成像消息队列。物理 LCD／EVF、JPEG／HEIF 实际文件和 RAW 完整幅面仍待实机验收。AP 私有比例现阶段保存在进程内，重启持久化尚未接入。

[A7M4 裁切实现参考](https://github.com/Erlla/sony-a7m4-custom-firmware/blob/main/methods/07-custom-aspect-ratios/IMPLEMENTATION.md)

## 修订 2 的回归

- 原生复制入口使用源和目标的任务偏移 `+0x20`，先执行原 `0x1ec` 字节复制，再按拍摄任务池定位旁表。修复前，复制 2.35:1 源任务后目标仍按旧 1.91:1 裁切。修复后为 9504×4048，普通 3:2 来源也会清除旧记录。 [A7M4 复制修复](https://github.com/Erlla/sony-a7m4-custom-firmware/commit/7375c9d8a66d5e33252638fe87bb2ec17038f180) · [A7R5 复制回归](test_cp.py)
- 回放尺寸表来自 A7R5 的 L／M／S 3:2 原生尺寸和六档编码结果。AP 回放保留九个栈入参和原厂回退，JPEG 出口回放检查实际宽高和原生返回值。libmpr 补丁仅占用固定原厂 RX 末端与 RW 之间经校验的空白，组合构建独立回读该文件。此验证覆盖尺寸匹配和元数据出口，尚未执行机身回放解码、放大和平移。 [A7R5 原生尺寸](https://helpguide.sony.net/ilc/2230/v1/en/contents/TP0003057051.html) · [A7M4 回放修复](https://github.com/Erlla/sony-a7m4-custom-firmware/commit/6e90ef7635673414fc0f8a762fc82e8280f28fda) · [A7R5 回放回归](test_playback.py)
