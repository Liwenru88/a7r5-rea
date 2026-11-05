# 修改版4.06的CP启动接线

本目录实现同一CP `18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97` 的有界启动代码和仅内存补丁计划。不会写出CP镜像、DAT、签名或访问设备；交叉链接及宿主逻辑不等于实际启动。

当前配对为：新页RX3352字节／`1a3b000`，RW288字节／`1a3ab40`，独立phase4字节／`1a3ac60`；原明确回收的RX尾`bef9e8..befb80`容纳408字节引导。快照永久入口为Thumb `befb35`，CP模块须使用同一个`--snapshot-entry`，完整118字节窗口和原`0x24`互斥检查均保留。

第36批CP私有对象增加同锁version，RW增至288字节。旧phase1a3ac50会与新RW重叠，已移至实际尾1a3ac60；C与汇编共享生成常量，构建器独立核实际phase literal位于RW之后。原34批3204／272配对保留历史身份，不能混用当前源码。

## 原启动入口及所有权

只替换原`5e3ed8 MOV r0,#0`为ARM BLX，原`5e3ed4 PUSH {r4,lr}`仍执行一次。准备函数所有路径返回0，恢复被替指令语义，回到原`5e3edc`。没有重放或跳过原构造、清零、unmap、页表及栈初始化。

phase清零依赖**原完整loader入口契约**：`10850c..520`按扩展BSS声明建立RW映射；原旧六槽搬运和后续原L1切换完成后才进入`5e3ed8`。因此phase与已映射旧六槽尾数据同在`1a3a000`页。这不是对任意MMU状态调用的容错接口；不能绕过loader直接调用并宣称安全。

准备函数另核SCTLR、TTBR0、TTBCR和固定原coarse／PTE，只接纳已确认的冷RW/XN或暖RO/RX页。已有RX通过完整CRC则暖复用，否则只在可写且冷源CRC正确时复制。RW逐字重建为`feffffff`加284个零字节，与ELF初始化像独立核对；未来出现其他初始化值或布局漂移立即拒绝。

冷源为`11d2000..11d2d18`，位于原必须清零的BSS，复制在原清零之前。**原拟用`11d4000`已作废**：它落在原`108f40`保护的旧六槽FNV源内。当前计划逐字保护`11d3000..11d4900`及旧包装器前缀，旧FNV保持`8855bcca`。BSS声明只扩292字节，原页表根`1a3c000`及原栈不移动；SOLID保留域／尾回收的原窗口见本批静态证据。

原unmap保持；原extraMap回调返回明确RX descriptor，经原mapper建立最终映射。缓存入口先执行原D维护，再补原I维护，随后原TLB／屏障尾仍执行。三处永久跳板只有phase2才进入新页，否则重放原指令、返回原流程。 extraMap在phase1和phase2均保留RX映射，避免已发布状态下重入原mapper时丢弃执行页；执行gate仍严格要求phase2。此修复不证明并发热unmap安全，仍要求原停核／同步生命周期。实际权限、跨核维护与原调度尚未执行。

## 构建与验证

```sh
.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/packaging406/build_cp_compact.py \
  --combined-page --snapshot-entry 0xbefb35 \
  --output .local/fixed-custom-filters/cp-module-next
.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/packaging406/cp_bootstrap/build_paired.py \
  --module-receipt .local/fixed-custom-filters/cp-module-next/verification.json \
  --output .local/fixed-custom-filters/cp-boot-next
.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/packaging406/cp_bootstrap/verify_memory.py \
  --build .local/fixed-custom-filters/cp-boot-next \
  --output .local/fixed-custom-filters/cp-memory-next
.venv/bin/python -B a7r5-firmware-features/custom-filters/experiments/packaging406/cp_bootstrap/verify_host.py \
  --build .local/fixed-custom-filters/cp-boot-next \
  --memory-plan .local/fixed-custom-filters/cp-memory-next/memory-plan.json \
  --output .local/fixed-custom-filters/cp-host-next
```

所有输出必须全新且在本任务`.local/fixed-custom-filters`内。固定源CPIO按全文摘要读取，实际CRC表1024字节还与独立多项式期待核对。CRC使用MSB、初值0、不作末异或；当前RX值`44b0e57f`，不是zlib CRC。

构建在新目录编译精确C／S副本，生成头始终与编译源相邻，拒绝源目录旧头遮蔽。另直接核实际目标码偏移168的CRC literal，不能只相信JSON。`test_header_binding.py`故意放入错误邻接头，旧方式先红，修复后实际交叉编译通过；隔离旧paired-v2含过期CRC，不能作为当前配对依据。

当前canonical最终回执为`continuation36-cp-final-bootstrap`、`continuation36-cp-final-memory`、`continuation36-cp-final-host`。九窗口应用和逆转逐字相同、错源拒绝；五组宿主逻辑覆盖冷复制、暖复用、失源／只读坏页、未知属性拒绝、ARM BLX解码及实际118B C校验器。宿主只替换地址、MRC和原服务边界，不执行ARM、MMU或缓存指令。

完整AP/CP启动会话、全部模式退出、四组件真实域与消费、取景／JPG和最终帧，以及实际介质尚未闭环。本目录不会因此开放产品发布准入或生成可安装固件。
