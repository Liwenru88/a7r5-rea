# A7R5 N0 本机单地址补证入口

只用 Python 标准库，复用工程现有虚拟环境，不需 sudo。默认不联网；prepare/check 都是本机操作。

当前具体步骤见 [执行与停止方案](执行与停止方案.md)。本轮目标为用户从相机界面提供的 `10.10.10.117/24`，连接路由器 Wi-Fi、USB 保持连接且模式未独立查询。当前没有联网批准。

## 本轮可用的离线命令

在工程根目录：

```sh
a7r5-qemu/.venv/bin/python -B a7r5-ssh/n0/n0.py check --operation a7r5-ssh/n0/packages/n0-20261020-01
a7r5-qemu/.venv/bin/python -B -m unittest discover -s a7r5-ssh/n0/tests -v
```

测试全部使用替身，不发送真实网络请求。

## 未来重新准备目标

仅当确有新的准备需求时使用新目录名。下面是本次准备命令的记录，**已经执行过，不要重复覆盖现有目录**：

```sh
a7r5-qemu/.venv/bin/python -B a7r5-ssh/n0/n0.py prepare \
  --name n0-20261020-01 \
  --address 10.10.10.117 --prefix-length 24 \
  --address-source camera-screen --network-mode access-point \
  --usb-state connected-mode-unconfirmed
```

prepare 只写本机新目录，生成计划、拒绝模板和 Terminal 入口。没有自动批准命令。本次未使用 `--icmp-fallback`，不会启动 ping。

实际联网入口为该新目录的 `run-n0.command`，只有另行明确确认后才生成绑定本次计划且有效15分钟的批准。保留旧目录和锁；失败不重试，不为重试自动换目录。
