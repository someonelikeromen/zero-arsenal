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

## 部分完成项（2026-06-04 第二轮已清零 ✅）

| ID | 内容 | 结果 |
|----|------|------|
| 降级日志 | 路由侧 R-D02/03/04/08 静默降级 | ✅ `characters.py`/`engine.py`/`sessions.py`/`worlds.py` 全部 except pass→warning；T-D09/11 此前已覆盖 |
| 前端性能 | 真·虚拟滚动 windowing + NarrativePart 细粒度订阅 | ✅ 引入 `react-virtuoso` 窗口化（followOutput 跟随）；流式 delta 拆入 store `streamBuffers` map，NarrativePart/ReasoningPart 订阅自身缓冲直写 DOM（conf_b12） |

> 至此复审清单 + 24 条裁定项**全部 ✅**，无遗留 ⚠️/❌。

## 路线图（产品向）

| 阶段 | 主题 | 状态 |
|------|------|------|
| Phase 1–8 | 骨架、Agent、扩展、VM、记忆、权限、前端、工具 | ✅ 主路径完成 |
| 2026-06 复审 | P0 崩溃/安全 + P1–P5 设计对齐 | ✅ `173d921` |
| 2026-06 第二轮 | 路由降级日志 + react-virtuoso 虚拟滚动 + conf_b12 细粒度订阅 | ✅ 清单全闭环 |
| 下一迭代 | 多实例 Redis 生产演练、bundle 拆包优化 | ⏳ |

## 维护规则

- 合并一批修复后：更新本文件摘要 + [FIX_VERIFICATION_2026-06.md](./FIX_VERIFICATION_2026-06.md) 对应行。
- 对外描述以 FIX_VERIFICATION 为准，避免 README Phase 表与实现脱节。
