# 八项相对偏移离线证据

功能和复现命令见[相对偏移说明](../../相对偏移调参说明.md)。本目录记录当前源码生成的离线组件和 CPU 验证，不是升级包或实体机验收。

| 文件 | 用途 |
|---|---|
| `verification.json` | 本轮结论、组件摘要、实际回归数量和边界 |
| `build.json`、`rebuild.json` | 独立构建、工具链、源码及组件身份 |
| `runtime-regression.json`、`runtime-regression.xml` | 最终相关回归、运行期间源码不变检查 |
| `relative-*.json` | 相对偏移用例的 AP／CP、文件字节和状态轨迹 |
| `parity-proof.json` | 上游四种状态、十二款各九条消息的逐字节比对 |
| `before-build.json`、`zero-default-before.xml` | 上轮 AP `69bbc280…` 仍显示 4／3／1 的预期失败 |
| `signed-format-before-build.json`、`signed-format-before.xml` | 中间 AP `a83e98d7…` 遗漏原生活动数值格式入口的预期失败 |
| `SHA256SUMS` | 本目录证据摘要，校验命令为 `shasum -a 256 -c SHA256SUMS` |

上游探针复用[冻结脚本](../upstream-parameters/probe.py)，其源码摘要由本轮验证记录绑定。旧上游核对目录保持原清单，不使用其旧回归结果替代本轮结果。

CPU 回放执行实际 AP／CP 和原生数值更新代码；外部文件、时钟、队列、对象及 UI 服务为明确夹具。没有连接相机、运行 QEMU／Qt 或生成新 DAT，没有验证实体机 LCD／EVF／JPG 像素及真实介质掉电。13～24 槽仍以合成数据验证容量；正式十二款配方保持原字节。
