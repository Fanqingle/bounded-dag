# AI 会话与工具调用记录

本题全部 AI 对话发生在单个 WorkBuddy 会话中，会话 ID 为 `d9d8d2a9-8cd8-42c1-b093-39e891c2add9`。

## 1. 使用的工具与模型

- WorkBuddy：本题全程使用，覆盖策略与设计讨论、规格裁决落地、源码与文档编写、测试执行与提交整理。
- 本机 Git CLI：版本控制操作（init / add / commit / push）。
- 模型：WorkBuddy default model。本机 `workbuddy.db` 的 `sessions` 表将该会话的模型标识记录为 `hy4flash-free`。

除上述工具外，本题未使用其它 AI 编码工具。

## 2. 文件与导出方式

- `ai-logs/workbuddy/session-d9d8d2a9.jsonl`：WorkBuddy 会话的原生 JSONL trace，从 WorkBuddy 会话目录原样复制。文件包含 `message`、`function_call`、`function_call_result`、`reasoning`、`file-history-snapshot` 等记录类型，未经格式化、截断或摘要；唯一允许的编辑是密钥打码。本次对 `sk-`、`token`、`password`、`api_key`、`Bearer` 等模式做了全文扫描，未发现命中，因此复制前后逐字节一致。

## 3. 会话与提交的对应关系

按时间顺序，本题已完成的 12 次提交与对应对话内容如下：

1. `0c3ffca` add project overview and run instructions：建立首个 README，确定项目概述、目录结构、目标命令与 AI 记录约定。
2. `865a009` add orchestration design doc：把状态转移、并发不变式、失败传播、事件清单与校验错误码写成设计文档。
3. `7e0be8d` add architecture decision records：记录调度器形态、事件日志优先、退避释放槽位等六条决策与 README 的工具小节。
4. `075cb9a` add plan schema and validation：落地 StepSpec / Plan / ToolConfig / RunRequest 与结构化校验。
5. `0651857` add bounded dag scheduler with retry and cancellation：实现事件日志、模拟工具与有并发上限的 DAG 执行器。
6. `5441f40` add orchestration tests：补充调度与校验测试，并加入忽略规则。
7. `71e61f4` fix deterministic timeout and event gaps：改为注入时钟判定超时，补齐 `step_queued` 与 `step_cancelled`，记录 `next_attempt_at`。
8. `7611840` add http api and sse replay：提供 FastAPI 端点、SSE 重放与快照，加入 `run.py` 和依赖清单。
9. `9016b9f` extend tests for timeout events and snapshot：新增超时重试、排队事件、快照回环与部分成功话术测试。
10. `ae51ee4` make concurrency tests deterministic：注入门闩时钟、确定性 rng 与屏障时钟，消除测试对调度顺序和随机数的依赖。
11. `8a140ee` fix example plan to match demo script：把示例规划改为标准五步配置，由调试面板调高失败率触发 PARTIAL。
12. `b84fb44` add timeline and debug panel ui：加入纯 TypeScript 前端，提供并发折线、时间线、事件流水与调试面板。

本次收尾包含三次提交：先让干净克隆可直接运行（`4239cd7`），再归档完整会话 trace，最后生成本地用量热力图。上述第 12 次提交之后的对话段落对应本次收尾。

## 4. 无法导出工具调用的工具

本题未使用此类工具。Claude Code 本机无本题历史会话，因此没有对应记录可导出。
