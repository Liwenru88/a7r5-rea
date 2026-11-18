# 第46批：真实请求副本、Capture颜色及最终输出来源

本批沿用现有修改版4.06；不扩大AJR2/AJR3或Gamma格式。所有实现和验证限于源码、宿主行为、固定CP静态反汇编、交叉链接及匿名内存补丁正逆。未操作相机、执行ARM或硬件模拟，也未写出完整CP／USR／DAT镜像。

## 本次修正的实际缺口

旧实现能绑定Capture的Gamma，但不能据此推导普通照片的矩阵、CC1和残差网格也已应用。普通照片请求从原live地址`157AA10`复制到独立`163F3F0`，并不读取已有worker的canonical副本；其`ADD7FA`构造链还会重新把请求转为`R=A+20`。此外，`48E842→7187D0`之后，普通Capture的另一原路径`717C4C→73E25A`还会以mode6重建颜色。只挂前一处会使后续重新使用原厂组件。

现已实现：

| 落点 | 实际改动 | 原行为／失败处理 |
|---|---|---|
| `ADF128`原memcpy | 按真实LR `ADF12D`分流，新增独立第四输入快照；原`0x24`非阻塞拥有者内复制、九字段投影、同版完整运行配方缓存 | 原copy始终一次；错源／尺寸／锁忙仍原委派，无私有资格；不写live或原六槽 |
| `ADD846→4596F4` | 原copy前后绑定本A请求号、请求epoch、线程及R实际复制字段子集 | begin期间请求换代由end撤销，不把相同参数当来源；原copy一次 |
| `719EF6`全部18个已核直接入站 | 共用永久门包裹原`719EF7(root,pipe)`，13个BL和5个B.W各保留原控制流 | 原入口和旧`48E842`不改；主operation不占Capture scope；不匹配C4／R／线程不授配方 |
| 原矩阵、CC1及网格 | 由Capture独立按值缓存授予来源；矩阵含现有16区形式；原构造后施加增量，网格借原packer | 主worker仍核原id3／C4；Capture不假冒主worker；原参数、校准和分组回退保持 |
| Capture网格mode6／11 | 必须原native工作区`+C==11`、最终stage1；重建原第二个1620B packed区 | 不放行默认stage3、mode7或任意stage；原厂／无view／故障仅清已跟踪packed；原返回后恢复raw借用和LR |
| A归还／池拆除／恢复 | 撤销伴随来源及缓存引用 | 保留原图像和A引用管理，不增加私有图像帧租约 |

Capture按值缓存包含两个完整运行配方和490个8B A关联，与原54880B Gamma记录一并在首次bind申请63072B普通堆。原R+150（真实请求source+238）必须为0，与主域支持合同一致；旧六款／未知模式保留原厂，不把它们的矩阵或CC1与新配方叠加。旧照片继续持有旧缓存，新请求不覆盖仍被A／同步构造借用的版本；两个版本均占用时回退／BUSY，不误报新配方已应用。仅支持同一次CP启动的普通堆寿命，未知同址热重建不支持。

审查曾找到并修复三项真实问题：普通malloc尾部未清零造成首次颜色初始化失败；A请求号预检与begin内部取快照之间存在换代窗口。新增脏堆A5及请求77→78／版本41→42回归均先复现、后通过。另补齐Capture原模式资格检查：旧249／未知1模式先复现误授配方，再以R+150==0修正，15项目标包装通过。最终共用入口的主operation、不匹配C4和原一次委派另有定向用例及只读审查。

## EVF真实源与原厂生命周期

已排除OSD：`2001/0501`和Image_Common_Start_Time／Offset不能当照片帧或滤镜版本。真实YC/YUV路线为：

```text
原task内同R／C4
 → AFE008主Gamma、原队列AFACD4／4C32A8主颜色
 → 4B3AD4：R+180+70*k实际DMM对象
 → 13DA18：165DB40 ImageSizeInfo
 → 4C00D8：原StdYC单元生产
 → 45765C／source 90050004／原Connect peer
 → 9284074A relay／原同步9缓存发布
 → 2001/0500 YUV命令
 → 6AB15E／1F1A28／6A22E0
 → B80E06原显示driver
```

Gamma和输出准备属于同R的不同异步状态，不能写成一次同步调用中的先后顺序。真实DMM对象来自同R的索引记录，而非在发送口读取“当前滤镜”补版本；原队列复制并持有原task/R。原YUV持有、引用递减和归还沿`6A1558／6A163E／6A1676／6A16F2`，不以OSD回调替代。

该链是已核原连接成立时的源码证据。运行期peer是否为`9059081A`、照片连续流和物理EVF效果仍需现场验收；不新增逐帧私有publisher。原relay reset不持同步9，所以不能把同步9下的快照描述成能抵抗全部reset的通用锁。

## JPG颜色、网格与Gamma的真实消费

同A的普通颜色分支`46C1B8`先调用`717C4C`构造并序列化，随后`46C1F2→AAC708(R)→AAC710`立即提交。`A+3008=R+2FE8`经`AAA6E0→755C00`进入矩阵寄存器域；`A+323C=R+321C`经`AB1A4C→7586B8`等进入颜色域。`A+2F84`是原参数关联块，不能把它叫网格packed指针。

