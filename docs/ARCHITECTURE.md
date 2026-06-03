# 架构与降级行为 (ARCHITECTURE)

本文档记录 ZeroArsenal 关键子系统的架构约束与**降级（degradation）行为**——即外部依赖缺失/失败时系统如何退化。理解这些边界对部署、调试与扩展开发至关重要。

> 配套文档：设计细节见 `docs/design/`；占位/未实现清单见 `docs/STUB_ANALYSIS.md`；贡献规范见 `docs/CONTRIBUTING.md`。

---

## 1. 总体分层

```
前端 (React + Zustand)
   │  REST + SSE
后端 (FastAPI)
   ├─ api/routers/        REST + SSE 端点
   ├─ agents/             LangGraph 多 Agent 管线（rules→DM→dice→npc/world→narrator→style→var→chronicler）
   ├─ engine/             骰子 / 战斗 / VariableVM / prompt_assembler / runtime_data_stream
   ├─ memory/             四层混合记忆（向量 + Bigram + 图 + 认知权重）
   ├─ prompts/            PromptFragment Registry + 模板加载
   ├─ extensions/         WorldPlugin 扩展（plugin/tools/hooks/agents）
   ├─ hooks/              HookManager（18 类生命周期事件）
   └─ bus/                事件总线（内存 / Redis）
```

---

## 2. 事件总线（Bus）— 单进程限制 ⚠️

| 模式 | 触发条件 | 能力 |
|---|---|---|
| 内存总线 `EventBus`（默认） | 未设置 `REDIS_URL` | `asyncio.Queue` 进程内发布/订阅 + SSE 重放 |
| Redis 总线 `RedisEventBus` | 设置了 `REDIS_URL` 且安装了 `redis` | 设计用于跨进程广播 |

**关键限制：**

- **默认（内存总线）下，事件无法跨进程/跨实例广播。** 多 worker（如 `uvicorn --workers N`）或多实例部署时，一个进程发布的 SSE 事件，订阅在另一个进程上的客户端**收不到**。
- `RedisEventBus` 当前为**实现桩**（见 `STUB_ANALYSIS.md` STUB-01/12）：`publish`/`subscribe` 仍降级到进程内 `_local_queues`，`get_events_after*()` 固定返回 `[]`，**断线续传不可用**。
- `redis` 未安装但设置了 `REDIS_URL` 时，自动 `except` 降级回内存总线（见 `bus/__init__.py`）。
- `event_log` 持久化失败时静默 `pass`（实时 SSE 仍可用，但历史重放记录可能丢失）。

**部署建议：** 当前生产环境请使用**单进程**（`--workers 1`）部署，依赖内存总线。多进程需先补全 `RedisEventBus`（`redis.asyncio` Pub/Sub + DB 历史查询）。

---

## 3. VariableVM（`engine/vm.py`）— 无沙箱即空操作 ⚠️

- 变量脚本（`use_vm=True`）依赖 **RestrictedPython** 提供沙箱执行。
- **RestrictedPython 未安装时**：`execute()` 直接返回**原始 state**，脚本被静默跳过（不报错）。动态变量/条件脚本系统实际失效。
- 影响：依赖 VM 脚本结算的世界机制不会生效。若需该能力，必须安装 `RestrictedPython`；否则应改走 TavernCommand DSL 路径。

**部署建议：** 启用变量脚本的世界，部署时务必安装 `RestrictedPython` 并在启动日志确认 VM 可用。

---

## 4. prompt_assembler（`engine/prompt_assembler.py`）— 失败返回空 prompt ⚠️

- 负责把 PromptFragment Registry 组装成最终 system prompt。
- **Registry 构建失败时**当前 `return ""`：LLM 将以**空 system prompt** 运行，角色/世界设定完全丢失，叙事质量灾难性下降。
- **jinja2 未安装时**：`return template_str` 原文（不渲染变量占位符）。
- `prompts/template_loader.py`：无 jinja2 或模板文件缺失时 `return ""`，对应 Prompt 片段变为空。
- `prompts/registry.py`：condition `eval` 失败时**默认注入**（`return True`，偏多注入）；TokenBudget 不可用则不裁剪。

**部署建议：** 安装 `jinja2`；监控启动期 Registry 构建日志。理想状态应在组装失败时抛错而非返回空 prompt（待改进项）。

---

