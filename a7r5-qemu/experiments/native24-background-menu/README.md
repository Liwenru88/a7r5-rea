# 二十四槽后台恢复候选菜单验证

独立实验仅接受本轮固定AP／CP与合成测试BIN；原十二槽、009／010实验和默认运行时不变。使用原沙箱、真实Qt按钮和原客体帧，不提供成像就绪通知，不接触设备。

在本项目目录使用自己的`.venv`执行：

```sh
.venv/bin/python -m unittest discover -s experiments/native24-background-menu -p 'test_*.py' -v
.venv/bin/python experiments/native24-background-menu/run_validation.py \
  --manifest build/native24-background-menu-20261103-01/manifest.json \
  --log build/native24-background-menu-20261103-01/qt-validation-new.log
```

驱动通过`QTest.mouseClick`操作真实按钮，核对前台设置导航、原厂ST调参页进入及确认返回、PT／NT往返，然后遍历24款、ST／FL2／FL3、四轮菜单开关与ST重入，最后STOP。每步等待真实输入回执与新帧。原有标题与参数显示保持，后台未确认时仍锁定有风险的编辑，不能称滤镜实际成像成功。

清单schema为`native24-background-menu/1`，只读2328字节；必须有`interaction_revision=1`构建收据。E4局部变量从本次`.o`符号表与链接节解析。AP固定为`cc3dde6456dbcb40378bb93e2cbf64c661ee3543673028c7e560e62784523467`，CP与010相同。

有效运行`native-native12-410-xwuaneij`完成107次Qt操作，107幅原帧与PNG逐一核对，工作进程、AP QMP及CP侧车均退出0。最终原E4在途1、后台状态5，ST／PT／NT仍显示正常原名和参数，不再出现“选择ST重新同步”。初始化模型缺口保留，未伪造应用成功。首次运行`91wopkal`的脚本导航断言失败现场保留，仅修正脚本对原厂确认键行为的预期。
