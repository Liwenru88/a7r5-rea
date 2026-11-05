# 二十四槽八项调参候选菜单验证

独立实验仅接受012候选固定AP／CP与合成测试BIN；原十二槽、009／010／011实验和默认运行时保持。使用原沙箱、真实Qt按钮和原客体帧，不提供成像就绪通知，不接触设备。

在本项目目录使用自己的`.venv`执行：

```sh
.venv/bin/python -m unittest discover -s experiments/native24-parameters-menu -p 'test_*.py' -v
.venv/bin/python experiments/native24-parameters-menu/run_validation.py \
  --manifest build/native24-parameters-menu-20261103-03/manifest.json \
  --log build/native24-parameters-menu-20261103-03/qt-validation-new.log
```

驱动通过`QTest.mouseClick`操作真实按钮，沿原厂设置导航进入创意外观，穿过24个附加槽到ASTIA，进入原调参页，逐项编辑八项并核对只读工作值。确认退出后重新进入，核对全部保留；按C4弹出原重置确认框，UP选择确认、ENTER重置并核对初始值。随后四轮MENU开关、回到ST，最后STOP。每步等待真实输入回执和新帧，不直接写工作值、客体状态或像素。

清单schema为`native24-parameters-menu/1`，只读2404字节；必须有`parameter_revision=1`和`interaction_revision=1`构建收据。E4局部变量从本次`.o`符号表与链接节解析；新增尾部仅调用微调只读getter采样。AP固定为`e0ef19eae2be9873946e61ddf52ae72f60cef767b1cea4325268a7f1bfa8d165`，CP为`35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300`，与011相同。

有效运行`native-native12-410-a20dwgjz`的`parameter-validation.json`为PASS，工作进程、AP QMP及CP侧车均退出0。工作值从`0/0/0/0/0/4/3/1`改为`1/1/1/1/1/5/4/2`，重入保留、确认重置恢复初始值。最终原E4在途1、后台状态5，附加滤镜标题仍显示“等待切换”，ST保持正常原名与参数。初始化模型缺口保留，未伪造应用／保存／成像成功；文件持久化与原CP消费由CPU回放单独验证。

失败现场`z2ugg54v`保留初始焦点错误；`gwadnkp7`保留重置弹窗默认取消的脚本错误。它们不作为最终通过证据。
