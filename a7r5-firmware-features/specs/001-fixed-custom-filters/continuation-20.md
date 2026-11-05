# 第二十批：四组件联合整数求解与原CP运算对照

- Feature ID: `001-fixed-custom-filters`
- Updated: `2026-10-26`
- Status: `OFFLINE_JOINT_CORE_VERIFIED_FULL_MODEL_PENDING`

## 本轮交付

将Gamma、色彩矩阵、CC1/色度和5×9×9网格的联合拟合收紧为完整转换必做项，移除“其他组件按需要加入”的降级表述。实现T08b2b/T08b2c的限定范围：原生整数组件、四组交替搜索、完整组合量化目标选优、有限资源与错误不发布，并在AArch64执行。

当前求解器依赖显式完整预测后端，本批使用合成耦合后端验证；当前CP的实际完整后端仍待T08b2d。已完成的网格模型不能描述Gamma/矩阵/CC1变化，参考Edit模型的输入域也不能直接当本机显示sRGB。原CP窗口仅证明运算/字节，不能作为完整联合颜色效果证据。因此T08b2/T08、实际菜单/机内保存/取景/JPG整体仍未完成。

## 主要改动与验证

| 文件/证据 | 结果 |
|---|---|
| `native/af_joint.h/.c` | 完整候选内存契约、18位129点Gamma、记录尾部保持、三端点矩阵6→9展开及CC1/网格边界 |
| `native/af_joint_fit.c` | 四组件共享同一量化目标、SKIP/错误分流、取消/失败不发布、重叠及模型/基底/CP身份拒绝 |
| `a7filters/native_joint.py`、`baseline.py` | `--joint-adapter`研究门控，独立AArch64执行与当前CP 5组Gamma、2组端点增量窗口联验 |
| 新测试及`native_sanitizer.c` | 四组件共同选优、原整数独立期待、模型中途出错/非有限值/单网格能力拒绝、取消保留全部输出 |
| [相关回归](../../../.local/fixed-custom-filters/pytest-20.json) | 203 passed in 7.80s，命令8.025秒、退出0且源码未变 |
| [ASan/UBSan](../../../.local/fixed-custom-filters/sanitizer-20.json) | 20000次含联合Gamma/矩阵边界探测及联合搜索/取消等核心契约；编译1.425秒、运行0.506秒、退出0 |
| [完整同包审计](../../../.local/fixed-custom-filters/cp-ui-access-406-20.json)与[命令](../../../.local/fixed-custom-filters/audit-20.json) | 151.113秒，修改4.06验签、736841帧、147成员、71目标和103资源，原24 AP分支/1218刷新/864快照保持 |
| 同报告`native_joint_core` | AArch64 1871断言、65次预算、11824字节工作区、四组件均有改进；原CP组件窗口逐字节对照及保护区保持 |

合成目标训练量化MSE从6.0233244×10⁻⁵到0，仅证明有限合成任务的求解器行为，没有真实LUT联合留出ΔE或机内效果结果。公开源/原包格式差异、约束、目标和剩余模型依赖见[联合核心与模型边界](joint-conversion-20.md)。

## 产物与复算

独立AArch64研究ELF位于`build-20-joint/joint-converter.elf`，80168字节，SHA-256 `632be037806dc689741748270a74d7d58fde55fa473f25231c7201ef293b7bc2`。基址`0x9080000`仅用于模拟器，不是装载许可。[构建回执](../../../.local/fixed-custom-filters/build-20-joint/commands.json)记录6条编译/链接命令和源码/头文件指纹。旧模块保持，不重建或覆盖。

仓库根复算，回执选择不存在的新路径，不安装依赖：

```sh
PYTHONPATH=a7r5-desktop/prepared/engine/site:a7r5-firmware-features/custom-filters \
  ./.venv/bin/python -B -m a7filters.baseline \
  /Users/wenruli/Desktop/索尼/BODYDATA.DAT --investigate-ui \
  --ui-adapter .local/fixed-custom-filters/build-12/ui-adapter.elf \
  --ap-ui-module .local/fixed-custom-filters/build-12/ap-ui-hooks.elf \
  --cp-parameter-adapter .local/fixed-custom-filters/build-13-verified/cp-parameters.elf \
  --cp-atomic-adapter .local/fixed-custom-filters/build-15-final/cp-atomic.elf \
  --ap-handshake-module .local/fixed-custom-filters/build-16-handshake-verified/ap-handshake.elf \
  --cp-handshake-module .local/fixed-custom-filters/build-16-handshake-verified/cp-handshake.elf \
  --ap-runtime-module .local/fixed-custom-filters/build-17-runtime-final/ap-runtime.elf \
  --cp-runtime-module .local/fixed-custom-filters/build-17-runtime-final/cp-runtime.elf \
  --grid-adapter .local/fixed-custom-filters/build-18-grid-verified/grid-converter.elf \
  --joint-adapter .local/fixed-custom-filters/build-20-joint/joint-converter.elf \
  --report .local/fixed-custom-filters/next-joint-audit.json

./.venv/bin/python -B -m pytest -q a7r5-firmware-features/custom-filters/tests --tb=short
```

本批当前ST原曲线位于CP文件`0xcc4a0c`；原Gamma窗口`0xbef948..0xbef9ae`、矩阵增量`0xbef762..0xbef772`、CC1增量`0xbef7c2..0xbef7d2`只在隔离执行器中运行，完整原生产器和硬件未执行。定向先行结果见[native-joint-20-initial.json](../../../.local/fixed-custom-filters/native-joint-20-initial.json)。最终源码/文档/历史产物/输入与引用见[本批指纹](../../../.local/fixed-custom-filters/verification-continuation-20.json)。

下一步先完成真实基底、处理顺序、输入域/采样轴及端点标定的完整组合预测，再做联合留出误差、原厂应用和菜单持久化。未操作相机、USB、SSH或真实SD，未读取私钥、修改输入DAT/冻结材料、生成安装固件或暂存/提交/推送。总体`NOT_VERIFIED`。
