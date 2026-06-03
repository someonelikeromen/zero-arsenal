# Zero-Arsenal 占位/打桩/未实现代码分析报告

> ⚠️ **历史快照（已部分过时，截至 Phase 0A 前）**
> 本报告经 **2026-06-03** 全量行级复审证实**已部分过时**：多条 P0（fail-open 门禁、`utils/llm_client.py`/`db/queries.py` 不存在、redis_bus 未实现、前端 UX 零接线等）实际已修复，同时存在一批旧报告未记录的新运行期硬伤。
> **后续请以以下三份报告为准**：
> - 代码缺陷：[`docs/REVIEW_2026-06.md`](./REVIEW_2026-06.md)
> - 设计符合度：[`docs/DESIGN_CONFORMANCE_2026-06.md`](./DESIGN_CONFORMANCE_2026-06.md)
> - 修复总清单（P0~P3）：[`docs/REVIEW_TODO_2026-06.md`](./REVIEW_TODO_2026-06.md)
> 行级证据分片见 `docs/review/def_c*.md`、`docs/review/conf_b*.md`。
>
> 生成日期：2026-06-02（持续更新）  
> 扫描范围：`backend/`（全部 ~100 个 .py）、`frontend/src/`（全部 47 个 .ts/.tsx）、`extensions/`、`tests/`（全部 13 个）、`data/` JSON 数据文件  
> 状态：✅ **三轮全量扫描完成**

---

## 统计摘要

| 严重程度 | 第一轮 | 第二轮 | 第三轮新增 | **合计** |
|---------|:------:|:------:|:---------:|:-------:|
| 🔴 核心功能缺失 | 14 | 9 | **11** | **34** |
| 🟡 功能降级 | 22 | 22 | **28** | **72** |
| 🟢 次要功能 | 11 | 17 | **17** | **45** |
| **合计** | **47** | **48** | **56** | **151** |

> 第三轮覆盖：agents 基础设施（ask_handler/llm/graph/permission/state/agent_node）、extensions/web_scraper、main.py、rules_loader、全部 13 个测试文件、全部前端组件与 stores、data/ JSON 数据文件。

---

## 一、🔴 核心功能缺失（14 处）

### STUB-01 · Redis 事件总线 — 完整实现桩

| 属性 | 值 |
|------|---|
| 文件 | `backend/bus/redis_bus.py` |
| 行号 | L1–120（尤其 L67–120） |
| 状态 | 文件头标注「实现桩 Stub」 |

**问题**：  
- `publish`/`subscribe` 未接 Redis Pub/Sub，仅用进程内 `_local_queues` 降级  
- `get_events_after()` 和 `get_events_after_from_db()` **固定 `return []`**，断线续传不可用  
- 多进程/多实例广播无法工作

**影响**：SSE 断线恢复失效；生产环境多进程部署事件丢失

---

### STUB-02 · 记忆向量引擎 — ChromaDB 缺失时整段不可用

| 属性 | 值 |
|------|---|
| 文件 | `backend/memory/adapter.py` L36–79, L122–150 |
| 文件 | `backend/memory/vector.py` L21–46 |

**问题**：  
- ChromaDB + sentence-transformers 未安装时 `_engine_available=False`，全程退化为 SQLite 关键词召回  
- `VectorStore` 抽象基类 4 个方法全是 `raise NotImplementedError`（Chroma/FAISS 子类存在，但默认环境可能永远走 fallback）

**影响**：语义记忆召回、相似度检索全部失效

---

### STUB-03 · Rules Agent — LLM 不可用时硬编码放行

| 属性 | 值 |
|------|---|
| 文件 | `backend/agents/rules_agent.py` |
| 行号 | L171–173 |

```python
result_text = '{"verdict":"pass","reason":"LLM不可用，默认放行"}'
```

**问题**：非降级，是**绕过规则门禁**，任何 LLM 超时/异常均会放行违规行为。  
**影响**：规则系统核心安全性失效

---

### STUB-04 · MUV-LUV 扩展 — Prompt 格式不兼容 + 无工具/钩子

| 属性 | 值 |
|------|---|
| 文件 | `backend/extensions/muv_luv/plugin.py` L20–115 |
| manifest | `tools: false, agents: false, hooks: false` |

**问题**：  
- 无 `tools.py` / `hooks.py` / `agents.py`  
- `PLUGIN.system_prompt_fragments` 用 `PromptFragment` 对象，与 `apply_to_registry()` 期望的 `dict`（含 `"content"` 键）**格式不兼容**  
- `MuvLuvWorldPlugin.apply_to_registry()` 存在但未挂到注册的 `PLUGIN` 实例上

**影响**：MUV-LUV 世界的 Prompt 注入链路可能完全失效

---

### STUB-05 · Gundam SEED 扩展 — 同上 + 空技能目录

| 属性 | 值 |
|------|---|
| 文件 | `backend/extensions/gundam_seed/plugin.py` L47–109 |
| manifest | `plugin_id` 非 `id`（loader 靠目录名兜底） |

**问题**：  
- 无 `tools.py` / `hooks.py` / `agents.py`  
- `get_skill_catalog()` 扫描 `skills/*.json`，目录**不存在** → 恒返回 `[]`  
- Prompt fragments 格式问题同 STUB-04

---

### STUB-06 · 抽卡发货 — 硬编码种子库，未读 pool-catalog.json

| 属性 | 值 |
|------|---|
| 文件 | `backend/extensions/infinite_arsenal/agents.py` L23–75 |

```python
# TODO: 正式版应读取 pool-catalog.json
_ACG_ITEMS = [...]  # 约 20 条硬编码条目
```

**问题**：`GachaAgent` 用 `random.choice` 从硬编码 `_ACG_ITEMS` 发货，无 LLM、无 ACG 来源校验。  
**影响**：无限武库抽卡核心体验降级至随机列表

---

### STUB-07 · draw_gacha 工具 — 只生成落点框架

