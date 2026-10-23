# libJit 按需 SSH：默认不限时，原始挂载视图

本工具先上传三个普通程序，再由独立 libJit 载荷触发一次 SSH；不写预加载、不DEBUG、不修改原账户、不自启。终端、命令、stdin脚本及默认SCP/SFTP都经过同一原始视图入口，切换或核验失败时拒绝执行。服务默认不限时，关掉Mac终端或断网不等于停服；需要明确停止，或由相机关机/重启结束。工具不自动重启相机。

**当前阶段是离线交付，不能把QEMU通过当作真机安装或恢复通过。实机载入和启动仍需用户确认。** 完整设计和风险见同目录`方案.md`。包中含密码哈希，目录须0700、文件0600，不公开上传。原厂文件、原始镜像、旧包、锁及卸载证据均保留。

## 本机准备和检查

在项目根目录使用已有`.venv/bin/python`。`package.py`只读本机口令文件并生成哈希，不把明文口令复制进包，也不连接设备。默认寿命0表示不限时。需要不同寿命时显式传`--ttl 正整数秒`，启动/传输/清理的超时仍然有界。

```sh
.venv/bin/python -B a7r5-ssh/libjit-ssh-on-demand/package.py \
  a7r5-ssh/libjit-ssh-on-demand/packages/自行选择新包名 \
  --password-file a7r5-ssh/ssh-service/fixed-password-input
```

以封包输出的绝对路径作为`PACKAGE`，仅核对本机：

```sh
.venv/bin/python -B "$PACKAGE/tool.py" check --package "$PACKAGE"
.venv/bin/python -B "$PACKAGE/tool.py" status --package "$PACKAGE"
```

包及本机依赖都绑定摘要，移动目录或更改材料后应重新封包。每包只允许一次载入、一次启动、一次停止及一次只读回收，各阶段永久锁及失败日志保留；下一次使用准备新包。随机前缀平铺的三个程序消除了载入阶段创建相机目录的需求，代价是不同包会留下独立材料；不自动删除旧材料。

## 实机执行顺序（须另行确认，当前不要执行）

1. 确认相机固件4.00、稳定独立供电、屏幕正常、Wi-Fi及当前IPv4。USB和全部媒体应匹配封存基线；历史端口、IP及媒体信息不自动代表现在正确。不改卡、不格式化，不为通过门槛自动放宽基线。
2. 审阅固定上传路径和摘要后，运行本包`load-once.command`，输入`check`中该阶段短语，按本机sudo提示认证。只上传`.service`、`.session`、`.sftp`三个随机前缀程序并回读；此时不上传`libJit.so`，不启动SSH。
3. 普通USB、驱动和媒体连续两次核对通过，用户查看屏幕正常后，仅在本机记录确认：

   ```sh
   .venv/bin/python -B "$PACKAGE/tool.py" confirm-screen --package "$PACKAGE" --phase load-once --screen-normal
   ```

4. 审阅并另行确认后执行`start-once.command`。检查三个程序与精确512换行预加载，上传本次票据与固定`/tmp/jiritsu/libJit.so`各一次。私有RAM里生成新主机密钥；主机通过已认证USB读取本次公钥，固定校验公钥摘要、READY、解除触发回执和前进心跳。全部通过才发送一次USB STOP；USB恢复及人工屏幕确认后才允许SSH连接。`confirm-screen`阶段改为`start-once`。
5. 监听`0.0.0.0:2222`，使用私有RAM账户密码登录；不依赖之前已删除的私钥。可信主机公钥保存在`.state/start-once/known_hosts`，首次也不能使用无条件接受主机密钥。连接示例是供用户在批准实机后手动执行：

   ```sh
   # TARGET必须是相机当时界面显示的IPv4；RUN取check输出的run_id。
   ssh -F /dev/null -o HostKeyAlias="a7r5-libjit-$RUN" \
     -o UserKnownHostsFile="$PACKAGE/.state/start-once/known_hosts" \
     -o GlobalKnownHostsFile=/dev/null -o StrictHostKeyChecking=yes \
     -o IdentityAgent=none -o PubkeyAuthentication=no -p 2222 "root@$TARGET"
   ```

   stdin脚本：在同样选项后添加`/bin/sh -s`并从本地脚本重定向stdin。命令使用`/bin/sh -c`语义；命令退出码直接返回。正常终端使用普通sh，不通过全局profile启动其它脚本。

   默认SCP通过外部SFTP服务端，使用相同主机别名、公钥文件和认证选项，将端口参数改为大写`-P 2222`。可双向传输；默认示例仅向本次`/tmp_network/`测试路径写入。旧协议`scp -O`未列为支持。

