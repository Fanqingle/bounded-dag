# bounded-dag

## 项目概述

输入是一份 JSON 描述的作业图：声明若干步骤、步骤之间的依赖关系，以及每个步骤要调用的模拟工具；输出是每步结果与一条按时间排序的事件流，前端据此还原各步骤从排队到终态的完整时间线，状态取值限定为 PENDING、RUNNING、SUCCEEDED、FAILED、SKIPPED、CANCELLED。执行器要保证的核心不变式只有一条：任意时刻处于 RUNNING 的步骤数不超过全局上限 N，且一个步骤只有在依赖策略判定其前置条件已满足时才可能进入 RUNNING，否则留在 PENDING 或被置为 SKIPPED。在此之上，每步带超时与重试，失败后按依赖策略让下游继续、降级或跳过，并支持对整次运行发出取消信号。所有工具都是模拟实现，不调用任何真实模型。

## 目录结构

仓库当前包含以下目录与文件。

- `src/`：放置执行器实现。`models.py` 定义 StepSpec、Plan、ToolConfig、RunRequest 数据模型；`validation.py` 提供结构化校验与错误码；`events.py` 实现 append-only 事件日志与可注入时钟；`tools.py` 实现 search / summarize / generate_image 三个模拟工具；`scheduler.py` 实现有并发上限、重试与取消的 DAG 执行器；`api.py` 提供 FastAPI 端点与 SSE 重放。
- `tests/`：放置不变式测试。`conftest.py` 提供 FakeClock、GatedClock、BarrierClock 与确定性 rng；`test_scheduler.py` 锁定并发上限、重试、失败传播与取消行为；`test_validation.py` 锁定校验错误码与环路径。
- `frontend/`：放置消费事件流并绘制时间线的界面，纯 TypeScript、不依赖 UI 框架。`index.html` 为页面骨架；`src/main.ts` 处理请求、EventSource 与重连补快照；`src/timeline.ts` 提供 parseRows 与 concurrentSeries 纯函数；`package.json`、`tsconfig.json`、`vite.config.ts` 为构建配置。
- `docs/`：放置设计说明与决策记录。`design.md` 记录状态转移、并发不变式、失败传播、事件清单与校验错误码；`docs/adr/` 包含 6 条 ADR（调度器形态、事件日志优先、退避释放槽位、失败传播声明式、可注入时钟、缓存仅单次运行内）与 `INDEX.md`。
- `ai-logs/`：放置完整会话与工具调用记录。`README.md` 说明工具、模型与导出方式；`workbuddy/session-d9d8d2a9.jsonl` 为原生会话 trace；`usage-heatmap/generate_heatmap.py` 为热力图生成脚本；`usage-heatmap/usage-heatmap.png` 为用量热力图。

## 阅读顺序

1. 本 README：了解输入输出、目录布局与启动方式。
2. `docs/design.md`：了解规格与不变式，包括状态转移、失败传播与事件清单。
3. `docs/adr/INDEX.md`：了解 6 条取舍及其触发条件。
4. `src/scheduler.py`：了解核心执行器的调度、重试与取消实现。
5. `tests/`：了解不变式如何被锁住。

演示页面见 `frontend/`，AI 记录见 `ai-logs/`。

## 快速开始

前置条件：Python 3.11+；Node.js 18+ 与 npm（仅构建前端时需要）。

一条命令启动：`python run.py`。该命令会自动安装前端依赖（当 `frontend/node_modules` 不存在时执行 `npm install --no-audit --no-fund`）并构建前端，然后同时提供 API 与静态页面；若 `frontend/` 目录不存在则跳过静态挂载，只提供 API。

- 启动：`python run.py`
- 测试：`pytest -q`

## 验证

执行 `pytest -q` 应输出 `14 passed`。`python run.py` 启动后，SSE 事件流与静态页面由 `http://127.0.0.1:8000` 提供。

## 关键决策

决策记录放在 `docs/adr/`。第一条：每个非显然取舍会在链路上留痕。后续每条记录说明取舍内容、理由与影响范围。

## AI 工具与假设

本项目使用 AI 辅助。策略与设计讨论使用 WorkBuddy；编码与文件编辑使用 WorkBuddy 内置工具，版本控制使用 Git CLI。完整会话与工具调用记录放在 `ai-logs/`，用量热力图放在 `ai-logs/usage-heatmap/`。

已落地的关键规格：
- 当前仓库根目录为本目录，首个提交只包含 README。
- 状态集固定为 PENDING、RUNNING、SUCCEEDED、FAILED、SKIPPED、CANCELLED；重试退避期间步骤回到 PENDING。
- 运行终态为 SUCCEEDED / FAILED / PARTIAL / CANCELLED 四值，取消不写失败降级话术。
- `n` 缺省为 2，由 POST body 覆盖；任意时刻 RUNNING 步骤数不超过 n。
- `docs/adr/` 归入 `docs/`；AI 记录目录为 `ai-logs/` 与 `ai-logs/usage-heatmap/`。
