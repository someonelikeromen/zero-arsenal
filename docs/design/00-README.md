# 零度武库 (ZeroArsenal) — 设计文档索引

> AI 跑团小说统合工具设计文档集  
> 本目录为唯一的需求与架构权威来源，所有实现以此为准。

---

## 文档列表

| 文档 | 内容摘要 |
|------|---------|
| [01-project-analysis.md](./01-project-analysis.md) | 六项目优缺点对比、能力矩阵、统合策略与风险 |
| [02-system-architecture.md](./02-system-architecture.md) | 总体分层架构、核心回合时序、项目目录结构、技术栈汇总 |
| [03-agent-system.md](./03-agent-system.md) | 三层 Agent 架构、LangGraph 图设计、各 Agent 职责、NarratorAgent 四阶段管线 |
| [04-extension-system.md](./04-extension-system.md) | 八类扩展点、Hook 全览、发现机制、内置扩展目录结构 |
| [05-prompt-architecture.md](./05-prompt-architecture.md) | PromptFragment Registry、五层提示词架构、SKILL.md 格式规范、Phase 过滤 |
| [06-data-model.md](./06-data-model.md) | Session/Message/Part Schema、角色卡 v4、章节树、记忆表、骰子日志 |
| [07-tool-registry.md](./07-tool-registry.md) | ToolDef 接口、工具执行链、内置工具清单、MCP 桥接、权限矩阵 |
| [08-memory-system.md](./08-memory-system.md) | 四层混合召回、viewer_agent 视角、固化流水线、回滚机制 |
| [09-event-bus-sse.md](./09-event-bus-sse.md) | Bus 接口、BusEvent 类型、SSE 端点实现、前端 SSE 客户端 |
| [10-permission-modes.md](./10-permission-modes.md) | AgentProfile 结构、三种内置模式、权限匹配算法、ask 交互流程 |
| [11-api-design.md](./11-api-design.md) | REST + SSE 端点全览、请求响应示例、错误码规范 |
| [12-frontend-architecture.md](./12-frontend-architecture.md) | React 布局、Zustand 切片、Part 渲染器、SSE 客户端、骰子面板 |

---

## 参考来源速查

| 设计思路 | 来源项目 | 关键文件 |
|---------|---------|---------|
| 四阶段叙事管线（P1-P4） | ai-vn-game-system | `src/engine/gameLoop.js`, `promptBuilder.js` |
| LangGraph 多 Agent 图 | ai-vn-system-backend | `backend/agents/graph.py` |
| 四层混合记忆系统 | ai-vn-system-backend | `backend/memory/` |
| TavernCommand DSL | MoRanJiangHu | `src/types.ts`, `sendWorkflow/` |
| d10 骰池引擎 | noveldemo | `tools/roller.py` |
| 角色卡 v3.2 Schema | noveldemo | `data/角色卡/林劫.json` |
| Plugin Hook 体系 | opencode | `packages/plugin/src/index.ts` |
| Permission Ruleset | opencode | `packages/opencode/src/agent/agent.ts` |
| Part 状态机 | opencode | `packages/opencode/src/session/processor.ts` |
| Bus + SSE | opencode | `packages/opencode/src/bus/`, `server/routes/` |
| SKILL.md 按需加载 | opencode | `packages/opencode/src/skill/` |
| Agent tool_use loop | pi | `packages/agent/src/agent-loop.ts` |
| Extension 系统 | pi | `packages/coding-agent/src/core/extensions/` |
| JSONL 会话树（分支） | pi | `packages/coding-agent/src/harness/session/` |
| SKILL.md 格式规范 | superpowers | `skills/*/SKILL.md` |
| user 消息前缀注入 | superpowers | `.opencode/plugins/superpowers.js` |
| always/auto/requestable 规则 | cursor | `e:\.cursor\rules\*.mdc` |

---

## 实现阶段（设计文档完成后执行）

```
Phase 1 — 骨架（2-3天）
  新建 FastAPI + React 脚手架
  Bus + SSE 事件端点
  roller.py HTTP 封装
  memory/ 子系统迁移
  Session/Message/Part SQLite schema

Phase 2 — Agent 核心（3-5天）
  LangGraph 7-Agent 图
  四阶段叙事管线（NarratorAgent）
  VarAgent 双轨变量执行
  AgentProfile Permission Ruleset

Phase 3 — 扩展与数据（2-3天）
  WorldPlugin 接口
  SKILL.md 按需加载
  三个内置扩展（crossover/wuxia/infinite_arsenal）
  37+ 文风库迁移

Phase 4 — 前端（3-5天）
  React Part 分块渲染
  骰子面板 + 角色卡侧边栏
  章节树 + 模式切换
  SSE 差分增量更新
```
