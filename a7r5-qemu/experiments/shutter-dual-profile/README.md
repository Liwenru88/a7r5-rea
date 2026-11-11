# 双组快门声音 QEMU 验证

执行固定候选 AP／CP，使用真实原厂菜单与 Qt 按键。虚拟 SD 接口提供两份测试 WAV 转换的中文 R5S，导入、校验、目录发布、两组选择／音量和文件保存均运行候选代码。音频后端使用明确替身，只校验载荷和安装事务；没有模拟音频硬件或证明真实出声。

输入 AP `63072c53ff5d9ed4b32f01175667e057f85c1cc83c6d5067337354c6c52c6eda`，CP `0e5ba4553064b1143a7d407b14dd9b5b353c98d77bd0d87bbfc8a4e490f4f523`。当前默认清单的 initrd 缺失，本实验使用逐项校验的独立历史种子 `build/menu417-17-oLYPDW/final/manifest.json`；没有修改默认清单或绕过其校验。

## 本次结果

三个成功会话共 137 次 Qt 操作、137 张原始帧／PNG 逐像素一致，AP QMP、CP 侧车和 Qt worker 均正常退出。覆盖：

- 两份中文声音扫描、完整 R5S 校验和机内入库，四项声音菜单及名称显示。
- 上下浏览不保存，中键确认；音量修改按 MENU 取消后重入仍为原值。
- 电子组选择第二份、80%；机械组选择第一份、30%，两组互不改写。
- 从虚拟 VFAT 只读导出 96 字节 `R5SOUND.PRO`、624 字节目录和两份包，独立核对身份与 CRC。
- 全新客体挂载新的虚拟 VFAT 后，恢复导出的原始文件；不发送有卡状态，不扫描虚拟卡，恢复两组选择和音量并装入机械组载荷。
- 四轮顶层 MENU 开关；启动前拒绝未知候选和损坏输入摘要。

具体会话：`runs/native-native12-410-go239log`（交互／取消）、`runs/native-native12-410-gsd2xzli`（保存／导出）、`runs/native-native12-410-ispd_1v2`（无卡新客体恢复）。最终回执 `runs/shutter-dual-profile-verification-20261111.json`。

## 复现

在 `a7r5-qemu` 目录使用本目录 `.venv/bin/python -B`。`build_guest.py` 的 `--candidate` 指向声音模块 `--custom-sound` 的组件构建目录，不能指向原厂 DAT。输出目录和日志必须使用新的名称。

```sh
PYTHONPATH=tools .venv/bin/python -B experiments/shutter-dual-profile/build_guest.py \
  --candidate /tmp/r5sound-port-build.tC1faZ/dual-verified \
  --output build/sound-qemu-new

PYTHONPATH=tools .venv/bin/python -B experiments/shutter-dual-profile/run_validation.py \
  --manifest build/sound-qemu-new/manifest.json --log runs/sound-qemu-new.log
```

控制器输出 `RUN_DIRECTORY`；该目录内的 `exported-files.json` 是本次实际虚拟文件系统的导出。用它构建第二个客体并验证无卡恢复：

```sh
PYTHONPATH=tools .venv/bin/python -B experiments/shutter-dual-profile/build_guest.py \
  --candidate /tmp/r5sound-port-build.tC1faZ/dual-verified \
  --output build/sound-qemu-restore-new \
  --restore runs/实际保存会话/exported-files.json

PYTHONPATH=tools .venv/bin/python -B experiments/shutter-dual-profile/run_validation.py \
  --manifest build/sound-qemu-restore-new/manifest.json --log runs/sound-qemu-restore-new.log \
  --restore runs/实际保存会话/exported-files.json

PYTHONPATH=tools .venv/bin/python -B experiments/shutter-dual-profile/test_runtime.py
```

若需独立逐像素复核，使用 `verify_run.py --manual ... --saved ... --restored ... --output 新回执.json`。新建会话的 `--manual` 需要额外执行音量取消与重入，或引用本次保留的手动交互会话；控制器路线已固化在 `route.json`。

## 适配及限制

只在派生客体中替换 AP、CP、两份图标、版本测试字节和模拟库，并增加测试文件／导出助手；CPIO 比对核对实际变更与其他条目及元数据。AP／CP 文件与声音候选组件保持逐字节一致。历史种子继承的 `original_components_modified` 字段不能代替本次 `changed_entries` 与 CPIO 对照；新版构建器已明确记录客体 AP／CP 替换范围。

CP 侧车直接加载当前 CP 指令、零初始化测试 RAM，并提供 OSAL／共享堆；旧版 `0x108f8d` 初始化地址在新布局已重新分配，本次去掉了该旧固定地址调用，接收入口改取当前符号。没有启动完整 CP RTOS。

早期失败记录保留：缺少模拟库 `memcmp` 声明、旧侧车入口、声音日志未镜像到控制台、精简客体缺少 base64。均为本次测试工具／适配问题，修复后重新建立客体或会话。没有修改生产固件修复这些工具问题。

实际音频输出、扬声器音质、真实曝光到声音延迟、播放中断电和真实 SD／eMMC 行为仍待实机验证；本轮没有连接相机，也没有生成升级包。
