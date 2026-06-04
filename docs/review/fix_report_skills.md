# Fix Report — 预置 Skill 落地（D16 + D17）

> 范围：仅新增 SKILL.md 技能定义文件（`**/skills/**`）。未改动 loader / tools / agents / frontend / docs（本报告除外）/ pyproject。
> 关联缺口：`docs/review/conf_b05.md` §3.4「设计预置 8 个 Skill 目录不存在，`backend/skills/` 无 SKILL.md」、§5.2「正文五节结构无任何文件遵循」。

## 1. 新建的 8 个 Skill

| skill | path | format-complete? | note |
|---|---|---|---|
| combat-narration | `backend/skills/combat/combat-narration.md` | ✅ 是 | 战斗叙事；五节齐全（决策图/铁律/执行流程/集成说明/禁词）；引用 roll_check/apply_damage/earn_sp_by_kill 与真实 verdict 枚举 |
| shop-evaluation | `backend/skills/economy/shop-evaluation.md` | ✅ 是 | 商店买卖三轮物理剥离定价；引用 open_shop/get_player_points/evaluate_item/purchase_item |
| chapter-opening | `backend/skills/narrative/chapter-opening.md` | ✅ 是 | 章节开篇承接/时间锚定/视角盲区；引用 get_chapter_summaries/search_memory/read_chapter |
| npc-dialogue | `backend/skills/narrative/npc-dialogue.md` | ✅ 是 | NPC 信息不对称与感知边界；引用 query_npc_profile/get_npc_knowledge_scope/spawn_npc/update_npc_state |
| breakthrough | `backend/skills/cultivation/breakthrough.md` | ✅ 是 | 境界突破/进化上限封顶；引用 read_character/roll_check/update_character_state，含 A/B/C/D 能力分级铁律 |
| world-transition | `backend/skills/meta/world-transition.md` | ✅ 是 | 穿越/跨界世界键切换；引用 get_world_state/update_world_state/search_lore + `<system_grant type="world_traverse">` |
| item-appraisal | `backend/skills/economy/item-appraisal.md` | ✅ 是 | Anti-Feat 星级 + 功能维度降级算法；引用 search_lore/evaluate_item/evaluate_weapon |
| gacha-resolution | `backend/skills/system/gacha-resolution.md` | ✅ 是 | 抽卡落点解析 + 真实 ACG 发货 + 重复溢出；引用 draw_gacha/get_player_points/evaluate_weapon；`applicable_worlds: [crossover, infinite_arsenal]` |

8 个均为完整、可端到端使用的真实用例（非桩），对应设计 `05-prompt-architecture.md` §3.4 的预置 Skill 清单（行 781–790），是世界无关的核心层 Skill。

## 2. 采用的 SKILL.md 格式（D17）

格式权威为 `docs/design/05-prompt-architecture.md` §5（项目无 `05-skill-system.md`，技能格式由 05-prompt-architecture 承载；§04-extension-system §2.3 为补充）。

**Frontmatter 字段**（全部 8 文件一致）：
- 设计 §5.1 必填：`id` / `name` / `phases` / `trigger` / `priority` / `role` / `inject_as` / `source`
- 设计 §5.1 选填：`condition` / `agent_filter` / `token_estimate` / `version` / `description` / `requires` / `conflicts` / `tags`
- loader 专用：`applicable_worlds`（世界过滤，`[]` = 全局）、`display_name`（人类可读中文名）

**正文五节**（设计 §5.2，逐文件齐全）：
1. 决策图（Decision Gate）— Mermaid `flowchart TD`
2. 铁律 [HARD-GATE] — checklist
3. 执行流程 — 带工具调用的 step-by-step
4. 集成说明 — 与骰子/经济/记忆/世界插件/链路 B 的对接点
5. 禁词与风格约束 — 在全局禁词上叠加

## 3. 与 loader 期望的一致性核验

**loader 代码**：`backend/tools/skill_loader.py`（未改动）。`main.py:62` 将 `SKILLS_DIR = backend/skills/` 注册进 `skill_registry`，`discover()` 用 `rglob("*.md")` 递归扫描——因此 `backend/skills/<子目录>/*.md` 会被发现（与设计的 `skills/combat/…`、`skills/economy/…` 子目录布局一致）。

**loader 解析的 frontmatter key**：`name`(身份键，回退 path.stem) / `description` / `trigger`(默认 on_demand) / `phases`(默认 [p3]) / `priority`(默认 100) / `condition` / `inject_as`(默认 user) / `applicable_worlds`。其余设计字段（id/role/source/version/requires/conflicts/tags/agent_filter/token_estimate/display_name）经 `yaml.safe_load` 解析后被忽略，不会报错。

**身份键取舍（诚实说明）**：loader 以 `name` 作为 `_skills` 字典键，而设计 §5.1 把 `name` 定义为「人类可读中文名」、`id` 为唯一标识。二者直接冲突。仓库现有 6 个技能文件（如 `crossover/skills/combat_crossover.md`）的既成约定是 **`name` = 标识符**。为同时满足「可被 loader 正确发现/keying」「可被 `load_skill(skill_name=...)` 稳定调用」「贴合现有约定」，本次取 `name == id == 短横线标识符`，并新增 `display_name` 承载设计 §5.1 的中文可读名。这是对「loader 实测优先」与「设计 §5.1」的折衷，已如实记录。

**实跑核验**（只读，未改任何代码）：

```
SkillRegistry().add_skill_dir(Path('backend/skills')); discover()
→ list_skills() 返回全部 8 个，name/trigger/phases/priority 解析正确
→ load_skill_content('combat-narration') 正常剥离 frontmatter 返回正文（# 战斗叙事专项规则 ... mermaid）
```

8 个 name 互不重复，无 keying 冲突；文件均为 UTF-8（loader 以 `encoding="utf-8"` 读取，YAML 解析成功）。

## 4. 无法完全确认 / 取舍项（诚实记录）

- **注入层级**：`load_skill` 工具（`builtin_tools.py:472`）将内容注入为 runtime 层 `priority=420`，而非设计 Layer 3 的 50–79；本次只写 Skill 定义，未触碰该接线（属 loader/工具侧，超出本次范围）。frontmatter 的 `priority`(57–64) 按设计 Layer 3 区间填写，供 loader 排序使用。
- **inject_as 取值**：采用设计 §5.2 的 `prefix`（loader 注释建议 system|user）。loader 不校验该字段、不影响发现与注入包装，故保留设计取值以符合 D17「完整设计格式」。
- **trigger=on_demand**：8 个均为按需加载（与设计 Layer 3 一致），因此不会被 `get_active_skills` 自动激活，需由 DM/`load_skill` 触发——这是设计预期行为，非缺陷。
- **`condition` 安全性**：loader 对 `condition` 仍用裸 `eval`（`def_c11` NEW-C11-08 已记录）；本次所有 Skill 的 `condition: null`，不触发该路径。
