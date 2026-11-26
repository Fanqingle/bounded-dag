# 编排设计

## 1. 六个步骤状态与合法转移

步骤状态只使用 PENDING、RUNNING、SUCCEEDED、FAILED、SKIPPED、CANCELLED。

| 当前状态 | 目标状态 | 触发条件 | 不这样会怎样 |
| --- | --- | --- | --- |
| PENDING | RUNNING | deps_policy 判定通过，且本次尝试获得一个并发槽位 | 无法表达“依赖满足才启动”，并发上限同时失效 |
| PENDING | SKIPPED | deps_policy 判定不通过，或上游 SKIPPED 沿后代传到本步 | 只跳一层会让孙步骤卡在 PENDING，运行无法收束 |
| RUNNING | SUCCEEDED | 本次尝试的模拟工具成功返回 | 成功没有终态，前端时间线断在 RUNNING |
| RUNNING | PENDING | 本次尝试失败且仍有剩余尝试；槽位已释放，进入退避 | 退避占槽会把 RUNNING 推过 n，违反不变式 |
| RUNNING | FAILED | max_attempts 用尽后本次尝试仍失败 | 失败步骤停在 RUNNING，无法触发运行终态判定 |
| RUNNING | CANCELLED | 收到取消信号，协作式立即终止，不再重试 | 取消后仍有步骤在跑，终态无法是 CANCELLED |
| PENDING | CANCELLED | 收到取消信号，尚未启动的步骤不再启动 | 取消后仍有步骤被调度，步骤状态与运行终态互相矛盾 |

终态 SUCCEEDED / FAILED / SKIPPED / CANCELLED 不再有任何合法后继。
不这样会怎样：已结束步骤会被重复调度，事件流与快照互相矛盾。

## 2. 并发不变式与唯一占槽点

- 任意时刻处于 RUNNING 的步骤数不超过 n；n 缺省为 2，由 POST body 的 n 覆盖。
不这样会怎样：无上限并发会瞬间挤满模拟工具的调度资源，时间线失去可读性。

- 唯一占槽点位于“获得信号量 → 置 RUNNING → 发出 step_started”这一处；每次尝试（含重试）都从这里进入。
不这样会怎样：多入口 acquire 会造成重复占槽或漏 release，RUNNING 数超过 n。

- release 写在每次尝试的 finally 中，成功、失败、取消三条路径都释放。
不这样会怎样：异常路径漏释放会永久占用槽位，剩余步骤全部饿死。

- 退避等待发生在 release 之后、下一次 acquire 之前；退避期间步骤状态为 PENDING，不持有槽位。
不这样会怎样：把退避算作 RUNNING 会让不工作的步骤占着槽位，直接违反不变式。

## 3. deps_policy 与 required 的正交语义表

deps_policy 只统计依赖步骤中 SUCCEEDED 的数量：all 要求全部依赖 SUCCEEDED；any 要求至少一个依赖 SUCCEEDED；quorum:k 要求至少 k 个依赖 SUCCEEDED。FAILED、SKIPPED、CANCELLED 均不计入。

| deps_policy 判定 | required | 步骤行为 | 对运行终态的影响 | 不这样会怎样 |
| --- | --- | --- | --- | --- |
| 满足 | true | 可启动；终态可为 SUCCEEDED / FAILED / CANCELLED | 若 FAILED，运行终态为 FAILED | 把 required 当调度条件会让非必需步骤也被挡住 |
| 满足 | false | 可启动；终态可为 SUCCEEDED / FAILED / CANCELLED | 若 FAILED 且必需步骤全 SUCCEEDED，运行终态为 PARTIAL | 非必需失败直接判 FAILED 会让 PARTIAL 永不出现 |
| 不满足 | true | 置 SKIPPED，并沿所有后代传递 | 运行终态为 FAILED | 只跳一层会让后代停在 PENDING，运行无法结束 |
| 不满足 | false | 置 SKIPPED，并沿所有后代传递 | 必需步骤全 SUCCEEDED 时运行终态为 PARTIAL | 非必需跳过也判 FAILED 会与 PARTIAL 定义冲突 |

required 只影响运行终态与 final_text，不改变步骤的调度资格。
不这样会怎样：必需与非必需在调度阶段被混为一谈，PARTIAL 无法产生。

