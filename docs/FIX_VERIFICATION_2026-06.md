# Zero-Arsenal 修复核查台账（2026-06）

> 配套：修复 plan / `docs/REVIEW_TODO_2026-06.md`
> 用途：每个修复点一行，记录「是否真实实现」的核查结论。
> 状态图例：✅ 真实实现 · ⚠️ 部分实现 · ❌ 未实现/无效 · ⏳ 待核查
>
> 凡 ⚠️/❌ 项保留在 `REVIEW_TODO_2026-06.md` 未勾选，并在本表「备注」给出原因与后续动作。

## Phase 1 · P0

| ID | 修复内容 | 真实实现? | 证据(file:line) | 备注 |
|---|---|---|---|---|
| NEW-C6-01 | fork_session Row 改列访问 | ✅ | `sessions.py:468,483,529` | 三处循环 `row=dict(row)` 后用 .get()；py_compile 通过 |
| NEW-C6-02 | 章节回滚分支列名 mode/branch_of | ✅ | `sessions.py:1029-1034` | current_mode→mode、forked_from→branch_of，均存在于 schema |
| NEW-C6-03 | fork 补 content/message_type/phase | ✅ | `sessions.py:472-480` | messages INSERT 补 phase/content/message_type（schema 确有此三列） |
| NEW-C9-01 | 4 世界 hooks 导入修复 | ✅ | `extensions/{muv_luv,gundam_seed,infinite_arsenal,crossover}/hooks.py` | 改用 wuxia 纯类模式（删 BaseHook/hook_registry import 与死 register_hooks）；discover 实测注册 muv_luv×2/gundam×2/infinite×3/crossover×3 |
| NEW-C3-01 | agents/llm.py logger | ✅ | `agents/llm.py:7,11` | 补 `import logging` + `logger = logging.getLogger(__name__)`；AST 解析通过 |
| NEW-C5-01 | embed_batch | ✅ | `utils/llm_client.py:111` | 新增 `_EmbeddingClient.embed_batch`，不可用时返回等长空向量 |
| NEW-C5-02 | get_db() 误用 + node_sync 方法 | ✅ | `memory/extractor.py:31-78,313-345,420-460` | 删 `db=get_db()` 误用，新增 `_upsert_node_sync/_mark_node_synced/_bump_retry` 协程（async with + 原生 SQL）；affinity 改写 session_npc_states 真实 schema |
| node_sync_status | 建表 DDL | ✅ | `db/schema.py:310` | 加入 CREATE TABLE + 索引；init_db 实测建表 + UPSERT 通过 |
| R-D01(D4) | auth 无 token fail-closed | ✅ | `api/middleware/auth.py:46-90` | 无 token 仅放行回环(127.0.0.1/::1)，远程 403；并改 hmac.compare_digest 常量时间比较 |
| NEW-C1-01 | verdict 缺失 fail-closed | ✅ | `agents/rules_agent.py:185-194`、`agents/dm_agent.py:259-272` | rules 白名单外→block，dm 白名单外→reject |
| D-16残留 | _resolve_permission 异常 deny | ✅ | `tools/registry.py:240-246`、注释 175/253、`permission.py:110` | 异常→降级 ask（非工具默认 allow）；修正三处 fail-open 误导注释 |
| NEW-B10-01 | review 放行审校工具 | ✅ | `agents/profiles/review.yaml:33-58`、`permission.py:168` | YAML+Python 均加 style_check/purity_check allow；实测 resolve=allow |
| NEW-C2-03 | chronicler start_message_id 游标 | ✅ | `agents/chronicler_agent.py:32-71,150-205` | 改按「上次固化 end_message 之后」计数；固化时写 start/end_message_id；narrative 按边界过滤（兼修 C2-04） |
| NEW-C5-03 | LLM 提取链生产接通 | ⏳ | | 归入 P1 记忆子代理（D5 pipeline），P0 仅修崩溃点 |
| B09缺陷1 | EventType 误当 Enum | ✅ | `bus/redis_bus.py:84-95,148,200-235` | 去除 `EventType(...)` 调用，统一字符串 type + `_bus_event_from_payload` 还原 |
| NEW-C7-05 | publish 携带 id/timestamp | ✅ | `bus/redis_bus.py:90-96,主体` | event_json 内嵌 id/timestamp，score=event.timestamp；续传支持按 UUID 定位锚点（兼修缺陷2） |

## Phase 2 · P1

