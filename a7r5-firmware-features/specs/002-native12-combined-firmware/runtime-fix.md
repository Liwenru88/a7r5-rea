# 验证来源清单遗漏C服务的修复

范围：本次离线验证基础设施。没有修改固件逻辑、固定上游或已交付DAT。

复现：在`test_build_source_receipt_excludes_archives_and_generated_work`的临时模块中加入`tests/runtime_case.c`，要求实施源清单包含它。修复前执行该定向回归，实际结果为`1 failed`：期望7份来源，实际只有6份。

原因：`build.py:implementation_sources()`原先只搜索`tests/*.py`。新增宿主C服务是回放的实际输入，漏记会使回执无法区分不同的外部服务实现。

修复：仍限定在本模块`tests/`直接目录，收录`.py`及`.c`普通文件；仍排除上游、交付归档及构建中间件，不放宽固定上游来源锁。现有来源清单回归同时检查C收录和归档排除。

验证：修复后的全部离线回归见`native12-combined/verification/2026-11-02-runtime/final-regression.xml`。当前回执绑定三份C服务和全部Python回放源，旧冻结回执保留。

本轮多次测试装配错误也已纠正：兼容源码别名重复链接、ARM第5参数栈位置、指令预算、32位返回值的高位、字符串缓冲尾部及不符合真实银行身份变化的测试替身。它们不是相机固件缺陷，不能记作固件功能修复。最终以当前源的集中回归为准。