| 属性 | 值 |
|------|---|
| 文件 | `backend/extensions/infinite_arsenal/tools.py` L183–239 |

**问题**：扣 SP + 随机 tier/sub/category 后，返回 `"note": "落点框架已生成，请 GachaAgent 匹配 ACG 来源物品并发货"`。真实物品发货依赖 GachaAgent（见 STUB-06）。

---

### STUB-08 · 卡池配置 — 硬编码，未读 JSON 目录

| 属性 | 值 |
|------|---|
| 文件 | `backend/extensions/infinite_arsenal/tools.py` L154–171 |

**问题**：`_POOL_CATALOG` 内联三池权重，同目录存在 `data/pool-catalog.json` 但**从未被加载**。

---

### STUB-09 · WorldPlugin 基类 — 空规则/空角色模板

| 属性 | 值 |
|------|---|
| 文件 | `backend/extensions/plugin.py` L134–140 |

```python
def get_rules_skills(self) -> list[str]:
    return []
def get_character_template(self) -> dict:
    return {}
```

**问题**：`muv_luv`/`gundam_seed` 未 override，会话初始化无世界专属角色模板。

---

### STUB-10 · crossover — 无 hooks.py

| 文件 | `backend/extensions/crossover/` 目录 |
|------|---|
**问题**：有 `plugin.py` 和 `tools.py`，但无 `hooks.py`，跨界事件钩子链路断开。

---

### STUB-11 · infinite_arsenal — 无 hooks.py

| 文件 | `backend/extensions/infinite_arsenal/` 目录 |
|------|---|
**问题**：无 `hooks.py`，武器损耗/锻造消耗等钩子事件无法触发。

---

### STUB-12 · Redis 历史事件查询第二个空实现

| 属性 | 值 |
|------|---|
| 文件 | `backend/bus/redis_bus.py` L107–120 |

```python
async def get_events_after_from_db(self, ...):
    # TODO: 从 DB 读取历史事件
    return []
```

（与 STUB-01 同文件，独立标注）

---

### STUB-13 · muv_luv — 无任何工具/Agent/Hook 实现

扩展目录仅含 `plugin.py` + `rules/` 规则文档，manifest 明示 `tools: false, agents: false`，完整扩展能力未落地。

---

### STUB-14 · gundam_seed — 无任何工具/Agent/Hook 实现

同上，仅有 `plugin.py` + `rules/mobile_suit_combat.md`。

---

## 二、🟡 功能降级（22 处）

> 有实现，但在 LLM/外部服务失败时静默退化为兜底行为。

### Agent 节点失败兜底

| # | 文件 | 行号 | 退化行为 | 风险 |
|---|------|:----:|---------|------|
| D-01 | `agents/dm_agent.py` | L280–283 | JSON 解析失败 → `dm_verdict = "allow"` | 规则误放行 |
| D-02 | `agents/rules_agent.py` | L206–211 | 解析失败 → 默认 `pass` | 规则绕过 |
| D-03 | `agents/npc_agent.py` | L106–112 | tool_loop 失败 → `"{npc}沉默地看着你。"` | 剧情断裂 |
| D-04 | `agents/world_agent.py` | L131–133 | 无触发词且非第 5 轮 → 跳过 LLM | 世界事件缺失 |
| D-05 | `agents/world_agent.py` | L178–179 | LLM/JSON 失败 → `world_events=[]` | — |
| D-06 | `agents/style_agent.py` | L165–168 | 审查 JSON 失败 → 原文透传 | 文风失控 |
| D-07 | `agents/chronicler_agent.py` | L297–299 | 摘要 LLM 失败 → `return ""` | 章节摘要丢失 |
| D-08 | `agents/narrator_agent.py` | L484–486 | P4 state_patch 提取失败 → `return []` | 状态不更新 |
| D-09 | `agents/compaction.py` | L78–79 | 压缩失败静默跳过 | 记忆溢出 |

### 工具层硬编码降级

| # | 文件 | 行号 | 退化行为 |
|---|------|:----:|---------|
| D-10 | `tools/builtin_tools.py` | L602–604 | `generate_action_options` 失败 → `"行动选项 A/B/C"` |
| D-11 | `tools/builtin_tools.py` | L867–873 | `open_shop` 失败 → 固定「普通长剑/生命药水」 |
| D-12 | `tools/builtin_tools.py` | L916–923 | `evaluate_item` 失败 → 品质倍率公式估价 |
| D-13 | `tools/builtin_tools.py` | L306–309 | `get_npc_knowledge_scope` 无档案 → **硬编码** knows/doesnt_know |
| D-14 | `tools/builtin_tools.py` | L396–400 | `check_skill_trigger` 仅关键词匹配，非真实规则引擎 |
| D-15 | `tools/builtin_tools.py` | L230, L245–246 | `roll_check` 读档失败 → 默认 `pool=2` |
| D-16 | `tools/registry.py` | L265–267 | 权限检查失败 → **fail-open 默认 allow** |
| D-17 | `tools/mcp_bridge.py` | L60–73 | 无 aiohttp 或 HTTP 失败 → `return []` |

### 扩展工具简化逻辑

| # | 文件 | 行号 | 退化行为 |
|---|------|:----:|---------|
| D-18 | `extensions/crossover/tools.py` | L109–119 | 预设 15 条事件，`random.choice` 非 LLM |
| D-19 | `extensions/infinite_arsenal/tools.py` | L59–75 | 锻造：固定材料映射表 + `random.randint` |
| D-20 | `extensions/wuxia/tools.py` | L111–168 | `spar_challenge` 直接接受 `outcome` 参数，无骰子逻辑 |

### 记忆/总线降级

| # | 文件 | 行号 | 退化行为 |
|---|------|:----:|---------|
| D-21 | `memory/adapter.py` | L145–150 | full recall 异常 → SQLite fallback |
| D-22 | `agents/tool_loop.py` | L419–470 | function calling 不可用 → 文本解析 `<tool_call>` |

---

## 三、🟢 次要功能（11 处）

