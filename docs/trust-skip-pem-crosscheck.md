# skip-PEM（verifyKey-only）方案对照

对照对象：`Erlla/sony-a7m4-custom-firmware`（`a7m4/patching.py`、`no-fastboot-install/patches.json`）、
`YuuLuo/a7c2-camera-tools`（`macos/mac_service_readonly/build_p1_gate_200.py`）、
`Lost-week-1025/CXD90057-CST`（识别层/执行层模型）。目的是核对本仓库
`a7r5-updater-trust/src/trust_recipe.py` 的 skip-key 路径是否与公开实践一致。

## 对照表

| 项目 | 前置基线 | verifyKey 覆盖 | 版本门补丁 | PEM | 校验和 | 重建不变式 |
|---|---|---|---|---|---|---|
| 本仓库 skip-key | 库 SHA 白名单 + 官方 PEM SHA + 显式 `--source-sha` | **四个库** | 无（升级场景） | **保留官方** | 整条 `p1chksum` 精确匹配后替换 MD5 | FAT 条目/FAT 元数据/squashfs 节点与 fragment 不变；只动 4 个库 |
| Erlla `patching.unlock`（换 PEM） | `state["official"]` | **四个库** | 无 | 替换为自己的 | 替换单个 MD5（必须恰好一处） | 整棵 squashfs 重新打包后 tar 往返逐文件 + POSIX 元数据比对 |
| Erlla `no-fastboot-install` | 官方 6.02 | 一个库（`libsdfile...`） | 有（`isVersionOK` + 两处局部版本拒绝） | **保留官方** | 重建 | 写后 766 块完整回读 |
| YuuLuo A7C2 | 固定 `source_sha` + fragment 白名单 | 一个库（+ `isVersionOK`） | 有 | 不涉及 | 105 字节 `p1chksum` | fragment 长度/明文 SHA 精确匹配 |

补丁字节各方一致：`00 00 80 52 C0 03 5F D6`（`mov w0,#0; ret`，状态 0 = 成功）。
我们额外断言 `VerifySignature` 的 372 字节未被修改。

## 差异与解释

1. **覆盖范围**：我们和 Erlla 的“换 PEM”路径都打四个库；Erlla 的 no-fastboot 与 YuuLuo 只打 SD 输入路径
   对应的库。我们打四个是超集，代价是 233/258 扇区略多。
2. **版本门**：他们需要，是因为目标包**版本更低**（6.02→6.01）或要做“p1 gate”；
   我们的目标是 4.31 > 4.00 的升级，版本门天然通过。回退记录也记录了 4.36 机身接受 4.37 标签。
3. **PEM**：skip-key 路径我们保留官方 PEM，与 Erlla no-fastboot 一致；换 PEM 路径才需要自定义钥匙。
4. **重建方式**：Erlla 用 tar2sqfs 整体重打并逐文件比对元数据；我们只重压变化的 fragment，
   其余字节原样保留，并用“节点表/fragment 表/inode 表尾部不变 + 只有四个库变化”约束。两者都要求
   squashfs 元数据不变。

## 我们已用测试钉住的不变式

`tests/test_trust_variants.py::test_skip_key_only_touches_verifykey_entries`：

- 官方 PEM 与写前逐字节相同；
- 变化文件恰好是四个 `usr/lib/*updaterapi*.so` / `libupdaterapi.so`（无第五个）；
- 每个库的全部差异都落在 `verifyKey` 入口的 8 字节内，且等于 `mov w0,#0; ret`；
- 原入口字节 `fd 7b b2 a9 e0 03 01 aa` 与白名单一致（不匹配会在 `verified_library` 阶段拒绝）；
- `p1chksum` 与候选 initrd/vmlinux 自洽；
- 救援 sparse 对 1/50/100/233 个扇区的半写状态都能恢复成写前镜像。

## 残余假设（未实机验证）

1. **verifyKey 是签名总闸**：Erlla no-fastboot 用“保留官方 PEM + 修改内容”的包安装成功，支持这一点；
   但 A7R5 上未实测。
2. **版本门对 4.31 放行**：依据是 CXD 的版本三元组模型与回退记录的 4.36→4.37 实测；4.00→4.31 未实测。
3. **四个库覆盖所有输入路径**：我们比公开实现多打三个库；若还有未发现的入口，仍会拒包。
4. **写后行为**：写入只改 initrd 的四个 fragment 与 `p1chksum`，理论上不影响启动；未实机验证。

## 结论

skip-key 路径与公开的 skip-PEM 实践在补丁语义、PEM 保留、校验和重建上一致，覆盖范围是超集；
差异只在“版本门”（我们的场景不需要）和“重建方式”（我们更小改动）。代码层面已用测试固定上述不变式；
剩下的不确定性只能靠明天的只读 + 写入实测消除。

## 哈希验证层次对照

| 阶段 | 我们（skip-key） | Erlla `unlock` | Erlla `no-fastboot` | YuuLuo A7C2 | 回退记录 |
|---|---|---|---|---|---|
| 前像识别 | `--source-sha` 显式绑定 + FAT/squashfs 结构 | PEM 指纹 ∈ 官方白名单 且四库 verifyKey **函数 SHA** ∈ 白名单 | 官方 6.02 基线 + 库原/补丁 SHA | 预检报告：p1 SHA-256、FAT 几何、initrd/p1chksum 位置、BK4 校验 | 整分区 logical 备份 |
| 补丁定位 | 整库 SHA 白名单 + `verifyKey` 8 字节前像 | 函数 SHA 白名单 + 入口字节 | 固定偏移 + 原字节 | fragment/库 SHA + 原指令 | 与存档原厂镜像的差异扇区 |
| 补丁结果 | 四库补丁后 SHA 锚点（本轮新增） | 重建后 tar 往返逐文件 + POSIX 元数据 | 写后 766 块回读 | 目标明文 SHA | 写后全量 logical + raw XTS |
| 写后 | 整分区前/后 SHA + 1532 块回读 + journal + `p1chksum` | 全分区回读 | 766 块回读 | `p1chksum` + 窗口校验 | 25,100,288 B + 49,024 raw 扇区 |

要点：

1. **全部是“从当次备份动态构建”**：没有一家把候选写成固定的整分区镜像；都要求用户提供本机备份，构建时再逐字节比对。
2. **锚点粒度不同**：我们用整库 SHA，Erlla 用 `verifyKey` 函数 SHA，YuuLuo 用 fragment + 明文 + 库 SHA，Hearts-Ace 用本机 SDM2/BootROM 参考。
3. **整分区 SHA 只用于“写后回读”和“救援目标”**，不用于“前像识别”。这正是本机 `1c97db…` 能与 acf32/ba3933 不同却仍可构建的原因。
4. 我们本轮新增了四个库补丁后的 SHA-256 锚点，使“补丁应用结果”也可回归验证；它与 YuuLuo 的 `target_plain_sha256` 属于同一类保护。
