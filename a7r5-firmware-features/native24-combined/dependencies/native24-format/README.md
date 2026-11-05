# 二十四槽容量与文件兼容原型

本目录现为 4.17 的格式派生与测试依赖。以下保留原型阶段的范围和独立复现方法，现行整合版见 [4.17 实施与复现手册](../../实施与复现手册.md)。

本目录验证的是“是否具备继续扩容的基础”，不提供二十四槽固件或升级包。现有十二槽AP／CP、旧BIN、两个DAT及冻结上游保持不变；未连接相机。

2026-11-03本阶段15项离线测试通过：独立布局原型在宿主、ARM32、AArch64得到一致的947000字节；旧十二槽配方完整解码并原样重编码；新完整／稀疏槽、候选选择文件和损坏拒绝通过。实测结果和证据见[验证记录](verification/2026-11-03-01/README.md)，范围见[008规格](../../../specs/008-native24-feasibility/requirements.md)。

**布局947000字节不是实机可用性证明。** 在显式1 MiB测试预算下单库剩101576字节，第二份完整库放不下；真实共享堆余量未知。原型没有接原CP颜色消费者、AP／CP传输或原创意外观菜单，也没有验证43行UI、原E4和整机启动。

复现仅使用仓库根目录现有`.venv`和本机clang，无新依赖。输出路径必须是不存在的新目录：

```sh
.venv/bin/python a7r5-firmware-features/native24-combined/dependencies/native24-format/prepare.py \
  --output .local/native24-feasibility-new

A7R5_NATIVE24_PROTOTYPE_BUILD="$PWD/.local/native24-feasibility-new" \
A7R5_NATIVE24_EVIDENCE="$PWD/.local/native24-feasibility-new/evidence" \
.venv/bin/python -m pytest -q \
  a7r5-firmware-features/native24-combined/dependencies/native24-format/tests/test_prototype.py \
  --junitxml=.local/native24-feasibility-new/results.xml
```

测试构造的13～24号仅复制原合法参数并使用“测试槽”名称，不代表新增十二款配方。候选v5文件和`R5SEL5`仅用于此独立原型，尚未成为正式接口；**不要将`fixtures/*.test.BIN`放入相机使用，也不要把它们当作当前4.11可导入的文件**。