| # | 文件 | 行号 | 描述 |
|---|------|:----:|------|
| M-01 | `extensions/registry_builder.py` | L98–101 | `_scan_extension_dir()` 标注「已废弃」，恒 `return []` |
| M-02 | `extensions/plugin.py` | L179–180 | 权限 overlay 失败 `pass`（静默跳过） |
| M-03 | `frontend/src/stores/character.ts` | L40–70 | `inventory` / `activeSkills` 字段**从未写入**，死状态 |
| M-04 | `frontend/src/components/parts/PartRenderer.tsx` | L27–30 | 未知 type → `return null`（无降级 UI） |
| M-05 | `bus/redis_bus.py` | — | 进程内降级队列（单进程限定，与 STUB-01 同文件） |
| M-06 | `gundam_seed/manifest.json` | L2 | 用 `plugin_id` 非 `id`（loader 靠目录名兜底） |
| M-07 | `extensions/hook_protocol.py` | L21–100 | Protocol 方法体为 `...`（接口定义，可接受） |
| M-08 | `agents/agent_span.py` | — | 多处 `except: pass`（SSE/Hook 发布失败不阻断） |
| M-09 | `tests/unit/test_p3_parttype.py` | L45 | `pytest.skip` 条件跳过 |
| M-10 | `docs/design/07-tool-registry.md` | — | 文档标注「待实现」 |
| M-11 | `docs/design/09-event-bus-sse.md` | — | 文档标注「待实现」 |

---

## 四、扩展插件完整度对照

| 扩展 | plugin | tools | agents | hooks | JSON 数据文件利用 |
|------|:------:|:-----:|:------:|:-----:|:---------------:|
| crossover | ✅ | ✅ 4个 | ❌ | ❌ | ❌ shop-catalog 等未读入 |
| infinite_arsenal | ✅ | ✅ 5个 | ⚠️ 种子库 | ❌ | ❌ pool-catalog/acg-registry 未读 |
| wuxia | ✅ | ✅ 3个 | ❌ | ✅ | ❌ sects/techniques JSON 未读 |
| muv_luv | ⚠️ 格式问题 | ❌ | ❌ | ❌ | 仅 rules md |
| gundam_seed | ⚠️ 格式问题 | ❌ | ❌ | ❌ | 仅 rules md |

---

## 五、Agent 节点 LLM 调用情况

| Agent 节点 | LLM | 备注 |
|-----------|:---:|------|
| rules_agent | ✅ | 失败默认放行（STUB-03） |
| dm_agent | ✅ | 失败默认 allow（D-01） |
| dice_node | ❌ | 设计如此，纯引擎计算 |
| npc_agent | ✅ | 失败固定台词（D-03） |
| world_agent | ✅ | 多数轮次跳过（D-04） |
| narrator_agent | ✅ | 四阶段，P4 有 fallback |
| style_agent | ✅ | 失败原文透传（D-06） |
| var_agent | ❌ | 设计如此，DB/VM 结算 |
| chronicler_agent | ✅ | 失败空串（D-07） |
| gacha_agent | ❌ | **无 LLM**，随机种子库（STUB-06） |

---

## 六、前端静态假数据扫描结论

**结论：前端组件均走真实 API，未发现仅展示静态假数据的组件。**

- 会话/世界/角色/资产/提示词均通过 `frontend/src/lib/api.ts` 拉取
- 轻微问题：`character.ts` 的 `inventory`/`activeSkills` store 字段未使用（M-03）

---

## 七、优先修复建议

| 优先级 | 问题 | 对应条目 |
|:------:|------|---------|
| P0 | Rules Agent 失败改为 `block` 或 `needs_check` | STUB-03 |
| P0 | muv_luv / gundam_seed Prompt fragments 格式修复 | STUB-04, 05 |
| P0 | 权限检查失败从 fail-open 改为 fail-closed | D-16 |
| P1 | Redis 总线填充 redis.asyncio，或明确「单进程限定」 | STUB-01, 12 |
| P1 | GachaAgent + 卡池改为读取 `data/*.json` | STUB-06, 07, 08 |
| P1 | DM Agent JSON 解析失败改为 `block` 而非 `allow` | D-01 |
| P2 | 记忆子系统健康端点在 UI 暴露 fallback 状态 | STUB-02 |
| P2 | crossover / wuxia JSON catalogs 改为读取 `data/` | D-18, D-19 |
| P3 | muv_luv / gundam_seed 补充 tools.py + hooks.py | STUB-13, 14 |
| P3 | 前端死字段 inventory/activeSkills 清理 | M-03 |

---

---

## 八、第二轮补充扫描结果

> 扫描范围：`middleware/`、`routers/`、`engine/`、`memory/`（完整）、`db/`、`hooks/`、`prompts/`、`skills/`、`utils/`、`bus/`（完整）

### 8.1 🔴 核心功能缺失（第二轮新增 9 处）

#### STUB-R01 · sessions.py fork — NPC 列名错误（SQL 会直接失败）

| 属性 | 值 |
|------|---|
| 文件 | `backend/api/routers/sessions.py` |
| 行号 | L494–499 |

**问题**：`fork_session` 插入 NPC 时使用列名 `npc_key`，而 schema 定义为 `key`，fork 时 NPC 复制会抛 SQL 错误。  
**影响**：Fork 会话功能完全不可用

---

#### STUB-R02 · sessions.py 章节回滚 — create_branch 未实现

| 属性 | 值 |
|------|---|
| 文件 | `backend/api/routers/sessions.py` |
| 行号 | L80–82, L893–971 |

**问题**：`ChapterRollbackRequest.create_branch` 字段从未使用；响应中 `new_branch_id` **恒为 `None`**。  
**影响**：分支创建回滚功能不可用

---

#### STUB-R03 · prompt_assembler — 失败时返回空 system prompt

| 属性 | 值 |
|------|---|
| 文件 | `backend/engine/prompt_assembler.py` |
| 行号 | L197–199 |

