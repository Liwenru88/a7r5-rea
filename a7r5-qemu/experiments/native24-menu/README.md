# 二十四槽独立菜单实验

保持既有沙箱、内核、原始Qt输入和无成像完成回执的模型。默认运行时和原十二槽实验不改；只接受固定24槽AP／CP、合成测试BIN和2320字节只读状态布局。

在`a7r5-qemu`目录使用本项目`.venv`：

```sh
.venv/bin/python experiments/native24-menu/build_guest.py \
  --output build/native24-menu-new \
  --runtime ../.local/native24-runtime-20261103-05

.venv/bin/python -m unittest discover -s experiments/native24-menu -p 'test_*.py' -v

.venv/bin/python -B experiments/native24-menu/qt_research.py \
  --manifest build/native24-menu-new/manifest.json
```

当前身份检查中的已构建正例绑定`build/native24-menu-20261103-02/manifest.json`；未知AP／CP和旧观察布局被拒绝。构建新候选时必须明确更新固定身份及相应测试，不能绕过校验或沙箱。

本次正常运行`runs/native-native12-410-rsdd3lr1`：真实前台设置和M档后进入ST，UP24、DOWN24、DOWN7、UP7，再退出并做四轮MENU／ST重入，最后STOP。96原帧逐像素核对，worker、AP QMP、CP退出0。完整证据见[24槽运行时验证](../../../a7r5-firmware-features/native24-combined/verification/2026-11-03-01/README.md)。

13～24号是“测试槽”合成配方。QEMU实际滤镜应用仍失败回退，原E4未获得成像就绪，不证明24款色彩成功。旧首次运行`va9lisan`在成功加载24槽后被旧29552字节检查拦截，已保留失败现场并修正为58976，不伪造状态。客体变化仅限AP、CP、两个图形资源、测试BIN及模拟观察／传输库，其他归档条目和元数据核对不变；没有实体I/O。