## 5. runtime_data_stream（`engine/runtime_data_stream.py`）— 部分轴写死

- 负责把运行时状态切成多条"数据轴"注入 Agent context。
- **当前 `active_quests=[]`、`active_hooks=[]` 写死**（轴 14-15 常为空）：任务/伏笔无法注入 Agent context。需从 `TurnContext`/DB 拉取后才能生效。
- 无 `world_events` 时时间/地点退化为「未知时间」「未知地点」占位。

---

## 6. 四层混合记忆 — 降级到 SQLite 关键词召回 ⚠️

记忆系统设计为四层混合召回（向量语义 + Bigram + 图扩散 + 认知权重）。实际运行路径取决于可选依赖：

| 依赖 | 缺失后果 |
|---|---|
| ChromaDB + sentence-transformers | `_engine_available=False`，**全程退化为 SQLite 关键词召回**；语义检索失效 |
| 向量步（`get_embedding_client`） | `hybrid_recall` 向量结果为 `[]`，混合召回退化为关键词 + 图扩散 |
| `jieba` | 分词降级（`pass`，合理降级） |

**当前实际运行路径（默认环境）**：启发式 `extract_queue`（关键词分段 + tier）+ SQLite + `chapter_consolidator`（LLM 摘要）。全量 LLM 图谱提取栈（`extractor`/`consolidator`/`retriever`/`rollback`）依赖项目内尚不存在的 `utils.llm_client` 与 `db.queries`，无法独立运行。

**可观测性：** 记忆健康状态见 `GET /config/system/memory-health`；前端「设置 → 记忆健康」Tab 暴露 fallback 状态。

---

## 7. Agent 管线失败兜底

各 LLM Agent 在解析失败/超时时有兜底行为。**安全相关已改为 fail-closed**：

| Agent | 失败行为 | 安全性 |
|---|---|---|
| `rules_agent` / `dm_agent` | 拒绝（fail-closed，本计划 Phase 0A 已修复） | ✅ |
| 权限检查（`tools/registry.py`） | 拒绝（fail-closed，Phase 0A 已修复） | ✅ |
| `npc_agent` | 失败 → NPC 沉默台词 | 剧情降级 |
| `world_agent` | 无触发词且非第 5 轮 → 跳过 LLM | 世界事件可能缺失 |
| `style_agent` | 审查失败 → 原文透传 | 文风降级 |
| `chronicler_agent` | 摘要失败 → 空串 | 章节摘要丢失 |
| `narrator_agent` | P4 state_patch 提取失败 → `[]` | 状态不更新 |

管线取消：玩家可通过 `DELETE /sessions/{id}/stream` 请求取消，管线在下一个节点边界抛 `TurnCancelled` 优雅停止（见 `agents/cancellation.py` + `agent_span.py`）。

---

## 8. 鉴权与限流

- **鉴权**（`middleware/auth.py`）：未配置 `ZERO_ARSENAL_API_TOKEN` 时**完全放行**所有 `/api/*`（开发模式 = 无鉴权）。生产部署务必配置 token。
- **限流**（`middleware/rate_limit.py`）：令牌桶状态**在进程内存**，多 worker 不共享；可通过 `ZERO_ARSENAL_RATE_ENABLED=0` 关闭。

---

## 9. 扩展加载

- 三级目录（内置 / 用户 `~/.zero-arsenal` / 项目 `.zero-arsenal`），高优先级覆盖低优先级。
- 仅含 `manifest.json` 的目录被识别；`_` 前缀目录跳过（如骨架 `_template`）。
- `plugin.py` / `tools.py` / `hooks.py` 经 `spec_from_file_location` 动态加载，**无包上下文**，详见 `CONTRIBUTING.md` 与 `extensions/_template/README.md`。

---

## 10. 测试分层与桩标注

- 部分历史测试为**静态源码字符串检查**或**失败不退出**的伪集成/伪 E2E（详见 `STUB_ANALYSIS.md` 第九节）。
- 这类测试已用 `@pytest.mark.stub` 标注，CI 可用 `pytest -m "not stub"` 排除，单独分组报告，避免它们给出虚假的绿色信号。
- 标记在 `backend/pyproject.toml`（或 `pytest.ini`）的 `markers` 中注册。

---

*本文档随架构演进持续更新。修改降级行为时请同步更新本文件（见 CONTRIBUTING.md 第 4 节）。*