**问题**：Registry 构建失败时 `return ""`，LLM 以空 system prompt 运行，角色/世界设定完全丢失。  
**影响**：叙事质量灾难性下降（无 system prompt 等于无设定）

---

#### STUB-R04 · VariableVM — 无 RestrictedPython 时直接返回原 state

| 属性 | 值 |
|------|---|
| 文件 | `backend/engine/vm.py` |
| 行号 | L114–121 |

**问题**：`RestrictedPython` 未安装时 `execute()` 直接返回原 state，`use_vm=True` 实际无沙箱执行，变量脚本全部静默跳过。  
**影响**：动态变量/条件脚本系统完全失效

---

#### STUB-R05 · memory/consolidator — 依赖 utils.llm_client（项目内不存在）

| 属性 | 值 |
|------|---|
| 文件 | `backend/memory/consolidator.py` |
| 行号 | L78–80, L100–115 |

**问题**：import `utils.llm_client` 在项目 `backend/utils/` 中**不存在**；失败时拼接摘要，语义压缩不可用。

---

#### STUB-R06 · memory/extractor — 全量 LLM 提取不可用

| 属性 | 值 |
|------|---|
| 文件 | `backend/memory/extractor.py` |
| 行号 | L224–248, L308–311 |

**问题**：`_llm_extract` 和向量化均依赖 `utils.llm_client`、`get_embedding_client`、`db.queries`（均不存在）。全量 LLM 图谱提取路径在仓库内无法独立运行。

---

#### STUB-R07 · memory/retriever — 向量召回步依赖缺失

| 属性 | 值 |
|------|---|
| 文件 | `backend/memory/retriever.py` |
| 行号 | L206–230 |

**问题**：`hybrid_recall` 向量步依赖 `get_embedding_client`，失败则 `vector_results=[]`，只剩图扩散/空召回，混合召回退化为纯关键词。

---

#### STUB-R08 · memory/rollback — 依赖 db.queries（不存在）

| 属性 | 值 |
|------|---|
| 文件 | `backend/memory/rollback.py` |
| 行号 | L33–35, L63–71 |

**问题**：逻辑完整，但 import `db.queries.get_db` 不存在，rollback 在调用时会 ImportError；API 层又静默捕获该异常，图谱/向量回滚往往未执行。

---

#### STUB-R09 · runtime_data_stream — quests/hooks 轴写死为空

| 属性 | 值 |
|------|---|
| 文件 | `backend/engine/runtime_data_stream.py` |
| 行号 | L256–257 |

**问题**：`_extract_stream` 中 `active_quests=[]`、`active_hooks=[]` 写死，轴 14-15 常为空，任务/伏笔无法注入 Agent context。

---

### 8.2 🟡 功能降级（第二轮新增 22 处）

#### API 路由层

| # | 文件 | 行号 | 退化行为 |
|---|------|:----:|---------|
| R-D01 | `middleware/auth.py` | L41–43 | 未配置 `ZERO_ARSENAL_API_TOKEN` 时**完全放行**所有 `/api/*`（生产忘配 = 无鉴权） |
| R-D02 | `routers/characters.py` | L203–208, L235–242 | LLM 解析失败 → `questions=[]` 或 `create_default_character()` 兜底 |
| R-D03 | `routers/engine.py` | L81–82, L94–95 | `rules_loader` 缺失时返回空列表 + note，非完整规则系统 |
| R-D04 | `routers/sessions.py` | L177, L336, L350 | `on_session_init` / WorldPlugin overlay / `active_tools` 失败 → `except: pass` 静默 |
| R-D05 | `routers/sessions.py` | L181–189 | `create_session` 响应里 **`character` 恒为 `None`**，未返回已创建角色卡 |
| R-D06 | `routers/sessions.py` | L952–963 | 章节回滚调用 `memory_rollback.rollback_chapter` 失败 → `pass` 静默，图谱回滚未执行 |
| R-D07 | `routers/stream.py` | L100–202（多处） | 管线各阶段异常 `pass` 吞掉（读库、插件、hook、写回角色） |
| R-D08 | `routers/worlds.py` | L88–94 | LLM 提炼 JSON 失败 → `entries=[]` |

#### 引擎层

| # | 文件 | 行号 | 退化行为 |
|---|------|:----:|---------|
| R-D09 | `engine/prompt_assembler.py` | L206–208 | 无 jinja2 时 `return template_str` 原文（非渲染结果） |
| R-D10 | `engine/runtime_data_stream.py` | L332–334 | 无 `world_events` 时时间/地点为「未知时间」「未知地点」占位 |

#### 记忆子系统

| # | 文件 | 行号 | 退化行为 |
|---|------|:----:|---------|
| R-D11 | `memory/engine.py` | L7–20 | `get_extract_queue` 符号缺失靠 ImportError 回退 |
| R-D12 | `memory/extract_queue.py` | L100–170 | `_process_task` 为启发式分段+关键词 tier，非 LLM 图谱提取；队列满则丢弃 |

#### Prompts 系统

| # | 文件 | 行号 | 退化行为 |
|---|------|:----:|---------|
| R-D13 | `prompts/registry.py` | L128–130 | condition `eval` 失败时**默认注入**（`return True`，偏多注入） |
| R-D14 | `prompts/registry.py` | L200–201 | TokenBudget 不可用则不裁剪 |
| R-D15 | `prompts/template_loader.py` | L51–77 | 无 jinja2/无模板文件时 `return ""`（Prompt 片段变为空） |

---

### 8.3 🟢 次要功能（第二轮新增 11 处）