真正的网格描述符是`A+32CC=R+32AC`，控制enable、packed地址、上传dirty分别在`+0/+14/+18`。原controller的state+18/+20/+24经`72869A`收集、`72B020`序列化；mode11的`718AB4`和mode6的`717F2A`都真实调用该序列化函数。随后同R／同照片资源Q的`414F44→757068`按原dirty与base条件，以八次同步copy上传1620B至原SRAM窗口。上传器不保留私有1215B raw，CPU最后节点读取已在`2318B2`结束；没有把私有cache指针交给异步DMA。

mode6后处理index0/1/2/7从本次state收集，4/5/6恢复原snapshot，3跳过本次收集。仅已证鲜活分支可称本次packed到上传；原恢复／禁用／cache／失败语义保持，不能概括所有mode6都会上传本次私有网格。正常ST且原source+238==0时，主／第二域均由原构造明确生成强度8；不是靠测试将level手填1，也不改写原强度。原level0同样可能走不缩放，不能将0解释成禁用或据此盲放开支持范围。

Gamma的同A／同Q关联也已固定：原`46BC2C→AE3A70(1)`得到Q=`190C630`，将Q写到`A+5A98`，将Q+140／Q+7B8写到`A+BB0/+BB4`。`46F3AC`在原`mask&80`成立时调用`AEC71A→AAC91A→AA7332→AA7FA8→AA86D0→755BA4`，同步读取第二域原银行。后续同A的`4706B4`将同一Q交`463BB8→74077A→74793A`实际producer；其主YC句柄A+59F0又是后续原JPG编码输入。

`A+2CDC`经原注册回调与字符串确认是最大信号电平派生数值，不是Gamma曲线指针或资源ID。原mask2B／7F不包含80，不能用上述一次显式提交推断它们每次重发第二域Gamma。另已核stage11正常SCNYC序列：同task的state1进入480DE4，在A218==3、A5B1E==0及A64BC==0时经483C28提交Gamma；state2进入470314的7F生产路径。原456CF8执行器仅在回调正常返回0后于456D5C..62递增task+27，再沿原调度器重新入队，因此是原异步任务的真实先后关系，不是一次同步调用或无条件成功。两种2B序列分别由请求type4/type9选出；不将它们默认为所有普通拍照，也不凭DEV名称排除为诊断。特殊请求当前Gamma覆盖仍单列，见`.local/implementation46-jpg-gamma-variants/`。原图像句柄、JPG请求槽及回调仍沿原协议：请求slot在回调前清空，回调使用此前按值复制的元数据，不能在回调时读当前slot赋滤镜身份。CPU参数消费、编码完成、A回池及最后物理DMA分别记录，不相互替代。

可复跑细证据分别为`.local/implementation46-jpg-flow/JPG_COLOR_SUBMIT.md`、`.local/implementation46-grid-consumer/README.md`、`.local/implementation46-grid-eligibility/README.md`和`.local/implementation46-jpg-gamma-alias/README.md`。它们交叉核对同包原raw／SHA与真实赋值，保留所有原branch／mask／后端child条件。

## 原厂保护、容量及最终检查

新Capture完整配方模块超出原8页代码容量。已基于同包原SOLID尾／原映射器及冷源必清范围核定固定22页布局：RX十页`2AEA000..2AF4000`、RW/XN十二页`2AF4000..2B00000`，冷源`11C8000..11D2000`。原栈、L1/L2、RW起点及旧资产不移动；原四页和二十页分支保持。不是通过任意heap地址获得执行权。

最终实际链接RX38344/40960B、静态RW48744/49152B，bootstrap408B；七个局部段物理486B、存储488B含两个零pad，50挂点和原factor构成1176B只读合同。67窗口只在匿名内存中变换，精确逆转回原CP摘要。旧六资产、FL2／FL3、声音和原helper有效代码均受保护，`BEF9C8`声音区未借作空洞。

最终同源验证：

- 统一相关宿主回归786 passed、21配置不适用skip，143.18秒、exit0；配对AP／CP／UI及仓库库编译链接通过。
- 7个真实C宿主可执行程序共97场景（模式修复后重验target15，复用342份未变源对应的其余82场景）通过ASan／UBSan；只替代固定地址和原硬件端口，不执行ARM。
- 387份软件来源、114份原生构建来源、344份消毒检查来源核对当前摘要一致；原DAT／CPIO／USR完整摘要一致。
- 实际native ELF、50挂点、67窗口、前像／逆转及旧资产保护通过。静态CFG与宿主执行分别记录，不能相互冒充。

总审计：`.local/fixed-custom-filters/implementation46-capture-flow-final-v2/verification.json`；复核脚本`.local/implementation46-final-audit/audit_final.py`。原生构建`.local/implementation46-final-native-v4/`；EVF四份审计`.local/implementation46-evf-flow/v3/`；普通Capture／共用入口审计`.local/implementation46-jpg-flow/`。较早的v1/v2回执属于各自历史代码状态。

整体仍为`NOT_VERIFIED`；没有可安装固件或像素验收声明。原厂分组更新／失败回退保持，允许既定的暂时新旧组件混用，不额外保证整配方原子切换。其他基底完整颜色域、实际机内文件／掉电及设备验收继续保留各自边界。
