# 电子快门声音

本目录包含原厂声音配方及双组自定义声音。机械快门与电子快门分别保存所选声音、关闭状态和音量；电子前帘与机械共用。普通配置保留原厂声音配方；[4.19 全功能预设](../presets/full-4.19.json)显式选择 `custom-dual-full` 变体，将双组服务与 FL2／FL3、C1–C6、24 槽及十档画幅一起构建。

## 自定义声音的电脑工具

在本目录运行以下命令。输入使用整数 PCM WAV，最长 2 秒，最多 1 MiB。转换使用本机 C 编译器，生成单声道 24 kHz、十档音量的 R5S。`inspect` 只需要 Python 标准库。

```sh
python3 host/prepare_sound.py convert "输入.WAV" -o "快门.R5S"
python3 host/prepare_sound.py inspect "快门.R5S"
```

`runtime/` 收录 R5S 读取、音频目录、双组设置及异步调度源码。`bindings.py`、`profiles.py` 接入原厂 4.00；`unified.py` 处理创意外观注册和重定位；`full.py` 隔离全功能组合的声音页及启动助手。4.19 候选已封包并独立解包验签；原生菜单和 CP 指令离线回放、QEMU 软件验证与真实出声分别记录，不将模拟音频服务视为硬件验收。

[接入步骤、复现命令和剩余边界](接入与复现.md) · [两套上游对照和接入设计](自定义声音整合方案.md) · [固定上游及文件摘要](upstream.json)

已补充 [QEMU 菜单、中文与无卡恢复验证](QEMU验证.md)：三个成功会话共 137 次 Qt 操作、137 帧原始数据／PNG 一致。声音的真实输出仍未验证。

## 原厂声音构建模式

基于 ILCE-7RM5 原厂 4.00，根据拍摄类型与抑制状态决定是否选用原厂电子快门声音。三段定长修改包含调用入口、包装器与其代码映射长度。

在构建配置的 `modules` 中加入 `photo-electronic-shutter-sound`。构建器核对完整 CP、各修改前像以及 FAT 回读。单选用 4.06 包头复现历史单项包。已有指令回放覆盖抑制条件及原调用状态，实际出声按拍摄模式在机身上验收。

[模块清单](module.json) · [历史实施细节](04_电子快门声音启用实施细节.md) · [构建与离线复验命令](../构建工程实施手册.md) · [历史单项](../independent/profiles/electronic-shutter/README.md)