| # | 文件 | 行号 | 描述 |
|---|------|:----:|------|
| R-M01 | `middleware/rate_limit.py` | L76–91 | 令牌桶状态在进程内存，多 worker 不共享；可整体关闭 |
| R-M02 | `routers/config.py` | L77 | `has_lifecycle_hooks` **恒为 `True`**，未检测插件是否真有生命周期 hook |
| R-M03 | `db/connection.py` | L51–134（多处） | 迁移/索引失败 `pass` 静默（可能掩盖真实错误） |
| R-M04 | `skills/watcher.py` | L118–121 | 无 `watchfiles` 时直接 return，热加载禁用 |
| R-M05 | `skills/writing_styles.py` | L34–35 | 目录不存在时 `return 0`（无风格注册） |
| R-M06 | `tools/skill_loader.py` | L53–54 | 单文件注册失败 `pass` 静默 |
| R-M07 | `bus/redis_bus.py` | L74–87 | publish 降级本地队列（单进程，已在 STUB-01 标注） |
| R-M08 | `memory/retriever.py` | L91 | jieba 缺失时 `pass`（合理降级） |
| R-M09 | `memory/vector.py` | L21–46 | 抽象基类 4 个方法 `raise NotImplementedError`（子类有实现） |
| R-M10 | `engine/prompt_assembler.py` | — | 无 jinja2 警告但不阻断（可接受） |
| R-M11 | `extensions/plugin.py` | L179–180 | 权限 overlay 失败 `pass` 静默跳过 |
| R-M12 | `memory/engine.py` | L68–74 | `enqueue_extraction` 入队 `{novel_id, messages, ...}`，与 `extract_queue._process_task` 期望的 `session_id/narrative_text` **字段不匹配**；全量引擎若启用，队列任务会被静默跳过 |
| R-M13 | `memory/schema.py` | L228–231 | `CONSOLIDATION_CONFIG["synopsis_to_arc"]` 无对应 consolidator 逻辑 |
| R-M14 | `db/character_v4.py` | L177–224 | `CHARACTER_V4_SCHEMA` 完整定义但未用 jsonschema 校验，`validate_character` 为手写子集 |
| R-M15 | `engine/combat.py` | L79–88 | `CombatRoundResult` 已定义但全项目**无引用**，整轮战斗结算 API 未暴露 |
| R-M16 | `bus/interface.py` | L56–62 | `get_subscriber_count` 默认返回 `-1`（EventBus 子类已覆盖，基类未实现） |
| R-M17 | `bus/event_bus.py` | L103–104 | event_log DB 持久化失败 `pass`（实时 SSE 仍可用，但历史重放记录可能丢失） |

---

### 8.4 横切结论

| 检查项 | 结论 |
|--------|------|
| **auth / rate_limit** | auth 有实现，但默认无 token 即放行（开发模式 = 无鉴权）；rate_limit 有实现，仅本机内存 |
| **hooks 系统** | ✅ 真实注册与 `fire`（stream 中 before/after_turn）；非空壳 |
| **bus/sse_adapter** | ✅ 订阅/重放/SSE 完整实现 |
| **engine/combat、dice、psyche** | ✅ 完整实现，无占位 |
| **engine/vm** | ❌ 无 RestrictedPython = 静默空操作 |
| **memory 全量栈** | ❌ extractor/consolidator/retriever/rollback 依赖 `utils.llm_client` 和 `db.queries`（均不存在），全量 LLM 图谱提取无法独立运行 |
| **记忆实际运行路径** | 启发式：`extract_queue` + SQLite + `chapter_consolidator`（LLM 摘要） |
| **prompts** | ✅ 核心片段完整；template_loader 有缺依赖退化 |
| **前端** | ✅ 全走真实 API，无假数据组件 |

---

## 九、合并优先修复建议（含两轮结果）

| 优先级 | 问题 | 对应条目 |
|:------:|------|---------|
| 🚨 P0 | `sessions.py` fork NPC 列名 `npc_key` → `key` | STUB-R01 |
| 🚨 P0 | Rules Agent 失败改为 `block`，禁止 silent pass | STUB-03 |
| 🚨 P0 | DM Agent 失败改为 `block` 而非 `allow` | D-01 |
| 🚨 P0 | 权限检查失败从 fail-open 改为 fail-closed | D-16 |
| 🚨 P0 | muv_luv / gundam_seed Prompt fragments 格式修复 | STUB-04, 05 |
| ⚠️ P1 | `prompt_assembler` 失败时抛错而非返回空 prompt | STUB-R03 |
| ⚠️ P1 | 补充或重定向 `utils/llm_client` + `db/queries`，解锁全量记忆栈 | STUB-R05~R08 |
| ⚠️ P1 | 实现 `create_branch`，`new_branch_id` 返回真实值 | STUB-R02 |
| ⚠️ P1 | Redis 总线填充 `redis.asyncio`，或明确「单进程限定」 | STUB-01, 12 |
| ⚠️ P1 | GachaAgent + 卡池改为读取 `data/*.json` | STUB-06, 07, 08 |
| 📋 P2 | `VariableVM` 无 RestrictedPython 时明确拒绝或走 TavernCommand 路径 | STUB-R04 |
| 📋 P2 | `runtime_data_stream` 从 TurnContext/DB 拉取 quests/hooks | STUB-R09 |
| 📋 P2 | `config.has_lifecycle_hooks` 按插件实际能力赋值 | R-M02 |
| 📋 P2 | 记忆子系统健康端点在 UI 暴露 fallback 状态 | STUB-02 |
| 📋 P3 | muv_luv / gundam_seed 补充 tools.py + hooks.py | STUB-13, 14 |
| 📋 P3 | crossover / wuxia JSON catalogs 改为读取 `data/` | D-18, D-19 |
| 📋 P3 | 前端死字段 `inventory` / `activeSkills` 清理 | M-03 |

---

## 九、第三轮补充扫描（agents 基础设施 + web_scraper + 测试 + 前端全量 + JSON 数据文件）

### 9.1 🔴 核心功能缺失（第三轮新增 11 处）

#### STUB-T01 · gacha 状态字段孤岛 — 未接入 LangGraph

| 属性 | 值 |
|------|---|
| 文件 | `backend/agents/state.py` L156–157 / `backend/agents/graph.py` |