PARTIAL 的 final_text 逐项说明未成功的非必需步骤，例如「竞品 C 的资料未查到，以下对比仅含 A、B。」；必需步骤失败时 final_text 指向失败步骤，例如「关键步骤 summarize 未能完成，本次未生成海报。」
不这样会怎样：前端只能给出通用错误，用户无法区分内容缺失与任务失败。

CANCELLED 不写失败降级话术，final_text 仅标记取消。
不这样会怎样：取消被误读为内容降级，误导前端展示。

## 4. 四个运行终态的判定规则

取消信号的判定优先于其余三条规则。
不这样会怎样：取消与失败同时出现时终态不确定，快照与事件流会分歧。

| 运行终态 | 判定条件 | final_text | 不这样会怎样 |
| --- | --- | --- | --- |
| SUCCEEDED | 全部步骤 SUCCEEDED | 正常汇总文本 | 无法区分“全成功”与“部分缺失” |
| FAILED | 任一 required 步骤 FAILED 或 SKIPPED | 「关键步骤 summarize 未能完成，本次未生成海报。」 | 关键缺失被当成 PARTIAL，输出不完整内容 |
| PARTIAL | 有非必需步骤 FAILED / SKIPPED，且所有必需步骤 SUCCEEDED | 「竞品 C 的资料未查到，以下对比仅含 A、B。」 | 非关键缺失导致整次运行失败，浪费已完成结果 |
| CANCELLED | 收到取消信号 | 仅标记取消，不写降级话术 | 取消被混入失败统计，污染运行指标 |

## 5. 事件流

- append-only 事件字段固定：seq（单调递增长整数）、ts（毫秒）、type、run_id、step_id（可空）、attempt（可空）、payload。
不这样会怎样：字段漂移会让 SSE 客户端与快照解析器各自兼容，重放结果不一致。

- 事件类型仅使用 run_started / step_queued / step_started / step_retry_scheduled / step_succeeded / step_failed / step_skipped / run_finished。
不这样会怎样：新增类型会迫使前端分支膨胀，时间线语义失控。

- step_queued 在步骤进入就绪队列时发出；step_started 在获得槽位后发出，携带 attempt。
不这样会怎样：排队与执行无法区分，时间线无法解释并发等待。

- step_retry_scheduled 在槽位释放后发出，payload 含退避时长与下一次 attempt；只有 max_attempts 用尽才发 step_failed。
不这样会怎样：把重试当最终失败会提前终止运行，把重试当成功会掩盖错误。

- SSE 端点 GET /api/runs/{id}/events，每条事件 id: <seq>，支持 Last-Event-ID 从指定序号重放；响应头带 Cache-Control: no-cache 与 X-Accel-Buffering: no。
不这样会怎样：代理缓冲或断线重连丢事件，前端时间线出现空洞。

- GET /api/runs/{id} 返回快照，供刷新与重连兜底；客户端断开不影响运行。
不这样会怎样：刷新后无状态可恢复，或前端关闭导致运行被误杀。

## 6. 校验规则与错误码

| 错误码 | 触发规则 | 输出要求 | 不这样会怎样 |
| --- | --- | --- | --- |
| duplicate_step_id | 两个 StepSpec.id 相同 | 返回重复的 id | 无法定位重复定义，执行时步骤被覆盖 |
| self_dependency | depends_on 包含本步 id | 返回该步骤 id | 自环会进入死锁或无限重试 |
| missing_dependency | depends_on 引用不存在的步骤 id | 返回缺失 id 与所属步骤 | 依赖永远无法满足，步骤卡在 PENDING |
| unknown_tool | tool 不在 search / summarize / generate_image 中，或 tools 缺少对应 ToolConfig | 返回工具名 | 执行期才失败，破坏提交前的可预测性 |
| cycle_detected | 依赖图存在环 | 输出具体路径，例如 s1→s2→s3→s1 | 只报“有环”无法定位修复点 |

校验按 duplicate_step_id → self_dependency → missing_dependency → unknown_tool → cycle_detected 的顺序返回首个错误。
不这样会怎样：多个错误并存时返回不稳定，客户端难以复现。
