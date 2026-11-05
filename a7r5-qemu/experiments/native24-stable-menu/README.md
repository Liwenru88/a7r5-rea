# 二十四槽稳定性候选菜单验证

独立实验仅接受本轮固定AP／CP与合成测试BIN；原十二槽、009实验和默认运行时不变。使用原沙箱、真实Qt按钮和原客体帧，不提供成像就绪通知，不接触设备。

在本项目目录使用自己的`.venv`执行：

```sh
.venv/bin/python -m unittest discover -s experiments/native24-stable-menu -p 'test_*.py' -v
.venv/bin/python experiments/native24-stable-menu/run_validation.py \
  --manifest build/native24-stable-menu-20261103-05/manifest.json \
  --log build/native24-stable-menu-20261103-05/qt-validation-new.log
```

驱动通过`QTest.mouseClick`操作真实按钮，逐步核对前台设置导航，然后遍历24款、ST／FL2／FL3、四轮菜单开关与ST重入，最后STOP。每步等待真实输入回执与新帧；原E4未就绪时只能验收同步／失败／需恢复提示，不能称滤镜实际成像成功。只读采样按源节映射；移除了已取消私有页的旧观察器，保留原生E4及九分派原体追踪。

最终实验schema2、只读2328字节。E4局部变量从本次`.o`的符号表与链接节布局解析，不沿用合并BSS中的旧偏移。原目标文件及地址解析已归档。有效运行`native-native12-410-ekfna2tl`包含96原帧，等待字段0、原E4在途1和需恢复1，三侧正常退出；QEMU初始化缺口保持，没有伪造完成。早期`wrm62iij`中旧偏移观测不作为最终E4数值证据，原文件保留。
