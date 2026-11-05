# 原厂／自定义Tab菜单验证

独立实验仅接受013候选固定AP／CP，以及满24槽或合法空库两个固定摘要的测试BIN。原十二槽、009～012实验和默认运行时保持。使用原沙箱、真实Qt按钮和客体原帧，不提供成像就绪通知，不接触设备。两个AP场景必须顺序运行，不能绕过原独占锁。

在本项目目录使用自己的`.venv`执行：

```sh
.venv/bin/python -m unittest discover -s experiments/native24-tabs-menu -p 'test_*.py' -v
.venv/bin/python experiments/native24-tabs-menu/run_validation.py \
  --manifest build/native24-tabs-menu-20261103-07/manifest.json \
  --log build/native24-tabs-menu-20261103-07/qt-validation-new.log
# 上一场景正常结束后，再运行空库。
.venv/bin/python experiments/native24-tabs-menu/run_validation.py \
  --manifest build/native24-tabs-menu-empty-20261103-04/manifest.json \
  --log build/native24-tabs-menu-empty-20261103-04/qt-validation-new.log
```

驱动通过`QTest.mouseClick`操作真实按钮，沿原厂路线进入创意外观。满库场景核对九次Tab／进入列表操作未增加CP消息和命令序号，未改变已选编号和选择文件；遍历本模式全部原厂可见项（含FL2／FL3），再遍历24槽，检查中键返回、右键调参、八项逐项编辑、重入保留和原C4重置确认。空库场景检查空提示、下／中键停留及返回原厂组，不能选择不存在的槽。两个场景均执行四轮MENU往返及STOP。

清单schema为`native24-tabs-menu/1`，只读2444字节；构建收据须同时有稳定性、后台恢复、八项调参和Tab修订1。AP固定为`d76eea4e83db227ae7ebdf05b02834719aed1854e14c402907f3906acd4f5ffb`，CP为`35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300`。两个BIN摘要分别为`5287043ca32c315705ac99c67e8dfd7c5cbd3dea920e5c64505a81edc3f7fd46`、`17408d7d5518c5ddc465a645f350a9b59eaa9b043bcd43a9ea7855e624d91a84`；文件长度按已固定输入核对，合法空库为128字节。

新增观察只读取生产Tab getter及原manager当前页。当前页先核对vtable为`base+0x58d2fb8`，再读`+0x3b8`；旧apply追踪只用于前21步路线对比，不能替代pop后当前页。未知身份立即失败，不写客体状态、工作值或像素。每个通过场景保存完整实际驱动、验证源码、工作进程与AP／CP退出回执，并逐帧核对原始BIN与PNG。

QEMU原E4初始化缺口仍保留。工作值和菜单成功不能证明原E4完成、机内保存或真实LCD／EVF／JPEG成像；持久化、事务和原CP消费由带明确边界的CPU回放另行验证。新增13～24号仅为容量测试配方，不能当作新增成品滤镜。

失败现场与修正原因见[013复盘](../../../a7r5-firmware-features/specs/013-creative-look-tabs/retrospective.md)，最终运行与归档身份见[013验证记录](../../../a7r5-firmware-features/specs/013-creative-look-tabs/verification.md)。旧版本运行不计入本候选通过证据。