**问题**：`AgentState` 定义了 `gacha_pending`/`gacha_granted` 两个字段，但 `graph.py` 中**没有对应的 gacha 节点**，这些字段在图执行中永远不会被正确写入。

---

#### STUB-T02 · SessionManager 会话重命名 — 后端端点不存在

| 属性 | 值 |
|------|---|
| 文件 | `frontend/src/components/SessionManager.tsx` L55 |

```typescript
api.patch('/sessions/${id}', { title })  // 后端无此端点
```

**问题**：调用 `PATCH /sessions/{id}` 但后端 `sessions.py` 只有 `/mode`、`/character` 子路由，此调用必 404。

---

#### STUB-T03 · WorldManager 用 `'tmp'` ID 发 SSE 请求

| 属性 | 值 |
|------|---|
| 文件 | `frontend/src/components/WorldManager.tsx` L210–211 |

**问题**：在 `ensureWorldCreated` 完成前，SSE 连接用 `createdWorldId || 'tmp'` 拼 URL，向 `/worlds/tmp/fetch-lore` 发请求，世界 ID 为字面量 `"tmp"`。

---

#### STUB-T04 · test_memory_endpoints.py — 假集成测试

| 属性 | 值 |
|------|---|
| 文件 | `tests/integration/test_memory_endpoints.py` L3–58 |

**问题**：标题声称"集成测试"，实现是静态读取 `routes.py` 源码字符串检查，**完全不启动 HTTP/DB**，不验证任何运行时行为。

---

#### STUB-T05 · test_infinite_arsenal.py — 名实不符

| 属性 | 值 |
|------|---|
| 文件 | `tests/e2e/test_infinite_arsenal.py` L3–7, L135–179 |

**问题**：文档注释声称测试 `get_arsenal_inventory`/`forge_weapon`/`evaluate_weapon`/`draw_gacha` 4 个工具；实际 `test_arsenal_tools` 只调 GET character/roll/archives 等通用端点，**未调用任何一个武库工具 API**。

---

#### STUB-T06 · test_browser_e2e.py 失败不退出

| 属性 | 值 |
|------|---|
| 文件 | `tests/e2e/test_browser_e2e.py` L450–453 |

**问题**：`fail_count > 0` 时只打印警告，**不调用 `sys.exit(1)`**，CI 流水线会误判为通过。

---

#### STUB-T07~T09 · unit test P1~P5 — 静态源码测试

| 文件 | 行号 | 问题 |
|------|:----:|------|
| `tests/unit/test_p1_gacha.py` | L36–47 | 只验证注册名，不执行 `GachaAgent.execute` |
| `tests/unit/test_p4_memory.py` | L10–47 | 三个测试均只 `inspect.getsource` 搜子串 |
| `tests/unit/test_p5_dm.py` | L9–15 | 只断言 prompt 含 `"modify"` 字符串 |

**共同问题**：5 个 unit test 文件全是对源码字符串的静态检查，不启动任何服务，实现改坏测试仍可能通过。

---

#### STUB-T10 · test_round10*.py 在测试内重复业务逻辑

| 文件 | 行号 | 问题 |
|------|:----:|------|
| `tests/test_round10_quick.py` | L28–38 | 在测试内重写 tier 分类逻辑 |
| `backend/tests/test_round10.py` | L43–74 | 同样重写，与 `ExtractQueue` 实现重复 |

**问题**：实现逻辑改变时，测试内的副本不会跟着改，测试失去验证意义。

---

#### STUB-T11 · web_scraper 扩展未注册到 __registry__.json

| 属性 | 值 |
|------|---|
| 文件 | `backend/extensions/__registry__.json` / `backend/extensions/web_scraper/` |

**问题**：`__registry__.json` 列出 5 个扩展（crossover/gundam_seed/infinite_arsenal/muv_luv/wuxia），**`web_scraper` 不在其中**，UI 扩展列表不显示它，也无 `display_name`/`description` 元数据。

---

### 9.2 🟡 功能降级（第三轮新增 28 处）

#### agents 基础设施

| # | 文件 | 行号 | 退化行为 |
|---|------|:----:|---------|
| T-D01 | `extensions/rules_loader.py` | L4, L56–62 | `on_demand` trigger 规则永不注入（`build_injection_block` 只匹配 `always`） |
| T-D02 | `extensions/rules_loader.py` | L214–222 | YAML AgentProfile 未加载 `default_permission` 字段，始终用 dataclass 默认 `DENY` |
| T-D03 | `extensions/rules_loader.py` | L99–104 | PyYAML 不可用时用简易 `key: value` 解析 frontmatter，能力受限 |
| T-D04 | `agents/llm.py` | L119–124 | 找不到 `agents.json` 或 agent 未配置时硬编码 deepseek-chat 默认参数 |
| T-D05 | `agents/llm.py` | L38–44 | 仅处理 `deepseek`/`openai` provider 前缀，其它 provider 原样传字符串 |
| T-D06 | `agents/permission.py` | L74–75 | `tool_registry` 导入失败时 `_tool_groups={}`，`allowed_groups` 过滤失效 |
| T-D07 | `agents/permission.py` | L110 | 注释写「60s 超时自动允许」但 `ask_handler` 超时实为 DENY（文档漂移） |
| T-D08 | `agents/graph.py` | L82–106 | 并行 NPC/World 子 Agent 异常静默保留空列表，主链路继续 |
| T-D09 | `agents/graph.py` | L159–160 | `options_node` 失败仅 debug 日志，不报错 |
| T-D10 | `agents/graph.py` | L167–188 | 扩展 agents.py 导入失败仅 warning，不阻断建图 |
| T-D11 | `agents/agent_node.py` | L132–135 | `insert_after` 目标不在 `edge_map` 时跳过注入并 warning |
| T-D12 | `main.py` | L110–111, L116–117 | 扩展 tool/agent 注册失败 `except: pass` 静默跳过 |
| T-D13 | `main.py` | L192–197, L209–210 | `build_registry` / WorldPlugin overlay 失败时 skip |
| T-D14 | `extensions/web_scraper/tools.py` | L78–103 | 无 `session_id`/`world_id` 时不写库但返回 `ok: True` |

