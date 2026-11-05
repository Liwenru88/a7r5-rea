# 本阶段任务

- [x] T001 独立派生与编译布局原型，核对十二槽前像及二十四槽容量／区域隔离。
  宿主／ARM32／AArch64一致，12槽522152、24槽947000字节；目标执行哨兵与全部24个视图Gamma指针读取通过。
  _Requirements: REQ-001, REQ-004_
  _Acceptance: AC-001, AC-004_
  _Verification: V2 宿主执行、ARM32／AArch64编译常量、槽写入哨兵和来源收据_
  _Boundary: 不改现有固件／上游；不把布局原型当作CP运行时_
- [x] T002 派生候选配方／选择编解码，建立旧新格式与损坏拒绝的交叉测试。
  旧BIN重编码原样、完整／稀疏新格式、损坏拒绝保留输出及0～24号选择格式交叉验证通过；新增槽仅为合成测试输入。
  _Requirements: REQ-002, REQ-003_
  _Acceptance: AC-002, AC-003_
  _Verification: V2 原解码器／派生C／独立Python文件构造器，原子拒绝和旧字节保持_
  _Depends: T001 的来源校验／编译支持_
  _Boundary: 仅独立研究格式，不迁移用户文件，不接AP／CP传输_
- [x] T003 归档命令、结果和身份，给出是否能进入运行时扩容阶段的依据及限制。
  最终15项测试通过，来源／目标对象／XML／身份和下一阶段门禁独立归档；没有24槽运行时或新固件。
  _Requirements: REQ-004, REQ-001, REQ-002, REQ-003_
  _Acceptance: AC-004, AC-001, AC-002, AC-003_
  _Verification: V0/V2 XML、摘要、链接及待实现门禁；复用同源成功证据_
  _Depends: T001, T002_
  _Boundary: 无24槽升级包、无相机I/O，下一阶段实现不在本阶段内_
