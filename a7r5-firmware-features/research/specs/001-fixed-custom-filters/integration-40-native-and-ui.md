# 原厂分组发布、完整配方和20个用户槽接线

- Updated: `2026-10-31`
- Status: `implementing`
- Input: 现有修改版4.06，原DAT／CPIO／USR不覆盖；相机与硬件模拟不在授权范围。误执行的旧指令模拟另列DEV-001，不抹除该偏差。

## 本次采用的发布行为

用户已明确接受原厂分组更新与回退。实现保留原Gamma／color selector、Post及超时行为，失败时可能短时混用新旧组件，不另造整配方原子发布器。输入校验、借用寿命和错误状态仍须确定，发送／prepared不表示像素成功。

## 已落到源码的链路

完整配方采用兼容AJR1的AJR2：固定1943字节保存seed曲线、三项tone、矩阵／CC1增量和网格。导入时联合拟合、量化后报告误差；CP按实际选中Gamma record应用tone，保留原column和八项formatter参数，避免直接用固定参考曲线替换所有运行条件。默认颜色近似仍是ST/context4及PT经验残差的显式参考，不代表本机实拍精度或其他基底已覆盖。

CP启动源码绑定实际接收器、原锁和双银行。完整接收后深拷贝到独立原生副本，Rx决定完成即可归还其租约；worker仍借用的原生副本不被覆盖。两个副本都占用时，返回明确`AF_EXHAUSTED`负ACK并保留原active；不挂起没有真实唤醒者的事务。解锁失败等未知结果保留pending与故障，不伪装已回滚。

三条实际C4复制与原队列28字节消息值复制绑定worker2／3／6；RUNNING身份由真实TaskID和queue对象确定，不使用全局当前view。原work不因私有资格失败被吞掉，原completion仍按原路径调用。私有输入只借到原worker的最后CPU读取，最终银行／图像资源继续由原厂管理。

矩阵、CC1、Gamma及网格接入四个原入口。新增`313C70`工作shot复制后缓存失效，解决同八值更换LUT及切回同基底原厂外观时Gamma可能不重建的问题；原模式抑制保留。Gamma恢复标记的清除依据是固定主formatter完整返回的原636指令CFG：五条完整129点写循环覆盖正常返回；数组有效性只是附加保守条件。第二Gamma域未因名称或全局地址相似而放开。

AP保留原v2请求接口，已保存LUT由实际不透明持久化service捕获。发送锁内提供真实会话／下一版本，重读并核当前保存代号和完整工作预设；失败不分配消息、不消耗版本。原UI八项调整发送完整配方但不隐式保存。BUSY只保留最后明确操作，原厂／NATIVE退出覆盖滞留用户请求；普通保存只增加记录代号，不丢最后工作编辑。

C01～C06采用明确二次确认后的独立overlay：没有替换时走原生数据和名称；写入私有记录后沿用户槽路由；清空tombstone后恢复原生。原Backup、旧六数组及成像资产不迁移。完整配方前六槽另需`USER20=0x80000`能力，依赖`FULL_RECIPE=0x40000`；旧端不能完成新默认HELLO，不能静默丢弃这些槽位。

## 当前可复用证据

