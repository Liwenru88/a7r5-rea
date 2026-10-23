# A7R5 SSH 原始视图候选

本目录实现“私有账户认证，登录后进入原始挂载视图”。命令、stdin脚本、交互终端和默认SCP/SFTP使用同一会话入口；不改原账户，不用profile，不自动把只读分区改成可写。旧2222服务、自启库及旧材料继续保留。

当前交付是04离线候选，尚未安装。03阶段A因历史持久密钥源在当前视图不存在而停止，失败记录和锁保留。现已通过现有SSH只读确认当前HostKey位于私有RAM；未读取私钥内容。后续上传、libJit锚点、2223启动仍分别确认；不替换2222，不启用新自启。

## 实现链路

1. 上传前绑定当前旧sshd的PID、启动时间、挂载命名空间、会话祖先及HostKey声明，检查RAM密钥root:root、0600、505字节、单链接普通文件。通过后在唯一新目录上传4个AArch64程序及start.sh；只写本地已信任的公钥，不把私钥复制到持久目录。认证密码仅复用旧材料内的哈希；材料含敏感哈希，整个目录0700、文件0600，不公开上传。
2. 用现有libJit一次性工具执行本包anchor-task.sh。它只生成本次RAM证明，不启动后台进程。探针要求唯一 `/usr/bin/bootin.elf` 进程的挂载命名空间和根目录与libJit任务完全一致，记录PID、启动时间和对象身份；不能用PID1猜测替代。没有唯一匹配立即失败。
3. 锚点任务、USB恢复和人工屏幕门槛通过后，通过现有SSH执行一次 `--launch-from-proof`。再次检查来源后，先持有旧认证视图RAM密钥目录FD；核对证明并进入原始视图，再建立私有认证子视图。FD跨两次视图变化保留，仅在新私有tmpfs中创建0600副本，核对源未变后关闭FD，不记录私钥字节或摘要。
4. 新sshd监听0.0.0.0:2223，候选寿命600秒。ForceCommand统一进入session.arm64，核对监督器PID/启动时间、nsfs对象、根目录、能力和组；仅setns mount，校正root/cwd，恢复可信附加组及umask后执行。失败退出126，不执行用户命令，不退回私有视图。
5. SFTP使用外部服务端而非internal-sftp。子系统固定命令和用户恰好执行该服务端绝对路径时进入SFTP，其余命令原样交 `/bin/sh -c`。无命令时启动普通sh；不读login profile改变基础环境。

基础环境为 `PATH=/bin:/sbin:/usr/bin:/usr/sbin`、`HOME=/`、`LC_ALL=C`，TTY所需TERM按可打印长度约束保留。只读分区属性继续生效。普通SSH的会话、流式输出和后台任务不套用libJit单任务15秒/32KiB限制。

## 本机检查

在工程根目录，使用既有 `.venv/bin/python -B`。查看具体包：

```sh
.venv/bin/python -B a7r5-ssh/ssh-service/original-view/packages/original-view-20261021-04/candidate_once.py check
```

`check`只读本机，显示各阶段摘要短语、待恢复标记及旧失败收口状态。标记消失不自动视为恢复。默认不连相机。三个 `.command` 文件都需要针对本包、本阶段另行批准并手动输入短语，不能代替聊天中的实机授权。

从ZIP解压后，先对解压出的包目录执行 `chmod 700 "包目录"`，再运行check；这是本机权限设置，不访问相机。

完整执行顺序、停止条件和恢复边界见 [实施与恢复清单.md](实施与恢复清单.md)。

## 源码和验证

- `proof.h`：原始视图证明、PID复用防护、mount-only切换、能力/附加组/umask核对。
- `anchor.c`：libJit侧固定锚点补证，无后台任务。
- `launcher.c`：独立2223监督器，私有认证和RAM 0600密钥；运行期原件变化记入回执，不自动回滚用户写入。
- `session.c`：统一shell/命令/外部SFTP分派，保留PTY标准描述符。
- `candidate_once.py`：默认离线、逐阶段单次锁、共享原工具互斥和待恢复门禁；复用连接消失时禁止重新连接认证。
- `build_candidate.py`、`package_materials.py`：离线重建与封包，旧文件不覆盖。
- `tests/`：本机调度失败验证和仅QEMU故障夹具。
- `verify_qemu.py`：真实Mac OpenSSH、默认SCP经Unix socket/串口到无网卡QEMU；额外用Paramiko发送PTY窗口变化和Ctrl-C。不会打开主机TCP或透传设备。

重建源码随包保留；可在新目录用同一config.h与编译命令重建比对摘要，不能覆盖已封存材料。源码中的原始账户SHA是前置基线；若机身已更改原账户，应先分析和重新批准适配，不能直接删掉检查。

QEMU使用唯一稳定测试进程代替机身bootin作为锚点；并模拟旧私有/var源路径在原始视图中消失的情况。真机bootin锚点、2223候选、实际终端和SCP仍未验证。本轮实机证据仅覆盖现有2222的可信主机密钥认证、当前配置及密钥元数据，不能代替候选安装验收。

## 外部SFTP来源和限制

独立SFTP程序取自 [Debian官方归档](https://archive.debian.org/debian/pool/main/o/openssh/openssh-sftp-server_7.4p1-10+deb9u7_arm64.deb)，OpenSSH 7.4p1 Debian补丁版；它不是Sony原厂新增文件，也未在本机从源码重建。版权、下载来源、包和ELF摘要保存在sftp-COPYRIGHT和sftp-provenance.json；本轮未验证Debian发行签名。ELF为AArch64，只依赖libc和动态加载器，版本需求为GLIBC_2.17；与目标glibc2.25的兼容性还要结合QEMU和实机各自验证，不能仅凭版本号认定安全。

这属于旧版附加依赖。候选保留密码认证和通配监听，仅用于批准的网络与600秒验收窗口。长期切换前应另行选择维护版本的SFTP实现并重新验证，不能把此次离线成功等同长期安全审计。
