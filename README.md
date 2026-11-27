# bounded-dag

## 项目概述

输入是一份 JSON 描述的作业图：声明若干步骤、步骤之间的依赖关系，以及每个步骤要调用的模拟工具；输出是每步结果与一条按时间排序的事件流，前端据此还原各步骤从排队到终态的完整时间线，状态取值限定为 PENDING、RUNNING、SUCCEEDED、FAILED、SKIPPED、CANCELLED。执行器要保证的核心不变式只有一条：任意时刻处于 RUNNING 的步骤数不超过全局上限 N，且一个步骤只有在依赖策略判定其前置条件已满足时才可能进入 RUNNING，否则留在 PENDING 或被置为 SKIPPED。在此之上，每步带超时与重试，失败后按依赖策略让下游继续、降级或跳过，并支持对整次运行发出取消信号。所有工具都是模拟实现，不调用任何真实模型。

## 目录结构

以下目录均为计划中的安排，目前尚未创建；仓库当前只有本 README。

- `src/`：计划放置 JSON 解析、依赖调度、全局并发限制、超时与重试、失败策略、取消信号和事件流输出的实现。
- `tests/`：计划放置调度不变式、状态迁移、失败策略分支与取消行为的测试。
- `frontend/`：计划放置消费事件流并绘制时间线的界面。
- `docs/`：计划放置设计说明与 `docs/adr/` 决策记录。
- `ai-logs/`：计划放置完整会话与工具调用记录；用量热力图放在 `ai-logs/usage-heatmap/`。

## 快速开始

前置条件：Python 3.11+；Node.js 18+ 与 npm（仅构建前端时需要）。

一条命令启动：`python run.py`。该命令会自动安装前端依赖（当 `frontend/node_modules` 不存在时执行 `npm install --no-audit --no-fund`）并构建前端，然后同时提供 API 与静态页面；若 `frontend/` 目录不存在则跳过静态挂载，只提供 API。

- 启动：`python run.py`
- 测试：`pytest -q`

## 关键决策

决策记录计划放在 `docs/adr/`（尚未创建）。第一条：每个非显然取舍会在链路上留痕。后续每条记录说明取舍内容、理由与影响范围。

## AI 工具与假设

本项目使用 AI 辅助。策略与设计讨论使用 WorkBuddy；编码与文件编辑使用 WorkBuddy 内置工具，版本控制使用 Git CLI。完整会话与工具调用记录放在 `ai-logs/`，用量热力图放在 `ai-logs/usage-heatmap/`；这两个目录目前尚未创建。

沿用上一轮确认的关键假设：
- 当前仓库根目录为本目录，首个提交只包含 README。
- 状态集固定为 PENDING、RUNNING、SUCCEEDED、FAILED、SKIPPED、CANCELLED；重试退避期间步骤回到 PENDING。
- 运行终态为 SUCCEEDED / FAILED / PARTIAL / CANCELLED 四值，取消不写失败降级话术。
- `n` 缺省为 2，由 POST body 覆盖；任意时刻 RUNNING 步骤数不超过 n。
- `python run.py` 与 `pytest -q` 为目标命令，实现完成后可用。
- `docs/adr/` 归入 `docs/`；AI 记录目录为 `ai-logs/` 与 `ai-logs/usage-heatmap/`。