#### 前端 API/组件

| # | 文件 | 行号 | 退化行为 |
|---|------|:----:|---------|
| T-D15 | `lib/api.ts` | L197–198 | `deleteSession` 用裸 `fetch`，不走 `apiFetch`，失败不抛错 |
| T-D16 | `lib/api.ts` | L357–374 | `importNpcToSession`/`grantItemToSession` 已定义但**无任何 UI 调用** |
| T-D17 | `stores/story.ts` | L99–113 | `loadMessages` action **从未被任何组件调用**（死 action） |
| T-D18 | `stores/world.ts` | L71–81 | `loadNpcs` 从 archives 推导而非请求 `/npcs` 端点 |
| T-D19 | `stores/ui.ts` | L38–44, L80–83 | `theme` 只改内存，无 localStorage/后端持久化 |
| T-D20 | `components/WorldManager.tsx` | L140–158 | `worldId` prop 未用于编辑已有世界，编辑入口缺失 |
| T-D21 | `components/WorldManager.tsx` | L324–456 | 无 `api.updateWorld`，已有世界只能删不能改元数据 |
| T-D22 | `components/AssetLibrary.tsx` | — | NPC 导入/物品发放 API 存在但**无 UI 按钮入口** |
| T-D23 | `components/CharacterCreator.tsx` | L337–338 | `getCharacterTemplate`/`updateCharacterTemplate` 无 UI，模板创建后不可查看/编辑 |
| T-D24 | `components/SessionManager.tsx` | L63–71 | `handleExport` 只导出 `Session` 列表 JSON，不含 messages/parts/character |
| T-D25 | `components/InputBar.tsx` | L59–64 | `directSelectOption` 未保证父组件已 `setState` 输入框内容 |

#### 测试套件

| # | 文件 | 行号 | 退化行为 |
|---|------|:----:|---------|
| T-D26 | `tests/e2e/test_browser_e2e.py` | L340 | 记忆检索用参数 `?query=`，后端实际为 `?q=`，检索可能恒为空 |
| T-D27 | `tests/e2e/test_browser_e2e.py` | L198–322 | 多处 429/找不到元素/`session.error` 标为通过而非失败 |
| T-D28 | `tests/e2e/test_homepage_hub.py` | L194–196 | Playwright 未安装则跳过浏览器段，`exit 0`，CI 不报错 |

#### JSON 数据文件（存在但代码不读取）

| # | 文件 | 代码中的替代 |
|---|------|------------|
| T-D29（确认）| `infinite_arsenal/data/pool-catalog.json` | `tools.py` 内联 `_POOL_CATALOG`（内容与 JSON 重复） |
| T-D30（确认）| `infinite_arsenal/data/acg-source-registry.json` | `agents.py` 内联 `_ACG_ITEMS`（仅 20 条，JSON 有完整 10 个 IP + tier_caps） |
| T-D31（确认）| `crossover/data/shop-catalog.json` | `open_shop` LLM 失败时用固定「普通长剑/生命药水」 |
| T-D32（确认）| `wuxia/data/sects-catalog.json` | `tools.py` 无门派查询实现 |
| T-D33（确认）| `wuxia/data/techniques-catalog.json` | `tools.py` 无技法查询实现 |
| T-D34（新发现）| `data/sys_config/agents.json` → `memory_extract` 配置项 | `extract_queue.py` 不读 `agents.json`，用关键词启发式而非 LLM |

---

### 9.3 🟢 次要功能（第三轮新增 17 处）

| # | 文件 | 行号 | 描述 |
|---|------|:----:|------|
| T-M01 | `frontend/src/App.tsx` | 全文件 | `return null` 死组件（迁移遗留，实际入口为 `router.tsx`） |
| T-M02 | `frontend/src/router.tsx` | L42–60 | `/settings`、`/sessions` 路由重定向到 `/`，组件 `() => null` |
| T-M03 | `stores/character.ts` | L151–174 | `pushSnapshot`/`restoreSnapshot`/`clearSnapshots` 无 UI 调用 |
| T-M04 | `stores/dice.ts` | 全文件 | 仅内存 history，不调 `api.getDiceHistory` 持久同步 |
| T-M05 | `lib/api.ts` | L215–237 | 6 个死 API 方法（`listWorldPlugins`/`listAgentProfiles`/`listWritingStyles`/`listMcpServers`/`mcpConnect`/`mcpDisconnect`）全局无引用 |
| T-M06 | `extensions/web_scraper/__init__.py` | 全文件 | 空文件，无包级导出 |
| T-M07 | `agents/state.py` | L24 | `_last = operator.attrgetter` 定义后未使用 |
| T-M08 | `agents/graph.py` | L129–130 | `on_chapter_end` hook 失败 `pass` |
| T-M09 | `agents/graph.py` | L132–133 | `chronicler_wrapper` 有不可达 `return ctx` |
| T-M10 | `agents/llm.py` | L24–25 | `dotenv` 缺失 `except ImportError: pass` |
| T-M11 | `main.py` | L168–173 | 只打印 rule_registry 规则数量，无其它 stub |
| T-M12 | `tests/test_live_generation.py` | L176–223 | 各用例 `try/except` 吞失败只 append errors，无 assert，需人工看控制台 |
| T-M13 | `tests/unit/test_p3_parttype.py` | L43–45 | `play.yaml` 缺失则 `pytest.skip`，配置可能长期不验证 |
| T-M14 | `stores/story.ts` | L4 | 注释写「虚拟滚动」，实现为普通 `map` |
| T-M15 | `components/MessageThread.tsx` | L4 | 同上，注释「虚拟滚动」未实现 |
| T-M16 | `extensions/__registry__.json` | — | `muv_luv` 无 `display_name` 字段（loader 靠目录名） |
| T-M17 | `data/sys_config/agents.json` | — | `memory_extract` 配置项永不被 `extract_queue.py` 读取（但文件整体有用） |