| Evidence | 结果与依据 | 范围 |
|---|---|---|
| E-320 | `test_native_tone_asset406`及导入／恢复／传输回归；独立64位数学与当前32位实现对照、AJR1字节保持 | 数值及格式，不是相机色差 |
| E-321 | `test_cp_native_bank406`、`test_cp_jobs406`；明确排队拒绝、实际执行、唯一借用、原worker不被吞掉 | 宿主行为及Thumb编译／静态指令 |
| E-322 | `test_cp_components406`；四组件端口及完整原Gamma CFG、工作shot复制／缓存比较点 | 原接口和CPU数据拥有权，不是EVF/JPG像素 |
| E-323 | [实际绑定回执](../../../.local/implementation40-native-binding406/verification.json)，10项通过 | 真实C启动／握手／AJR2接收／原锁／银行／ACK；OS及Jobs/Components为显式宿主边界 |
| E-324 | [最终原生及明确退出链接](../../../.local/implementation40-native-integration/final-exit/verification.json)、[严格内存计划](../../../.local/implementation40-native-integration/final-exit/memory-plan.json)与[往返回执](../../../.local/implementation40-native-integration/final-exit/receipt.json) | RX25336/32768、RW静态47916/49152、永久尾408；15挂点含11 copy，25窗口内存逆转返回原CP SHA，未写完整CP |
| E-325 | [原UI回执](../../../.local/implementation40-ap-ui-full/receipt.json)、`test_stored_recipe_stream406`／`test_ap_recipe_sender`／`test_loader_recipe_source406`／`test_user20_protocol406` | 默认CUBE→实际文件保存→UI请求胶合→实际AP28帧→Rx校验，C01/C07及工作八值，错误／能力隔离；非照片效果 |
| E-326 | `test_ap_legacy_overlay`及真实仓库IMPORT/clear/reopen用例 | 二次确认、未确认拒绝、原六overlay和tombstone；仅临时普通目录 |
| E-327 | [完整原输出路由审计](../../../.local/implementation40-output-route-review/verification.json) | 21个完整CFG及33条pins；主Gamma最后CPU同步复制已定位，最终EVF/JPG流身份未闭合 |
| E-328 | [最终统一软件回执](../../../.local/fixed-custom-filters/implementation40-final-software/verification.json) | 565 passed、6项旧分支不适用skip、92.88s、exit0，全部受检源前后相同；动态UI130352B、后端576792B、AP研究92808B、CP研究92008B交叉链接 |
| E-329 | [AP动态预检](../../../.local/fixed-custom-filters/implementation40-final-package/verification.json)、[当前配对启动库](../../../.local/fixed-custom-filters/implementation40-final-loader/verification.json)与[完整配对宏默认关闭宿主检查](../../../.local/fixed-custom-filters/implementation40-loader-host-native/verification.json) | 动态AP请求58256B、12RELATIVE、原132检查／57声明；启动库89880B链接，另13项宿主边界及当前recipe宏的COW逆变换／默认关闭通过；未执行目标文件 |
| E-330 | [明确退出修复](../../../.local/implementation40-explicit-exit-fix/verification.json)及[独立复核](../../../.local/implementation40-explicit-exit-independent-review/review.json) | 先复现第5片发送失败阻断原厂切回，后ST/FL2/FL3、迟DATA/ACK、未知take及单次退出失败通过；不恢复连接，不自动重发，不保证像素退出成功 |
| E-331 | [完整原启动任务链](../../../.local/implementation40-loader-startup/verification.json)、[启动实现回执](../../../.local/implementation40-loader-startup/receipt.json)及[独立复核](../../../.local/implementation40-startup-independent-review/verification.json) | Task0/Task64因果、同UI owner/Main空闲及真实HELLO准入，12项宿主已计入E-328；56+3代码分流预装，活跃期零RX写、禁用reset原委派及ROparent失败路径修复 |
| E-332 | [原输入复核](../../../.local/fixed-custom-filters/implementation40-baseline-audit/verification.json) | 原DAT754525608B、CPIO429577216B、USR410652672B三个完整SHA再次匹配；未写输入或设备 |
| E-333 | [冻结准备清单](../../../.local/fixed-custom-filters/implementation40-final-manifest.json)、[新USR准备镜像回执](../../../.local/fixed-custom-filters/implementation40-final-unsigned-usr/verification.json)及E-334独立回读 | 新USR410652672B／646bfbb5…a44cc，1043→1047项；70资源+4DSO与AP7窗口，inode/无关内容保持、e2fsck0；未包含CP镜像更新或签名 |
| E-334 | [最终离线审计](../../../.local/fixed-custom-filters/implementation40-final/verification.json) | 364受检文件指纹与各配对构建一致，74组件及AP实际独立回读／逆转、原三输入再次匹配；当前缺口覆盖原staging工具的早期保守占位文案，不改写历史回执 |

首次统一回归实际结果为`4 failed, 543 passed, 6 skipped`，保存在`.local/fixed-custom-filters/implementation40-integrated-software/commands.json`。四项失败来自旧测试仍把C01/C06当永久非法槽：已改为原生覆盖显式确认、空overlay返回EMPTY及非法0/21返回INVALID，并保留无文件／目录／状态副作用断言；四项定向复验通过。该失败回执保留。启动／退出源码冻结后的最终E-328为565项通过、6项不适用跳过，不以首次失败或旧检查点代替最终状态。

### 执行边界偏差 DEV-001

子任务的一次回归命令误纳`test_ap_ui_confirm.py`与`test_ap_ui_lifecycle.py`旧用例，实际执行了Unicorn AArch64指令。15项在初始登记断言失败；没有进入目标reset回归，不得记成通过或未运行。已立即停止该验证路径并向用户披露；原命令、阶段与结果保存在[偏差记录](../../../.local/implementation40-disabled-ui-review/deviation.json)。后续仅使用已核对的宿主／静态／交叉编译范围；这些后续结果与该误执行分别记录。未连接相机、未执行整机或外设模拟、未写真实介质。

## 正在收口的真实启动和剩余边界

原loader的`admission_ready`无生产者已由E-331补齐：prepare在原Task0/64创建前预装56个disabled界面入口、两个通信入口及永久refresh观察者；原refresh完整运行后，由相同UI拥有者读取真实连接状态／0xF1FFF能力，并等待Main空闲才发布菜单元数据和启动存储。活跃期不再改写RX代码或撤回入口，失败保持模块驻留和禁用分流；仅在任务创建前的部分安装失败允许代码逆回滚。不手置ready，不在AppInit等HELLO，也不在已有18项呈现器打开时扩展列表。

主Gamma数值最终同步复制进入原pipe对象的地址已确认，原函数返回后不继续借用临时record。最终EVF／JPG流身份、第二Gamma域的真实请求来源、其他基底完整模型及机身介质／照片效果尚未验证。上述缺口不因接口／链接或原函数返回而关闭，当前仍不输出可安装DAT。
