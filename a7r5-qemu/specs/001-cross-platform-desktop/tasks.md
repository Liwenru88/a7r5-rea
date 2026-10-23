# 任务清单：跨平台客户端与相机输入

## 阅读摘要

**M1、M2（T001—T009）已实施并完成限定范围验收。** 交付独立 Mac 客户端、显式网页回退和 35 项控制清单；仅启用六键菜单与 C4 菜单帮助，其他 28 项禁用。M3 的 T010—T012 未实施。

实际命令、失败与修复、截图和功能限制见 `verification.md`。

## 元信息 Metadata

- Feature ID: `001-cross-platform-desktop`
- Status: `M1-M2-verified; M3-not-run`
- Related requirements: `requirements.md`
- Related design: `design.md`
- Created: `2026-10-19`
- Updated: `2026-10-19`
- Requested stopping point: `M1 M2 implementation and verification`

## M1：先交付可用桌面客户端

- [x] **T001：固定基线并验证 GUI 依赖组合**
  - 完成条件：记录当前运行输入和关键代码摘要；核对 PySide6 与 Python 3.14、macOS arm64 的兼容性，锁定桌面依赖。依赖只进入项目环境，不覆盖 Python，不安装与客户端无关的 Qt 模块。打包工具单独记录版本，历史通过记录和本次待执行验证分开。
  - _Requirements: REQ-001, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-007-02, AC-REQ-008-01_
  - _Verification: V-007, V-008；安装前后清单、最小 Qt 窗口与依赖导入，后续复用同一基线_
  - _Depends: none_
  - _Boundary: 项目内依赖与基线；原始镜像、相机和 SD 卡完全排除_

- [x] **T002：抽出共用会话控制，保留网页适配器**
  - 完成条件：`EmulatorSession` 不依赖 HTTP/Qt，统一拥有 worker、在途请求、状态、取消和退出回执。命令仍限固定工作流和六键；网页入口调用同一控制层。补充启动中关闭、忙时退出、重复请求、超时、进程异常、锁占用等独立失败结果的回归。
  - _Requirements: REQ-002, REQ-003, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-003-01, AC-REQ-007-01, AC-REQ-008-02_
  - _Verification: V-002, V-005；复用/调整现有 HTTP 契约测试；实际 Qt 行为留到 T004 同批验收_
  - _Depends: T001_
  - _Boundary: tools/emu_session.py、现有入口和 bridge 的必要接线；不重写已验证固件初始化链_

- [x] **T003：明确资源路径和平台能力边界**
  - 完成条件：共用模块能在不导入 macOS/POSIX 专用实现的情况下探测能力；首期只启动现有 Mac 后端。分离资源根与数据目录；输入、bridge 和输出路径均有限定。其他平台输出明确未支持状态，不能绕过隔离。Mac 沙箱、锁、QMP 和拥有的进程回收行为保持。
  - _Requirements: REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-006-01, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-008-01_
  - _Verification: V-005, V-007；不支持平台、缺二进制/隔离、路径越界/符号链接和摘要失败的参数化拒绝测试，以及真实 Mac 沙箱检查_
  - _Depends: T002_
  - _Boundary: tools/platform_backend.py、tools/app_paths.py 及 Mac 实现的定向拆分；不实现 Linux/Windows 运行_

- [x] **T004：实现 Qt 窗口并验收现有六键**
  - 完成条件：独立窗口显示真实菜单帧、保持比例，提供六键按钮、快捷键和状态；后台操作不阻塞窗口。关闭窗口等待真正的 QMP/进程结束，异常时可查看收据。先保留独立新入口，不提前替换默认入口。
  - 阶段门槛：真实窗口操作；四轮 MENU 开关和六键基线比对；原始帧/PNG 校验；空闲暂停；正常与启动失败/关闭路径。用一个端到端批次承载共同证据，不为每个按钮重复启动虚拟器。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-007_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-007-02_
  - _Verification: V-001, V-002, V-007；产出新的 Qt 窗口截图、原始帧和退出收据；复用 T002/T003 未失效的拒绝测试_
  - _Depends: T002, T003_
  - _Boundary: client/、桌面验收适配；不启用候选键、不更改客体归档_

