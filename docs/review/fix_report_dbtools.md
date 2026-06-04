# 修复报告 — DB/SCHEMA + TOOLS + BUS + 持久化层

> 范围：`backend/db`、`backend/tools`、`backend/bus`、`backend/api`（限相关写入/持久化路径）。
> 决策遵循 D8=A（当前无存量数据，可对全表自由添加 CHECK/FK 约束）。
> 未触碰 `docs/FIX_VERIFICATION_2026-06.md`。`schema.py` 中新增的 `node_sync_status` 表已保留。
> 日期：2026-06-04

## 一、自检结果（全部通过）

| 检查项 | 命令 | 结果 |
|---|---|---|
| 语法编译 | `python -m py_compile`（9 个编辑文件） | ✅ EXIT=0 |
| 核心导入 | `python -c "import backend.db.connection, backend.tools.registry, backend.bus.event_bus"` | ✅ `IMPORTS_OK` |
| 扩展加载（ToolDef） | `python -c "from backend.tools.registry import tool_registry"` | ✅ `TOOLS_LOADED=59`，**无** `world_plugin`/`display_name`/`Failed to load` 报错 |
| 编辑模块导入 | `import sessions, builtin_tools, rate_limit` | ✅ `EDITED_MODULES_IMPORT_OK` |
| init_db 烟测 | 临时库 `set_db_path`+`init_db` | ✅ 22 张表建成（含 `node_sync_status`）；`foreign_keys=1`；`foreign_key_check` 0 违规；CHECK 拒绝非法值（`IntegrityError`） |
| 角色 v4 烟测 | `validate_character` / `migrate_v3_to_v4` | ✅ `jsonschema=True`；默认卡/迁移卡 valid=True；坏卡 valid=False（5 处错误） |

init_db 烟测建表清单：
```
chapter_anchors, chapters, character_cards, character_snapshots, character_templates,
dice_log, event_log, item_templates, memory_entries, message_parts, messages,
node_sync_status, npc_profiles, npc_templates, prompt_templates, schema_version,
session_npc_states, sessions, vector_index_meta, world_archive_entries,
world_archives, worlds
```

## 二、修复项明细

