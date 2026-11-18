# 自然启动与菜单软件验证

读取规格`integration-50-boot-menu-qemu.md`。只用于离线QEMU，不连接相机；不新增CP／ISP硬件模型。

`build.py`在全新`.local/fixed-custom-filters/`目录生成隔离CPIO和DTB，包含同源4.09派生AP、真实启动库和固定资源；原始CPIO、默认模拟器清单及历史客体不改。

```sh
.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/boot-menu406/build.py --loader .local/fixed-custom-filters/boot-menu50-loader --software-peer --output .local/fixed-custom-filters/boot-menu50-next
a7r5-qemu/.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/boot-menu406/run.py --manifest .local/fixed-custom-filters/boot-menu50-next/manifest.json --interactive
```

必须保持TTY。逐行发送`{"action":"DOWN"}`等固定请求，以`{"action":"STOP"}`正常结束并保存QMP退出回执。支持UP、DOWN、LEFT、RIGHT、ENTER、MENU、MODE_M、SNAPSHOT、STATE和STORE_EXPORT，不提供任意客体命令输入。后两者只读；STORE_EXPORT须启用软件存储，会严格验证实际记录的CRC／载荷SHA并导出原字节。

不带`--software-peer`为缺对端对照。带该选项新增明确的软件协议服务，校验HELLO、参数消息及配方分帧的CRC／SHA／身份，并经过原AP接收入口；ACK只表示软件校验提交，不是图像消费。没有直接更改就绪标志或应用图像滤镜，也没有CP／ISP模型。

`--software-storage --chinese`用于中文导入与保存工作流：恢复同包原厂字体、调用原厂语言接口；在隔离客体RAM块设备上挂载真实16MiB VFAT，使未修改的生产存储检查和读写／回读代码实际执行。SD端口使用明确的目录提供者，承接真实扫描和稳定读入；该端口仅编入生成的实验启动库，产品Fsys端口未被替换。清单分别记录产品库与实验库摘要，实验库不能部署相机。两个软件SD库带有中文CUBE／AFD1夹具，不预置槽位或成功回执。

`--restore-records <STORE_EXPORT目录>`会先验证全部导出文件，再把原字节复制到全新客体的VFAT；由自然启动的生产仓库恢复目录，不设置内存快照。它验证独立软件启动恢复，不代表真实断电或SD硬件验收。每次构建使用新的输出目录，保留失败现场。

`--prepared-record <导出的Cxx_A/B.rec>`核对实际完整记录的CRC／载荷SHA与converter2/3，再把其AFD1原字节作为“04_完整配方.a7filter”放入软件SD库；用于完整配方导入路径的补测，不宣称该夹具来自电脑优化器或已完成照片标定。

第51批`audit_storage.py`审核中文双入口、八项保存／另存／取消和独立恢复；`audit_prepared.py`追加核对完整AFD1/AJR2原字节导入。它们分别创建固定新回执目录，不覆盖已经冻结的审核结果。

`audit.py`审核第50批已冻结的具体运行，不是任意路径放行器；后续软件对端扩展后不能用它的旧源码相等断言代替本批验证。产物与原始帧SHA、PNG重生成、真实启动状态、无对端拒绝、原协议软件应答和正常退出分别核对；结果不等于相机可刷写或完整成像验收。
