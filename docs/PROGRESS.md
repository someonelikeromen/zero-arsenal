# 项目进度（2026-06-04）

> 权威核查台账：[FIX_VERIFICATION_2026-06.md](./FIX_VERIFICATION_2026-06.md)  
> 历史修复清单：[REVIEW_TODO_2026-06.md](./REVIEW_TODO_2026-06.md)  
> 最新代码基线：`main` @ `173d921`（P1–P5 复审修复）

## 一句话状态

**主路径已可演示**：多 Agent 叙事、确定性骰子、世界扩展、四层记忆（`mode=full`）、角色卡 v4、SSE 实时前端均已接通；仅剩少量可观测性与性能优化待办。

## 已完成（已核查 ✅）

| 领域 | 说明 |
|------|------|
| 后端骨架 | FastAPI + SQLite + 自动迁移 + REST/SSE |
| Agent 管线 | LangGraph 多 Agent（rules → DM → dice → npc/world → narrator → style → var → chronicler） |
| 记忆系统 | LLM 图谱提取队列、chromadb 向量、词法兜底、图扩散、viewer 五视角、`GET /memory?viewer_agent=` |
| 扩展 | crossover / wuxia / infinite_arsenal / muv_luv / gundam_seed；18 类 Hook 已 fire；三级目录扫描 |
| 安全 | 无 token 时远程 fail-closed；verdict/permission fail-closed；常量时间 token 比较 |
| 引擎 | VM guard、骰子减值 schema、world_events 键对齐 |
| 数据 | 角色卡 v4 schema + 迁移 + jsonschema；全表 CHECK/FK |
| 前端 | Hub 合并、按事件解锁输入、Tailwind v4、IndexedDB LRU、apiFetch 统一、4xx 终止 SSE 重连 |
| 其他 | 8 预置 Skill、外部 MCP 子 Agent、分级超时、design 02–12 文档对齐 |

收尾验证（见 FIX_VERIFICATION Phase 6）：`pytest --collect-only` 61 项、前端 `npm run build` 通过、init_db CHECK/FK 通过、59 工具加载、记忆 `mode=full`。

## 部分完成（⚠️，适合认领）

| ID | 内容 | 影响 |
|----|------|------|
| 降级日志 | world/style/npc/options 已补日志；**路由侧** R-D02/03/04/08、T-D09/11 未全覆盖 | 可观测性，不影响功能正确性 |
| 前端性能 | 智能滚底 + 流式跟随已有；**真·虚拟滚动 windowing** 与 NarrativePart 细粒度订阅未做 | 长会话列表性能，暂缓引第三方依赖 |

## 建议 good-first-issue

1. 为 `api/routers/sessions.py` 及叙事路由降级路径补 `logger.warning`（对照 FIX_VERIFICATION「降级日志」备注）。
2. 评估 `MessageThread` 虚拟列表方案（`react-window` / 自研 windowing），在不大改 Part 渲染的前提下做 POC。

## 路线图（产品向）

| 阶段 | 主题 | 状态 |
|------|------|------|
| Phase 1–8 | 骨架、Agent、扩展、VM、记忆、权限、前端、工具 | ✅ 主路径完成 |
| 2026-06 复审 | P0 崩溃/安全 + P1–P5 设计对齐 | ✅ `173d921` |
| 下一迭代 | 路由降级日志、虚拟滚动、多实例 Redis 生产演练 | ⏳ 见上表 ⚠️ |

## 维护规则

- 合并一批修复后：更新本文件摘要 + [FIX_VERIFICATION_2026-06.md](./FIX_VERIFICATION_2026-06.md) 对应行。
- 对外描述以 FIX_VERIFICATION 为准，避免 README Phase 表与实现脱节。