| 项 | 编号 | 状态 | 证据（file:line） | 备注 |
|---|---|---|---|---|
| ToolDef kwargs 导入崩溃 | conf_b07 | ✅ | `backend/tools/registry.py:119-120`（新增 `display_name`/`world_plugin` 字段） | 扩展 `tools.py` 传入这两个 kwarg 不再触发 `TypeError`；烟测 59 工具全载入 |
| 工具结果契约标准化 | conf_b07 | ✅ | `backend/tools/registry.py:50`（`ToolResult`）、`:80`（`normalize_result`） | `execute()` 统一经 `normalize_result` 归一化为 dict |
| 工具反注册 | conf_b07 | ✅ | `backend/tools/registry.py:186`（`unregister`） | 支持热卸载 |
| MCP 重试 + 反注册 | conf_b07 | ✅ | `backend/tools/mcp_bridge.py:104-105`（退避参数）、`:127`（重试循环）、`:159`（`unregister_from_registry`） | 网络/5xx 退避重试至多 3 次；4xx 不重试 |
| CHECK + FK ON DELETE 全表约束 | D8 | ✅ | `backend/db/schema.py`（共 43 处 `CHECK(`/`ON DELETE`） | `foreign_key_check` 0 违规；CHECK 拒非法值已烟测 |
| 角色卡 v4 schema/校验/迁移 | D7 | ✅ | `backend/db/character_v4.py:79`（schema）、`:348`（默认卡）、`:517`（校验）、`:546`（v3→v4） | `jsonschema` 可用时走严格校验，否则回退手工校验 |
| v4 校验接入写入路径 | D7 | ✅（核心入口） | `backend/api/routers/sessions.py:104-130`（`create_session` 迁移+校验+回退并记日志） | 见「四、需父级跟进」对其余写入入口的清单 |
| init_db fail-loud | NEW-C7-08 | ✅ | `backend/db/connection.py:46`（说明）、`:59`（幂等忽略）、`:64-69`（致命错误抛出） | 良性错误（already exists/duplicate column）幂等忽略；语法/约束错误抛出 |
| 限速器空闲桶淘汰 | NEW-C7-01 | ✅ | `backend/api/middleware/rate_limit.py:35`（TTL/上限）、`:109`（`_sweep_idle_buckets`）、`:102`（`_get_bucket` 显式建桶） | 改用显式 get-or-create + 周期清扫 + 硬上限，防伪造 IP 撑爆内存 |
| X-Forwarded-For 受信代理 | NEW-C7-02 | ✅ | `backend/api/middleware/rate_limit.py:31`（`_TRUSTED_PROXIES`）、`:94-100`（仅受信对端采信 XFF） | 默认空集=不信任任何 XFF，杜绝伪造 IP 绕过限速 |
| 事件总线持久化复用连接 | NEW-C7-09 | ✅ | `backend/bus/event_bus.py:99`（`_enqueue_persist`）、`:125`（`_persist_worker` 批量复用连接） | 由每事件新开连接 → 单后台 worker 批量提交（最多 100 条/批）；失败计数+日志 |
| 订阅生命周期/计数 | NEW-C7-04 | ✅ | `backend/bus/event_bus.py:182-188`（退订后清空键）、`:285-289`（`close` 幂等） | `_subscribers` 不再随 SSE 断连无界增长，`get_subscriber_count` 精确 |
| NPC 存储单一源 | NEW-C11-01/02 | ✅ | `backend/tools/builtin_tools.py:263`（说明）、`:268`（`_lookup_npc_row`）、`:295`/`:312`/`:338`（query/scope/update 统一读写 `npc_profiles`） | 消除 `world_archives` 与 `npc_profiles` 双存储分裂；`get_npc_knowledge_scope` 无档案时返回 `found:False`（D-13，不伪造边界） |
| 快照恢复 fail-loud | NEW-C6-04 | ✅ | `backend/api/routers/sessions.py:979-1008`、`:1079`（返回真实 `character_state_restored`） | 取消静默 `except: pass`；异常抛 500；按 `rowcount` 判定真实恢复 |
| create_world_archive 字段错位 | NEW-C6-05 | ✅ | `backend/api/routers/sessions.py:1152-1160` | `world_key` 不再误用 `archive_type`，会话内档案 `world_key` 留空 |

## 三、编辑文件清单

```
backend/tools/registry.py
backend/tools/mcp_bridge.py
backend/db/schema.py
backend/db/connection.py
backend/db/character_v4.py
backend/api/routers/sessions.py
backend/tools/builtin_tools.py
backend/api/middleware/rate_limit.py
backend/bus/event_bus.py
```

## 四、需父级/超出本次范围跟进的事项

1. **D7 校验接入其余写入入口**：`create_session`（sessions.py:104-130）已接入 v4 迁移+校验。其余写角色卡的入口建议同样接入 `migrate_v3_to_v4`+`validate_character`：
   - `backend/api/routers/characters.py`（角色卡 PUT/PATCH 更新接口，若存在直接写 `character_cards.data_json` 的路径）。
   - 各世界扩展的角色默认卡生成器（`backend/extensions/<world>/...`，若其默认卡仍为 v3 结构）——这些适配器位于世界插件目录，超出 DB/TOOLS/BUS 范围，需父级逐插件适配为 v4。
2. **RedisEventBus 的订阅计数/泄漏**：`backend/bus/redis_bus.py` 为独立实现，其 `get_subscriber_count` 与跨进程订阅生命周期不在本次内存 `EventBus` 修复范围内，建议单独评审。

## 五、临时烟测脚本

`_smoke_init.py`、`_smoke_char.py` 为本次验证使用的临时脚本，位于仓库根，可在确认后删除（非交付物）。