- [x] **T005：实现目录式 `.app` 与冻结 worker 启动**
  - 完成条件：打包后父进程/worker 不依赖 `.venv` 和源码绝对路径，资源根与可写目录正确；必要 Qt/Python/QEMU 动态库可定位，资源清单只携带一份固件归档。记录重定位后的 QEMU 候选摘要并保留开发版本。
  - 阶段门槛：从其他工作目录、含空格路径双击；包内 worker 真正启动 QEMU、显示原厂菜单并正常退出；实际运行不读取开发 `.venv` 或 Homebrew 库。缺依赖、只读资源目录、不能创建运行目录时可解释地停止。只有开发启动器时该任务不算完成。
  - _Requirements: REQ-001, REQ-002, REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-002-02, AC-REQ-006-01, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-008-01_
  - _Verification: V-008, V-005, V-007；包内依赖审计、真实打包程序的启动/帧/退出；未改变的导航逻辑复用 T004 证据_
  - _Depends: T004_
  - _Boundary: client/main.py、packaging/、包内程序/库和资源清单；不放宽为无沙箱运行，不复制原始分区镜像_

- [x] **T006：切换默认入口并交付 M1**
  - 完成条件：T004/T005 通过后默认入口启动客户端；显式网页回退保留且不自动切换。更新使用说明、平台支持状态、操作边界和真实 `verification.md`，附依赖/输入摘要与截图；用户能直接找到 `.app` 和退出方法。
  - 阶段门槛：完成一次网页启动、一帧、退出的回退冒烟；复用仍有效的 Qt 与包验收，不重复整套导航。未通过任何必需项就保留新客户端为候选，不切换默认入口。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-002-01, AC-REQ-002-02, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-006-01, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-008-01, AC-REQ-008-02_
  - _Verification: V-001, V-002, V-005, V-007, V-008；引用已有同版本证据，补回退和默认入口的独立检查_
  - _Depends: T005_
  - _Boundary: 启动入口、AGENTS.md、README.md、平台状态和验收记录；不删除旧研究与历史证据_

## M2：完整控制面板与分批按键适配

本阶段已获用户授权，M1 验收后继续执行。若该阶段需要新增客体模拟文件，先按候选与归档差异门槛推进；不会自动修改原厂应用和内核。

- [x] **T007：建立 A7R5 完整控制注册表与面板**
  - 完成条件：官方机身控制逐项入表，记录实体标签、交互类型、映射来源、行为状态和上下文；完整面板可显示尚未验证的控制并解释禁用原因。准确区分 C4/删除、自定义键、控制轮、前/后拨轮、摇杆与机械操作。
  - _Requirements: REQ-004, REQ-007_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-02, AC-REQ-007-01_
  - _Verification: V-003, V-005；官方布局对照、注册表 schema 和未验证项不能进入注入层的契约测试_
  - _Depends: T006_
  - _Boundary: config/controls.json、tools/input_registry.py、client/control_panel.py；不启用只有标签的事件_

- [x] **T008：扩展输入语义与释放状态管理**
  - 完成条件：针对已有证据的动作实现需要的 tap/press/release/rotate/select 等语义及严格参数验证；界面失焦、取消、退出或传输失败时不会留下未核对的按下状态。状态选择与快门两段不套用方向键格式。
  - _Requirements: REQ-002, REQ-004, REQ-005, REQ-007_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-004-02, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-007-01_
  - _Verification: V-002, V-003, V-004；已按下、已释放、重复、超时和失焦等独立结果用参数化状态机测试；真实消息语义由 T009 证明_
  - _Depends: T007_
  - _Boundary: 结构化控制协议和释放状态；不开放任意键码编辑或任意 shell_

- [x] **T009：按证据分批适配更多实体控制**
  - 完成条件：先审查已有 C4/删除与拨轮候选，再选择有证据的 Fn、播放、自定义键等；每批记录具体控制、固件映射、场景、预期与停止条件。每个启用项有真实接收/分发与响应证据；失败或硬件受限项记录原因并保持禁用。
  - 快门、录像、AF-ON、状态选择器和触控仅在各自证据齐备后进入相应子批次；不把事件发送成功标为对焦/拍摄/录像成功。遇异常不遍历未知值、不自动重试。
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-005, REQ-007_
  - _Acceptance: AC-REQ-002-02, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-007-01, AC-REQ-007-02_
  - _Verification: V-004, V-002, V-003, V-007；改动共享导航链时补受影响 V-001；每批提交输入、场景响应、释放和退出收据_
  - _Depends: T008_
  - _Boundary: 本批明确控制和必要模拟载荷；超出模拟库或引入新硬件服务须更新设计、说明风险后再执行_

## M3：逐平台原生后端与交付