6. 结束前先退出自己的终端并完成传输，再运行`stop-once.command`。它经一次独立USB会话读取固定READY/主机公钥/心跳，写一次精确会话号停止请求；不依赖即将被终止的SSH通道回传最终结果。回收完整父/子终态、重复终态、结束心跳和预加载基线后才一次USB STOP。恢复及屏幕正常后确认`stop-once`，解除本机活动标记，永久锁及日志保留。
7. 若用户显式采用有限寿命，或服务已通过批准的其它方式结束，可选择`collect-once.command`仅读取固定RAM终态，不重发停止请求。需要先满足同包启动与恢复记录。未知USB状态或失败待恢复门槛下，不允许用此入口绕过恢复；应先另行准备受限恢复方案。

关闭一个SSH终端不会自动停止服务。默认不限时没有离线到期兜底；Mac关机、休眠或网络断开后机内监听可能仍在。手动停止失败时保留证据，不重试、不杀未知进程、不自动断电。用户命令可能改变真实系统，工具不会自动回滚这些写入。

## 状态、日志和停止条件

每阶段记录于`.state/<阶段>/`：原始接口、响应头、分块边界、固定文件副本、原始主机观察、协议摘要及结果。全工具共享`a7r5-exec/ACTIVE_SESSION.lock`互斥，本工具`PENDING_RECOVERY.json`及`ACTIVE_SERVICE.json`阻止重复启动和未收口后继续操作。屏幕确认只解除成功阶段的本机待确认标记，不能覆盖失败结果。

清理结果中的`originals_unchanged`只对应监测的原账户、NSS、原厂sshd配置及选定挂载基线，不表示相机所有文件未变；用户root命令产生的其它写入不在这项检查的审计范围内。

以下情况立即停止，不换端点、不重发、不自动恢复：材料或依赖变化、可读路径冲突、未知预加载、版本/加载库/接口不符、协议失步、上传读回不符、READY或心跳不符、端口占用、视图/密钥检查失败、退出次数或清理门槛不符。文件结果`0x10000006`只能表示当前不可读，不能证明不存在；固定libJit路径仍有覆盖与持久残留风险。

## 离线验证

```sh
.venv/bin/python -B -m pytest -q a7r5-ssh/libjit-ssh-on-demand/tests
.venv/bin/python -B a7r5-ssh/libjit-ssh-on-demand/verify_qemu.py
.venv/bin/python -B a7r5-ssh/libjit-ssh-on-demand/verify_flow.py
```

QEMU不带网卡、不透传USB/SD，SSH字节仅通过串口与本机Unix socket桥接，测试口令临时生成。验证原始/私有视图访问差异、UID/能力/环境、终端、窗口变化及Ctrl-C、脚本退出码、双向SCP摘要、只读挂载拒写、坏证明零用户命令执行、不限时跨600秒、停止回收及QMP正常关闭。`verify_flow.py`另将实际主机操作器接至QEMU文件通道，核验四阶段策略、显式有限寿命、未知预加载、活动实例冲突及AArch64符号链接拒绝；不是USB协议仿真。有限观察不代表无限期稳定性；Sony真实USB触发、跨STOP及Wi-Fi仍需实机确认。

外部SFTP沿用已保存的Debian OpenSSH7.4p1二进制及版权、来源摘要；未本机源码重建，未验证发行签名。相关限制随包保留，不将本工具视为长期安全审计结果。