| ID | 修复内容 | 真实实现? | 证据(file:line) | 备注 |
|---|---|---|---|---|
| D5-deps | chromadb 依赖+向量层 | ⏳ | | |
| D5-pipeline | LLM 提取+embedding+图写入 | ⏳ | | |
| NEW-C5-05 | adapter.add_memory 全链 | ⏳ | | |
| NEW-C5-04 | retriever 词法兜底 | ⏳ | | |
| D6 | viewer_agent 五视角 | ⏳ | | |
| conf_b08-viewer | GET /memory 应用 viewer | ⏳ | | |
| conf_b04-hooks | 11 类 hook fire | ⏳ | | |
| NEW-C8-03/C9-04 | 去双重注册 | ⏳ | | |
| NEW-C8-04 | hook/rules 扫三级目录 | ⏳ | | |
| NEW-C4-01 | vm guard | ⏳ | | |
| NEW-C4-02 | world_events 键对齐 | ⏳ | | |
| NEW-C4-03 | dice 减值 schema | ⏳ | | |
| R-M15 | CombatRoundResult 接线 | ⏳ | | |
| R-D09 | jinja2 依赖 | ⏳ | | |
| D2 | plan.yaml 去 roll_* | ⏳ | | |
| D3 | overlay 副本合并 | ⏳ | | |
| D7-schema | 角色卡 v4 schema | ⏳ | | |
| D7-migration | v3→v4 迁移 | ⏳ | | |
| D7-frontend | 前端适配 v4 | ⏳ | | |
| D7-ext | 各扩展适配 v4 | ⏳ | | |
| R-M14 | character_v4 jsonschema | ⏳ | | |
| D8 | 全表 CHECK/外键 | ⏳ | | |
| NEW-C11-01/02 | NPC 单一存储 | ⏳ | | |
| NEW-C7-04 | pubsub/task 回收 | ⏳ | | |
| NEW-C7-01 | 令牌桶淘汰 | ⏳ | | |
| NEW-C7-02 | X-Forwarded-For 信任 | ⏳ | | |
| NEW-C7-08 | init_db fail-loud | ⏳ | | |
| P0-5 | Hub 会话 Tab 合并 | ⏳ | | |
| NEW-C14-02 | 输入按事件解锁 | ⏳ | | |

## Phase 3 · P2

| ID | 修复内容 | 真实实现? | 证据(file:line) | 备注 |
|---|---|---|---|---|
| 降级日志 | 叙事/路由降级补日志 | ⏳ | | |
| 死代码 | 死代码/死配置清理 | ⏳ | | |
| prompt 接线 | TokenBudget/registry.build/watcher | ⏳ | | |
| 前端死字段 | activeSkills/快照/world store | ⏳ | | |
| NEW-C13-03 | 裸 fetch 统一 apiFetch | ⏳ | | |
| 前端杂项 | PromptManager 排序/WorldModal | ⏳ | | |
| 测试 | marker/命名/query/skip | ⏳ | | |
| NEW-C3-03 | compaction 裁剪 | ⏳ | | |
| NEW-C3-04 | tool_loop 异常显式 | ⏳ | | |
| NEW-C3-02 | ask 泄漏清理 | ⏳ | | |
| NEW-C6-04 | 快照恢复 fail-loud | ⏳ | | |
| NEW-C6-05 | create_world_archive 字段 | ⏳ | | |
| NEW-C7-03 | token 常量时间比较 | ✅ | `api/middleware/auth.py:9,76` | 随 R-D01 一并改 hmac.compare_digest |
| D18 | simpleeval 替换 eval | ⏳ | | |
| NEW-C7-09 | 复用 DB 连接 | ⏳ | | |
| conf_b07-toolresult | ToolResult 契约 | ⏳ | | |
| conf_b07-mcp | MCP 重试/unregister | ⏳ | | |
| conf_b09-reconnect | 前端 4xx 终止重连 | ⏳ | | |

## Phase 4 · P3 + 实现型裁定

| ID | 修复内容 | 真实实现? | 证据(file:line) | 备注 |
|---|---|---|---|---|
| D12 | MAX_ITER=20 | ⏳ | | |
| D11 | 多模型映射 | ⏳ | | |
| D13 | 外部 MCP 子 Agent | ⏳ | | |
| D16 | 8 预置 Skill | ⏳ | | |
| D17 | SKILL.md 完整格式 | ⏳ | | |
| D19 | 超时常量 30/120/15/300 | ⏳ | | |
| D21 | Tailwind v4 | ⏳ | | |
| D22 | IndexedDB LRU | ⏳ | | |
| D9 | Narrator P4 VariableBlock | ⏳ | | |
| 前端优化 | 订阅/滚底/虚拟滚动 | ⏳ | | |

## Phase 5 · 文档同步

| ID | 修复内容 | 真实实现? | 证据(file:line) | 备注 |
|---|---|---|---|---|
| D0-docsync | design 02~12 对齐 | ⏳ | | |
| 注释漂移 | redis_bus/T-D07/import 等 | ⏳ | | |

## 未完全实现汇总（核查后回填）

> 收尾阶段把所有 ⚠️/❌ 项汇总到此处，作为下一轮迭代输入。

（待 Phase 6 回填）