以下任务为延期路线，前置条件是对应测试环境和实施授权。没有实际主机的任务保持 `NOT_RUN`，不阻塞已完成的 Mac 客户端交付。

- [ ] **T010：验证 Linux 原生后端**
  - 前置条件：明确 Linux 发行版/版本、CPU 架构和可用测试主机；同步项目规则允许该平台模拟。
  - 完成条件：固定源码原生构建、运行输入校验、锁、QMP、拥有进程管理和可实测的文件/网络隔离通过；真实 root、菜单、六键、暂停和正常退出通过，再记录支持状态。
  - _Requirements: REQ-002, REQ-003, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-007-01, AC-REQ-007-02_
  - _Verification: V-006, V-005, V-007；Linux 真正运行与隔离证据，不能以 Mac 上模拟 sys.platform 的测试替代_
  - _Depends: T006_
  - _Boundary: Linux 后端、构建/清单和隔离策略；不恢复 Docker，不读取物理设备，不弱化 Mac 隔离_

- [ ] **T011：验证 Windows 原生后端**
  - 前置条件：明确 Windows 版本/架构与测试主机；同步项目规则；先证明所选文件/网络隔离可满足门槛。
  - 完成条件：解决原生 QEMU 产物、非 POSIX 锁、进程所有权/回收、QMP 传输与隔离；真实 root、菜单、六键和退出通过。隔离方案不能满足时保留未支持，产出明确阻塞结论。
  - _Requirements: REQ-002, REQ-003, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-007-01, AC-REQ-007-02_
  - _Verification: V-006, V-005, V-007；Windows 实际运行、拒绝访问和退出证据；Job Object 回收不能代替完整隔离验收_
  - _Depends: T006_
  - _Boundary: Windows 专用后端与已论证的隔离实现；不移除拒绝门槛，不将 WSL/容器结果标为原生 Windows 通过_

- [ ] **T012：各平台应用包与支持矩阵**
  - 完成条件：只对 T010/T011 已通过的平台各自构建应用包，验证冻结 worker、资源定位、原生库、真实帧和退出；更新每个平台/架构的独立收据和未验证项。Mac 包不能复用为其他系统的安装产物。
  - _Requirements: REQ-001, REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-007-01, AC-REQ-008-01, AC-REQ-008-02_
  - _Verification: V-006, V-008；每个平台分别验收包与原生后端，共享与其相同版本的有效导航证据_
  - _Depends: T005；Linux 子包依赖 T010，Windows 子包依赖 T011，二者分别完成，不互相等待_
  - _Boundary: 已验收平台的打包、依赖、许可证和使用/支持文档；不包含公网发布或证书账号配置_

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
| --- | --- | --- | --- |
| REQ-001 | AC-REQ-001-01, AC-REQ-001-02 | T001, T004, T005, T006, T012 | V-001, V-008 |
| REQ-002 | AC-REQ-002-01, AC-REQ-002-02 | T002, T004, T006, T008, T009, T010, T011 | V-002 |
| REQ-003 | AC-REQ-003-01, AC-REQ-003-02 | T002, T004, T006, T009, T010, T011 | V-001 |
| REQ-004 | AC-REQ-004-01, AC-REQ-004-02 | T007, T008, T009 | V-003 |
| REQ-005 | AC-REQ-005-01, AC-REQ-005-02 | T008, T009 | V-004, V-002 |
| REQ-006 | AC-REQ-006-01, AC-REQ-006-02 | T003, T006, T010, T011, T012 | V-005, V-006 |
| REQ-007 | AC-REQ-007-01, AC-REQ-007-02 | T001, T002, T003, T004, T005, T006, T007, T008, T009, T010, T011, T012 | V-005, V-007 |
| REQ-008 | AC-REQ-008-01, AC-REQ-008-02 | T001, T002, T003, T005, T006, T012 | V-008 |

## 任务质量门与实施记录

- [x] 每项实施任务有需求、验收、验证、依赖和边界，验收标准无遗漏。
- [x] 阶段按可观察结果拆分，联合验证复用证据，没有单独堆砌重复跑命令的任务。
- [x] 本次按用户授权执行 T001—T009；M3 保持未实施。
- [x] 实施中才创建 `verification.md` 记录实际命令和 `PASS/FAIL/NOT_RUN`；本轮不生成虚假的通过记录。
- [x] T001—T009 的实际证据已记录；未验证的按键/硬件能力不因任务完成而启用。
