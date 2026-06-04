---
id: "npc-dialogue"
name: "npc-dialogue"
display_name: "NPC 深度对话专项规则"
phases: ["p3"]
trigger: "on_demand"
priority: 59
role: "user"
inject_as: "prefix"
source: "zero-arsenal-core"
condition: null
agent_filter: ["narrator_agent", "npc_agent"]
token_estimate: 880
version: "1.0.0"
description: "NPC 对话的信息不对称、性格一致性、感知边界与对话格式约束。"
requires: []
conflicts: []
tags: ["narrative", "npc", "dialogue", "consistency"]
applicable_worlds: []
---

# NPC 深度对话专项规则

## 决策图（Decision Gate）

```mermaid
flowchart TD
    A[NPC 出场/开口] --> B[query_npc_profile 取档案]
    B --> C{档案是否存在?}
    C -->|否| NEW[spawn_npc 先建档再发言]
    C -->|是| D[get_npc_knowledge_scope 取知/不知]
    NEW --> D
    D --> E{该 NPC 此刻掌握什么信息?}
    E --> F[据 knows/blind_spots 框定可说内容]
    F --> G{有感知行为?}
    G -->|是| H{满足感知触发条件?}
    G -->|否| I[按性格生成台词]
    H -->|否| J[降级：不可感知，改为普通观察]
    H -->|是| I
    J --> I
    I --> K[对话后必要时 update_npc_state]
```

## 铁律 [HARD-GATE]

- [ ] **信息依据**：NPC 的每个判断/态度都要能回答「他此刻掌握了什么具体信息支撑此行为」；无依据则不成立。
- [ ] **不知不说**：NPC 不得知晓主角未透露的信息（对照 `knowledge_scope.blind_spots`）。
- [ ] **能力封顶**：NPC 的感知/技能不得超出其 `capability_cap`；静默收敛的对手不能被无特殊感知者「感应」到。
- [ ] **性格守恒**：台词措辞符合其教育/文化背景与 `core_values`；核心价值观无铺垫不得颠覆。
- [ ] **标签后置**：说话者标注在对话后或内部，禁止「他说道：」前置式。

## 执行流程

1. **取档案**：`query_npc_profile` 读 `psyche_model_json`（core_values / knowledge_scope / capability_cap / behavior_patterns）。
2. **缺档处理**：无档案先 `spawn_npc` 建档，不得凭感觉直接开口。
3. **框定信息**：`get_npc_knowledge_scope` 确认 knows / blind_spots，据此裁剪 NPC 可表达内容。
4. **感知校验**：若 NPC 做出「察觉气势/杀意」类行为，先核对感知触发条件（主动释放 / 能力外泄 / 有专项感知）；不满足则降级为普通微表情观察。
5. **生成与回写**：按性格与情绪状态产出台词；若本轮 NPC 认知/信任发生变化，`update_npc_state` / `edit_npc_state` 回写。

## 集成说明

- **角色系统**：NPC 档案存于 `psyche_model_json`；主角状态用 `query_character_summary` 交叉确认信息不对称。
- **信息矩阵**：knows/blind_spots 对应信息不对称矩阵；对话不得越过矩阵约束。
- **NPC 子会话**：深度对话可由 `npc_agent` 接管，本 Skill 的边界规则对子会话同样生效。
- **记忆系统**：关系/信任变化由 Calibrator 写入，跨章对话须保持连续。

## 禁词与风格约束

- 禁「语气温柔地」「眼中闪过一丝……」等贴标签式心理直述。
- 禁「瞳孔地震」「破防」等网络梗。
- 长对话（>3 行）后必须插入一处动作或环境描写，避免对话悬空。
