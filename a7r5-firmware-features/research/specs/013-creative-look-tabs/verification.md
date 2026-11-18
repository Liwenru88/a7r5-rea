# 验证记录

Feature ID: 013-creative-look-tabs
Status: NOT_VERIFIED

本轮只验收离线实现及原AP菜单操作，整体仍为`NOT_VERIFIED`。012的70项／106帧只作历史基线，不替代本轮Tab证据。相机、真实介质、成像、签名及DAT不在本次范围。

## 当前证据

| Evidence | 实际执行 | 结果与边界 |
|---|---|---|
| E-001 | 旧012首项UP回归、旧06上游包装器回归、旧07刷新反查回归 | 按预期失败，分别复现无Tab焦点、上游绕过分组、组内第二行变PT；失败XML及原帧保留 |
| E-002 | 最终09的Tab定向及原43行注册／导航检查 | 11项PASS，2.56秒；覆盖三条资格入口、无应用、稀疏槽、空组、取消、刷新及调参页隔离；原UI发布为明确夹具 |
| E-003 | QEMU固定身份检查及满库实际Qt运行`native-native12-410-brzkxnbo` | 2项身份PASS；115次操作，18个本模式原厂可见项（含ST、FL2／FL3）及24槽循环、右键八项编辑、确认、重入、重置和四轮MENU均PASS；Qt／AP／CP退出0 |
| E-004 | 合法空库实际Qt运行`native-native12-410-et3ph4au` | 39次操作PASS；显示空组，下／中键停留、不应用、不选不存在槽，返回原厂及四轮MENU正常，三侧退出0 |
| E-005 | 独立09／10构建、012清单、旧DAT及重开定位补充回放 | 四组件逐字节一致；012的1048项摘要、原压缩包及旧4.10／4.11 DAT保持；CP与两图形资源同012。已恢复选择为夹具，真实AP重开定位第1／24槽及FL3均PASS |
| E-006 | 最终09完整相关CPU回归 | 80项PASS，1212.88秒；原始XML及`regression/session-result.json`同为PASS，完整相关集合、源码前后不变、构建与组件一致 |
| E-007 | 新研究归档、原帧／PNG及来源新鲜度门禁 | PASS：满库115帧、空库39帧逐字节一致，来源新鲜度及正常退出门禁通过；1369项摘要及压缩包逐成员重新读取核对。旧归档不覆盖 |

切Tab／进入列表的九次操作中，CP消息数保持31，命令序号保持0、已选编号保持0，`R5FILTER.BIN`只读长度及完整字节不变。合法空库的七次对应操作也保持应用状态不变。这里证明没有新应用意图，不表示停止或撤销已被后台接收的事务。

八项从`0/0/0/0/0/4/3/1`逐项改为`1/1/1/1/1/5/4/2`，重新进入完整保留，原重置框确认后恢复初始值。QEMU原E4在途及后台等待状态保留，不能将工作值当作已保存或成像成功。

AP：`d76eea4e83db227ae7ebdf05b02834719aed1854e14c402907f3906acd4f5ffb`。

CP：`35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300`。AP BSS 290520字节，CP代码7544字节、堆请求947000字节，真实堆及线程高水位未测量。

最终回归命令（仓库根目录）：

```sh
A7R5_NATIVE24_BUILD="$PWD/.local/native24-tabs-20261103-09" \
A7R5_NATIVE24_EVIDENCE="$PWD/.local/native24-tabs-20261103-09/regression" \
.venv/bin/python -m pytest -q a7r5-firmware-features/native24-combined/tests \
  --tb=short --junitxml=.local/native24-tabs-20261103-09/regression.xml
```

QEMU独立清单为`native24-tabs-menu/1`，只读2444字节；最终满库`build/native24-tabs-menu-20261103-07/manifest.json`、空库`build/native24-tabs-menu-empty-20261103-04/manifest.json`顺序运行。复现见[实验说明](../../../a7r5-qemu/experiments/native24-tabs-menu/README.md)。

| Acceptance | 当前状态 | 证据 |
|---|---|---|
| AC-001 分组／焦点 | PASS（离线逻辑与聚焦画面；滚动显示限制见下） | E-002／003／004 |
| AC-002 保留操作 | PASS（实际菜单操作） | E-002／003 |
| AC-003 浏览不应用 | PASS | E-002／003／004 |
| AC-004 一致恢复及边界 | PASS（机器码及明确边界夹具） | E-002／003／004／005／006 |
| AC-005 可追溯交付 | PASS | E-005／006／007 |

归档：[研究组件与证据](../../native24-combined/verification/2026-11-03-tabs-01/README.md)、[结果](../../native24-combined/verification/2026-11-03-tabs-01/results.json)、[操作说明与截图](../../native24-combined/Tab分组交互说明.md)。压缩包67611206字节，SHA256为`7d5f2b33a2bc152918e434643b0339c7fe267f22c4f86d93730e12e77b774d29`。显示限制另随包保存于`build/known-limitations.json`，不可当作可安装升级包。

## 未验证边界

长列表滚动的AP抓帧偶有顶部文字部分或全部缺失：本轮`brzkxnbo/research-064-DOWN.png`与旧012的`a20dwgjz/research-032-UP.png`均可见，聚焦Tab和重入时可见两组。当前模拟器未实现完整CP合成／面板，不能确定实机表现或将其直接归因于本轮Tab改动。未改截图、未猜测原控件字段；不能声称该显示现象已修复。

真实LCD／EVF／JPEG、原E4完整初始化与应用、机内保存的实机确认、真实介质掉电、全模式与堆／线程高水位及安装仍为`MANUAL_REQUIRED`。新增13～24号是合成容量测试配方，不是新增成品滤镜。未连接相机，未签名、封DAT、提交或推送。