---

### 9.4 JSON 数据文件利用情况对照（全量）

| 文件 | 内容丰富度 | 代码是否读取 | 影响 |
|------|:----------:|:-----------:|------|
| `infinite_arsenal/data/pool-catalog.json` | 3 池完整权重+保底 | ❌ 代码内联 `_POOL_CATALOG` | 卡池改动需改两处 |
| `infinite_arsenal/data/acg-source-registry.json` | 10 个 IP + tier_caps | ❌ GachaAgent 用 20 条硬编码 | ACG 来源库形同虚设 |
| `crossover/data/shop-catalog.json` | 4 类 12 商品 | ❌ open_shop 失败用固定兜底 | 商店体验完全靠 LLM |
| `crossover/data/character-template.json` | 角色模板 | ⚠️ 未确认（待查） | — |
| `crossover/data/world-registry.json` | 世界注册表 | ⚠️ 未确认（待查） | — |
| `wuxia/data/sects-catalog.json` | 5 门派完整数据 | ❌ tools.py 无查询实现 | 门派系统不可用 |
| `wuxia/data/techniques-catalog.json` | 9 个武功/内功 | ❌ tools.py 无查询实现 | 武功系统不可用 |
| `data/sys_config/agents.json` | 10 个 Agent 完整配置 | ✅ llm.py 读取 | memory_extract 项死配置 |
| `data/sys_config/mcp.json` | MCP 服务器配置 | ✅ main.py 读取 | — |
| `data/sys_config/scraper_rules.json` | 爬虫规则 | ✅ web_scraper/tools.py + API 读取 | 萌娘/百度 disabled |
| `extensions/__registry__.json` | 5 个扩展元数据 | ✅ extension_loader.py 读取 | web_scraper 缺失 |

---

### 9.5 已确认无占位的文件（第三轮）

以下文件通读后确认为完整实现：

| 文件 | 说明 |
|------|------|
| `lib/bindSSEToStores.ts` | SSE 路由，12 个事件类型全部处理 |
| `lib/idb.ts` | IndexedDB 缓存层，CRUD + SSE cursor 持久化 |
| `lib/sse.ts` | SSE 客户端，心跳/指数退避/Last-Event-ID |
| `agents/ask_handler.py` | `asyncio.Event` 阻塞等待，超时 DENY，已实现 |
| `agents/graph.py`（主链路）| 完整连通，无孤立节点 |
| `extensions/web_scraper/tools.py`（主链路）| 真实抓取 + LLM 提炼 + 写库 |
| `prompts/core_prompts.py` | Layer0/1 片段注册完整 |
| `hooks/hook_manager.py` + `builtin_hooks.py` | 真实注册与分发 |
| `bus/event_bus.py`、`sse_adapter.py` | 订阅/重放/SSE 完整 |
| `engine/combat.py`、`dice.py`、`psyche.py` | 完整算法实现 |

---

## 十、合并优先修复建议（三轮完整版）

| 优先级 | 问题 | 对应条目 |
|:------:|------|---------|
| 🚨 P0 | `sessions.py` fork NPC 列名 `npc_key` → `key` | STUB-R01 |
| 🚨 P0 | `SessionManager` 补充后端 `PATCH /sessions/{id}` 端点 | STUB-T02 |
| 🚨 P0 | `WorldManager` 确保世界创建后再连接 SSE | STUB-T03 |
| 🚨 P0 | Rules/DM Agent 失败改为 `block`，禁止 silent pass | STUB-03, D-01 |
| 🚨 P0 | 权限检查失败从 fail-open 改为 fail-closed | D-16 |
| 🚨 P0 | muv_luv / gundam_seed Prompt fragments 格式修复 | STUB-04, 05 |
| ⚠️ P1 | `test_browser_e2e.py` 失败时 `sys.exit(1)` | STUB-T06 |
| ⚠️ P1 | `test_memory_endpoints.py` 改为真实 HTTP 集成测试 | STUB-T04 |
| ⚠️ P1 | `test_browser_e2e.py` 记忆查询参数 `?query=` → `?q=` | T-D26 |
| ⚠️ P1 | `prompt_assembler` 失败时抛错，非返回空 prompt | STUB-R03 |
| ⚠️ P1 | 补充 `utils/llm_client` + `db/queries`，解锁全量记忆栈 | STUB-R05~R08 |
| ⚠️ P1 | GachaAgent 改为读取 `data/pool-catalog.json` + `acg-source-registry.json` | STUB-06~08 |
| ⚠️ P1 | `graph.py` 添加 gacha 节点或移除孤立 state 字段 | STUB-T01 |
| ⚠️ P1 | `rules_loader` 实现 `on_demand` trigger 注入；加载 `default_permission` | T-D01, T-D02 |
| 📋 P2 | `VariableVM` 无 RestrictedPython 时明确拒绝 | STUB-R04 |
| 📋 P2 | `runtime_data_stream` 从 DB 拉取 quests/hooks | STUB-R09 |
| 📋 P2 | `crossover` 商店 + `wuxia` 门派/武功改为读取 `data/` JSON | T-D29~T-D33 |
| 📋 P2 | Redis 总线填充 `redis.asyncio` | STUB-01 |
| 📋 P2 | `web_scraper` 扩展写入 `__registry__.json` | STUB-T11 |
| 📋 P3 | muv_luv / gundam_seed 补充 tools.py + hooks.py | STUB-13, 14 |
| 📋 P3 | `AssetLibrary` 添加 NPC 导入/物品发放 UI 入口 | T-D22 |
| 📋 P3 | `WorldManager` 实现世界元数据编辑 | T-D21 |
| 📋 P3 | 清理死 API 方法、死 store 字段、`App.tsx` 空组件 | T-M01~T-M06 |

---

*报告由 Cursor AI 自动生成（三轮全量扫描，2026-06-02）。如需针对某具体模块输出修复方案，可在对话中指定。*
