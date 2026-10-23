# 无 SSH 隔离/跨 STOP 补证的离线验证

日期：2026-10-20。范围：本机源码、受控进程、协议替身和隔离QEMU RAM。**没有实机执行、相机请求、账户字段修改或真实sshd启动。**

## 1. 实现与边界

- `isolation.py`：准备/校验、分阶段批准与锁、READY/心跳/终态门槛、固定只读收集入口。probe和collect不自动串联。
- `src/ns_probe.c`：私有挂载子进程、原字节账户副本、父视图核对、75秒元数据观察、RAM终态、直接子进程回收；不含exec、网络监听或账户变更接口。
- `src/ns_abi.h`、`src/ns_sha256.h`：目标ABI与流式证据摘要；摘要不用于自制认证协议。
- `src/root_once.c`：复用原有精确argv、中和、固定脚本与输出限制；只纠正目标ARM64的O_NOFOLLOW数值，没有开放其他触发入口。
- `isolation_qemu.py`：验证真实AArch64代码、完整固定载荷链路和退出，不改默认模拟器输入、沙箱或网卡。
- `isolation_pack.py`：只封存当前源码、vendor和本次无批准材料，不遍历旧实机结果或旧锁。

## 2. 定向测试

最终相关回归：**33个测试方法，25.251秒，OK**，日志为`verification/isolation-v1/unit-verified.log`。其中`tests/test_isolation.py`有11个方法，覆盖：

- 本机临时普通文件下的原字节副本、挂载步骤失败注入、父视图不符、子进程提前退出、输出管道关闭、有限寿命和回收。
- SHA-256与标准库对照：空串、abc、边界块、多块及65536字节。
- 两阶段分别缺少批准即拒绝；模板为false；旧阶段锁、等待截止、前次收据变化及材料篡改均拒绝。
- 真实RestrictedChannel报文解析器下的头损坏、基线变化、完整读回不符、DEBUG失步、旧/非root状态、错误READY摘要、命名空间未变化、冻结/过期心跳、中和/重复状态变化。
- 独立读回没有文件写入或DEBUG；终态、回收、原件和长度/摘要错误均不放行；保留负结果及原始响应。
- READY后移走运行目录并在原路径放置替代目录，后台仍向原目录描述符写入，替代目录保持空白；不因路径变化落入其他文件系统。

主机C测试用替身表示命名空间系统调用，不证明macOS提供Linux命名空间。下列QEMU验证补充真实目标行为。最终回归及源码摘要见`verification/isolation-v1/summary.json`；`unit.log`是补强前32方法的通过记录，`unit-final.log`是严格编译拒绝字符串偏移写法的失败记录，均保留，不替代最终通过日志。

## 3. QEMU 实际结果

三次取得隔离能力正回执，均完成75秒生命周期并通过QMP正常退出：

| 目录 | 覆盖内容 |
|---|---|
| `verification/namespace-qemu-ly58d7nr/` | 直接执行真实AArch64启动器；不同mnt namespace、原字节副本、只读bind、父视图不变、完整观察/摘要及子进程回收 |
| `verification/namespace-qemu-z5f0wug5/` | 完整预加载载荷→启动器→READY→固定任务DONE 0→512换行中和→后台75秒观察→回收；另验证ARM64目录/stat布局和NOFOLLOW拒绝软链接 |
| `verification/namespace-qemu-aiu_0ikz/` | 最终目录描述符补强版，完整载荷链路、32KiB上限、原视图不变、15份网络样本及回收全部通过；默认QEMU输入不变 |

第三次是最终C源码的完整集成证据。新包重新生成nonce，二进制不必逐字节等同；验证收据比较C源码和去除nonce/本次启动器摘要后的固定配置。Python门槛由协议替身单独验证。

QEMU运行时使用新RAM账户夹具，root shell保持`/bin/false`；启动器复制前后字节不变。夹具SHA-256为`3b1e35fade26860d3e66991284f02f719f5331de4c725a3753e63b1e02e86764`，**与实机预检基线不同**，不能拿QEMU回执冒充实机READY。实机入口仍要求本次已固定的真实摘要。

没有QEMU网卡、USB/SD直通或外部网络监听；默认runtime输入摘要不变。QEMU未发送真实相机STOP，也没有真实无线接口，因此只能证明载荷/进程/隔离机制，不能证明实机跨STOP存活或联网。

## 4. 保留的失败与修复

- `namespace-qemu-63073rtf`：上传命令过长造成终端截断；中断本次控制进程，通过QMP退出，改用已有验证的48字节上传分块，并在执行前核对SHA-256。
- `namespace-qemu-0oiy0p96`：启动准备退出88，缺少明确步骤；保留日志，增加启动阶段步骤码及errno。
- `namespace-qemu-iicxu33o`：定位为`var_metadata errno=22`；使用了其他架构的O_DIRECTORY值。核对Linux 4.9 ARM64接口后修正，并对真实目标行为增加回归。
- `namespace-qemu-c2zrno_a`：目录描述符补强后的构建被`-Werror`拒绝，未启动虚拟机；改用显式数组地址表达式，随后最终33方法及完整目标验证通过。

元数据调用不直接依赖目标libc缺少的fstat/lstat包装，采用已核对的ARM64系统调用和128字节stat布局。O_DIRECTORY为`040000`，O_NOFOLLOW为`0100000`；原执行器的目标分支同时修正后重建。[Linux ARM64 fcntl定义](https://github.com/torvalds/linux/blob/v4.9/arch/arm64/include/uapi/asm/fcntl.h)、[stat布局](https://github.com/torvalds/linux/blob/v4.9/include/uapi/asm-generic/stat.h)、[系统调用号](https://github.com/torvalds/linux/blob/v4.9/include/uapi/asm-generic/unistd.h)

没有删除失败目录、旧包、旧ZIP、原批准、尝试锁或旧实机证据。未修改原始固件镜像、默认QEMU运行材料或物理介质。

## 5. 未验证项

真实相机与QEMU可以有不同权限、内核配置和挂载行为。实机仍须一次性补证，不能因QEMU成功而直接启SSH或改账户。RAM结果可能被休眠、模式切换或原厂进程清理，也可能在重启后消失；不能回退成后台持续写持久分区。

独立读回新增一次认证/START/STOP会话的风险已在执行方案列明，必须另行批准；没有自动二次认证。若此方式不能接受，应停在第一次READY及主机恢复证据，不能虚称已取得最终网络轨迹。
