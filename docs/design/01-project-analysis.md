# 01 · 现有项目分析与统合策略

> **文档版本**：v1.0 · 2026-05-31  
> **适用项目**：zero-arsenal  
> **作者**：架构分析组  
> **状态**：基线锁定，后续每次重大架构决策后更新

---

## 1. 项目概览表

| 项目 | 类型 | 技术栈 | 核心定位 |
|---|---|---|---|
| **ai-vn-game-system** | 后端叙事管线 | Node.js 18 + Express + SQLite | 四阶段流式叙事引擎，SillyTavern 协议兼容层 |
| **ai-vn-system-backend** | 后端多Agent编排 | Python 3.11 + FastAPI + LangGraph + SQLite WAL | 5-Agent 协同写作后端，四层混合记忆系统 |
| **MoRanJiangHu** | 纯前端游戏 | React 19 + TypeScript + Vite | 132模块提示词框架，多阶段AI桥接，GitHub同步 |
| **noveldemo** | 轻量Agent原型 | Python 3.10 + roller.py + JSONL | 确定性骰子+OCEAN心理+部位HP的Agent-first系统 |
| **opencode** | AI开发工具 | TypeScript monorepo + Bun | Plugin Hook体系，MCP一等公民，Part状态机，SSE总线 |
| **pi** | Agent框架 | TypeScript + jiti + JSONL | Agent loop + Extension系统 + 会话分支树 |
| **superpowers** | 方法论文档 | SKILL.md + Markdown | 工作流决策图，HARD-GATE铁律，OpenCode插件模式 |

---

## 2. 各项目深度分析

### 2.1 ai-vn-game-system

**定位**：Node.js 后端叙事引擎，专注于**可流式化的四阶段叙事管线**，与 SillyTavern 保持协议兼容。

#### 核心优势

1. **四阶段叙事管线设计成熟**：P1（Planner 规划叙事骨架）→ P2（RAG 记忆注入）→ P3（流式叙事输出）→ P4（变量回写）形成完整的单回合闭环，各阶段职责单一，错误隔离清晰。
2. **NarrativeGrant 异步旁路**：对于"授予能力/物品/世界穿越"等需要系统级副作用的场景，通过旁路 `<system_grant>` XML 标签异步触发，不阻塞主叙事流，是解决叙事与系统结算解耦的经典方案。
3. **VM 沙箱变量脚本**：使用 Node.js `vm` 模块运行不信任的变量更新脚本，提供基础沙箱隔离，支持动态计算`hp += roll(2,d6)`等表达式而不污染主进程。
4. **多世界时间流速**：每个世界配置独立的 `time_multiplier`，支持"1现实秒=N游戏分钟"的异构时间线并行，为多世界小说系统奠定了设计模型。
5. **SillyTavern 协议兼容**：兼容 SillyTavern 的角色卡格式和 API 协议，使现有大量社区资产（角色卡/提示词/插件）可直接接入，降低冷启动成本。

#### 核心劣势

1. **Node.js 生态在向量记忆上薄弱**：Python 的 LangChain/ChromaDB/FAISS 生态远优于 Node.js 同类，混合检索（向量+BM25+图扩散）在 JS 里实现成本极高。
2. **单进程 Express 难以承载复杂 Agent 并发**：多 Agent 并行执行（如 NPCAgent ‖ WorldAgent）在 Node.js 事件循环里需要精心管理 Promise，LangGraph 的有向图调度远更自然。
3. **变量 VM 沙箱安全性有限**：`node:vm` 不是真正的沙箱，已知可以通过原型链逃逸，生产环境需要替换为更严格的方案（如独立进程+IPC）。
4. **没有 purity_check / 风格自检**：叙事输出质量只依赖提示词工程，没有程序层面的风格违规检测机制。
5. **测试覆盖薄弱**：管线各阶段高度依赖 LLM 输出，单元测试难以覆盖核心路径，回归成本高。

#### 关键技术亮点（可复用的设计）

- **四阶段 P1-P4 管线架构**：与语言无关，可直接移植为 LangGraph 的四个节点序列
- **NarrativeGrant `<system_grant>` XML 旁路机制**：解耦叙事与系统副作用的核心设计
- **多世界时间流速模型**：`WorldConfig.time_multiplier` 字段设计
- **SillyTavern 角色卡 Schema**：作为 NPC 档案格式的参考输入来源

#### 不可复用的部分

- Express 中间件栈（语言绑定）
- Node.js `vm` 沙箱（移植为 Python RestrictedPython）
- npm 生态依赖（`better-sqlite3`、`tiktoken-node` 等）

---

### 2.2 ai-vn-system-backend

**定位**：目前最完整的**生产级多Agent写作后端**，是 zero-arsenal 后端的最直接参考原型。

#### 核心优势

1. **5-Agent 有向图协作**：DM（主控/门禁）→ NPC（人物驱动）→ World（世界状态）→ Style（文风审查）→ Chronicler（存档归纳）五个 Agent 各司其职，LangGraph 图结构保证执行顺序和并发分支的确定性。
2. **四层混合记忆子系统**：向量召回（65%权重，ChromaDB）+ Bigram 关键词（35%权重）+ 图扩散（关系网络漫步）+ 认知分区（近期/重要/世界分桶）。这是目前所有现有项目里最接近生产质量的记忆系统。
3. **SQLite WAL 模式**：Write-Ahead Logging 保证了写不阻塞读，多 Agent 并发写入时不会死锁，适合频繁的章节存档场景。
4. **purity_check 程序化风格审查**：在 Style Agent 节点对叙事输出执行关键词/句式检测，是将"文风铁律"从文档规范转化为可执行代码的唯一现有实现。
5. **FastAPI + Pydantic**：类型安全的 REST API，自动生成 OpenAPI 文档，Pydantic 模型作为 Agent 间数据契约，减少运行时类型错误。

#### 核心劣势

1. **与特定小说项目强耦合**：数据库 Schema、Agent 提示词、NPC 档案格式深度绑定具体世界设定，抽象层薄弱，移植到新项目需要大量重构。
2. **无骰子/规则引擎集成**：系统中不存在确定性随机机制，所有数值变化均依赖 LLM 自由输出，可复现性差。
3. **前端完全缺失**：只有后端 API，没有配套 UI，调试只能通过 curl/Postman。
4. **Agent 间消息格式不统一**：各 Agent 的输入输出在不同版本里出现过格式漂移，缺少统一的 `MessagePart` 规范。
5. **部署复杂度高**：依赖 ChromaDB 服务、Python 虚拟环境、LangGraph 服务端等多个组件，本地开发环境搭建成本较高。

#### 关键技术亮点（可复用的设计）

- **整个 `memory/` 子系统**：四层混合召回的完整实现，可作为独立模块移植
- **LangGraph 图结构定义**：Agent 节点、条件边、并行分叉的定义方式
- **purity_check 函数**：Style Agent 的风格违规检测逻辑
- **SQLite WAL + `chapter_anchors` 表设计**：章节存档的增量写入模式
- **AgentProfile 权限概念**：限制不同 Agent 可以调用哪些工具的访问控制思路

#### 不可复用的部分

- 特定世界的提示词（需要参数化重写）
- 硬编码的 NPC 关系图（需要泛化为配置驱动）
- ChromaDB 具体客户端代码（可选择迁移至 SQLite-vec 降低运维复杂度）

---

### 2.3 MoRanJiangHu

**定位**：**规模最大的纯前端 AI 游戏实现**，验证了"全部状态驻留前端 + 多阶段独立 AI 调用"的可行性上限。

#### 核心优势

1. **132 个 TypeScript 提示词模块**：每个模块是独立的 `.ts` 文件，导出标准化的提示词构建函数，形成了目前最完整的提示词工程模块库。关卡、角色、世界、战斗、心理各维度均有覆盖。
2. **TavernCommand DSL**：自研的 DSL 语言，允许在提示词文本中嵌入 `[ROLL_DICE:2d6+3]`、`[SET_VAR:hp=45]`、`[TRIGGER_EVENT:combat_start]` 等指令，运行时解析执行，是"提示词即程序"理念的实践。
3. **多独立 AI 阶段**：将一次游戏回合拆分为多个独立的 `fetch` AI 调用（规划→生成→审查），每阶段使用不同的系统提示，避免单个超长对话的上下文污染。
4. **GitHub 同步**：使用 GitHub API 将游戏存档直接存储为仓库文件，实现了无后端的云存储方案，适合快速原型验证。
5. **React 19 + 并发特性**：大量使用 `useTransition`、`Suspense`，在 1800+ 文件的大型项目中保持了相对流畅的 UI 响应。

#### 核心劣势

1. **纯前端架构的安全天花板**：API Key 暴露在客户端，无法做任何需要后端权限的操作（如服务端骰子验证、防作弊），这是设计上的根本限制。
2. **状态管理复杂度爆炸**：1800+ 文件中大量 Zustand store 互相依赖，修改一处常引发连锁更新，维护成本极高。
3. **无真正的记忆子系统**：依赖 localStorage + 简单的对话历史拼接，没有向量检索，长篇故事的上下文质量随篇幅下降。
4. **132 个模块之间缺乏统一测试**：提示词模块几乎无自动化测试，行为验证全靠手动游玩，回归困难。
5. **TypeScript 提示词模块对跨语言项目不可直接复用**：需要移植到 Python 字符串模板或 Jinja2。

#### 关键技术亮点（可复用的设计）

- **提示词模块化的分类方式**：角色/世界/战斗/心理各维度的分层组织思路
- **TavernCommand DSL 语法设计**：`[COMMAND:参数]` 内联指令格式，可在 Python 中重新实现解析器
- **多阶段独立 AI 调用的分段设计**：每阶段明确的输入输出契约
- **37+ 文风库的具体文风规则内容**（Markdown 格式，语言无关）

#### 不可复用的部分

- TypeScript/React 组件（语言绑定）
- Zustand store 设计（状态管理库绑定）
- GitHub 存档 API 调用（替换为后端 SQLite）
- 1800+ 文件的整体项目结构（过于特定化）

---

### 2.4 noveldemo

**定位**：**最轻量的 Agent-first 原型**，核心价值在 `roller.py` 确定性骰子引擎和 OCEAN 心理模型实现。

#### 核心优势

1. **roller.py 确定性骰子引擎**：d10 骰池机制，给定相同 seed 产生完全相同的结果，通过 `RollResult` 对象记录完整掷骰过程（每粒骰子的值、是否成功、累积成功数），支持 JSONL 审计追踪。这是**所有现有项目里唯一真正解决确定性随机问题的实现**。
2. **部位 HP 系统**：将角色生命值拆分为头部/躯干/四肢等独立部位，每部位独立 HP + 伤害阈值，战斗结果不再是"扣总血"的简化，而是有位置语义的真实伤害系统。
3. **OCEAN 心理模型（五大人格）**：用 O(开放性)/C(尽责性)/E(外向性)/A(宜人性)/N(神经质) 五维数值描述 NPC 性格，每次 NPC 行为由骰子+OCEAN 共同决定，保证心理一致性且可量化。
4. **JSONL 审计日志**：每次掷骰、状态变更、Agent 调用均追加写入 `.jsonl` 文件，可完整回放任意历史状态，对调试和内容审计极其有价值。
5. **Agent-first 极简架构**：整个系统不到 2000 行 Python，依赖极少，可在任何 Pi 运行时上直接启动，是验证新机制的理想沙盒。

#### 核心劣势

1. **依赖 Pi 运行时**：设计上假设运行在 Pi 的 Extension 系统之上，独立运行需要额外适配层。
2. **无前端 UI**：纯命令行交互，调试体验差，无法展示给非开发者。
3. **单 Agent 串行执行**：没有并发 Agent 协作，所有逻辑顺序执行，无法利用多 Agent 并行提速。
4. **无向量记忆**：状态仅存在于 Python 对象和 JSONL，没有语义检索能力，长篇内容质量受限。
5. **骰子引擎与叙事引擎未整合**：roller.py 作为独立模块存在，如何将掷骰结果自然地融入叙事输出（"你掷出了3个成功，GM描述..."）没有完整实现。

#### 关键技术亮点（可复用的设计）

- **`roller.py` 完整实现**：可直接复制为 zero-arsenal 的 `engine/dice.py`
- **`RollResult` 数据结构**：掷骰结果的完整记录格式
- **OCEAN 五维心理模型的数值定义**：心理驱动行为的量化公式
- **部位 HP 的 `BodyPart` 枚举和伤害计算函数**
- **JSONL 审计追加写入模式**：`append_jsonl(path, record)` 通用函数

#### 不可复用的部分

- Pi 运行时绑定代码（替换为 FastAPI 适配层）
- 特定场景的提示词硬编码（参数化重写）

---

### 2.5 opencode

**定位**：**架构参考标杆**，TypeScript monorepo，展示了生产级 AI 开发工具的插件体系、Part 状态机和 SSE 总线的完整实现。不直接复用代码，仅学习架构设计。

#### 核心优势

1. **Plugin Hook 体系**：`tool.execute.before`、`tool.execute.after`、`chat.messages.transform`、`session.init` 等钩子形成完整的插件生命周期，第三方插件无需修改核心代码即可注入行为。这是最成熟的 AI 工具扩展点设计之一。
2. **Permission Ruleset（权限即模式）**：用声明式规则集描述"哪类操作需要用户确认"，不同的规则集对应不同的工作模式（autonomous/interactive/supervised），通过配置切换而非硬编码条件判断。
3. **Part 状态机**：每条消息由多个 `Part` 组成（`TextPart`/`ToolCallPart`/`ToolResultPart`/`ReasoningPart`），每个 Part 有独立状态机（pending/streaming/complete/error），前端根据 Part 状态渲染不同的 UI 组件，实现增量流式渲染。
4. **Bus + SSE 事件总线**：后端 `EventBus` 发布 Part 状态变更事件，SSE 端点向前端推送，前端 React store 订阅更新。这个三层架构（Bus → SSE → Store）是流式 AI 应用的经典模式。
5. **MCP 一等公民**：Model Context Protocol 工具在系统里与本地工具完全同等地位，统一注册、统一调用、统一权限检查，不是"插件二等公民"。
6. **Fork/Revert 会话分支**：任意消息节点可以 Fork 出新会话分支，会话树结构存储，支持回退到历史节点重新探索。

#### 核心劣势

1. **TypeScript 语言绑定**：完整代码库无法直接在 Python 后端复用。
2. **面向开发者工具，不面向游戏/小说场景**：Permission、Part 等概念为代码辅助优化，移植到叙事游戏需要概念重新映射。
3. **Monorepo 复杂度**：多包管理、构建工具链、类型声明文件，对 Python 项目贡献不了任何现成代码。
4. **无骰子/游戏规则概念**：整个系统假设工具输出是代码/命令，没有"可验证随机数"的概念。

#### 关键技术亮点（可复用的设计，均为架构概念）

- **Hook 钩子的命名规范**：`{域}.{事件}.{时机}` 三段式命名（`tool.execute.before`）
- **Part 状态机的类型定义**：`TextPart | ToolCallPart | ToolResultPart` 联合类型
- **Permission Ruleset 的 YAML 格式**：声明式权限规则的 Schema 设计
- **Bus → SSE → Store 三层事件流架构**
- **Fork/Revert 的消息树数据结构**

#### 不可复用的部分

- 全部 TypeScript/JavaScript 代码
- Bun/npm 生态依赖
- 面向代码编辑器的 UI 组件

---

### 2.6 pi

**定位**：**最轻量的 TypeScript Agent 框架**，重点在 Extension 系统（jiti 热加载）、JSONL 会话树和 SKILL.md 自动扫描。同样仅参考架构。

#### 核心优势

1. **pi 风格 Agent Loop**：`beforeToolCall(ctx)` / `afterToolCall(ctx, result)` 钩子围绕工具执行形成完整拦截点，Extension 代码可在不修改核心的情况下实现日志、权限检查、结果变换。
2. **Extension 系统（jiti 热加载）**：Extension 文件是普通 TypeScript 模块，通过 jiti 在运行时动态加载，无需重启进程即可更新扩展，开发体验极佳。
3. **JSONL 会话树（分支）**：会话以 JSONL 格式存储，每条记录包含 `parent_id`，天然形成有向树，支持从任意节点分叉，实现会话分支探索。
4. **SKILL.md 自动扫描**：启动时自动扫描 `.cursor/skills/` 目录下的 `SKILL.md` 文件，将文档中描述的能力注册为可用工具，实现"文档即工具声明"的元编程。
5. **setActiveTools 动态切换**：允许在运行时根据当前上下文激活/停用工具集，如"进入战斗模式时激活骰子工具，退出后停用"，减少 LLM 的工具列表干扰。

#### 核心劣势

1. **TypeScript 语言绑定**：同 opencode，代码不可直接复用。
2. **jiti 热加载仅适用于 JS/TS**：Python 中需要使用 `importlib.reload` + 文件监听实现类似功能，复杂度更高。
3. **没有记忆子系统**：JSONL 会话树是原始对话记录，没有向量化检索，不适合长篇叙事。
4. **单 Agent 设计**：框架本身不原生支持多 Agent 并发协作，需要额外封装。
5. **SKILL.md 扫描过于简单**：仅做文件发现和描述提取，没有能力验证和权限控制。

#### 关键技术亮点（可复用的设计，均为架构概念）

- **`beforeToolCall`/`afterToolCall` 钩子接口设计**：在 Python 中可用 `asyncio` 协程钩子实现
- **JSONL 会话树的 `parent_id` 分支结构**
- **SKILL.md 扫描注册的元编程模式**：Python 中可用 `pathlib` + 正则实现
- **setActiveTools 动态工具集切换的 API 设计**

#### 不可复用的部分

- jiti 热加载机制（Python 等价物：`watchdog` + `importlib`）
- TypeScript Extension 接口定义
- 全部运行时代码

---

### 2.7 superpowers（方法论参考）

**定位**：不是代码项目，而是**工作流与规范文档**的集合，是 zero-arsenal Cursor Rules 和 SKILL.md 的方法论来源。

#### 核心价值

1. **SKILL.md 标准格式**：定义了 Skill 文件的触发条件、工具使用顺序、输出验证三段式结构，直接决定了 `.cursor/skills/` 目录的组织方式。
2. **决策图（Decision Graph）**：用流程图描述"遇到问题X时应该走哪条分支"的决策树，将隐性知识显性化。
3. **HARD-GATE 铁律**：明确列出"永远不能做的事"（如：不经 MCP 凭空假设状态、不在验证前输出正文），作为一等公民规则写入工作流，而不是"建议"。
4. **OpenCode 插件注入模式**：将 Skill 的上下文注入实现为 `user` 消息前缀（而非修改 `system` 提示），避免了 `system` 提示竞争问题，是多 Skill 并存的关键技术选择。
5. **四层文风文件体系**：骨架层/节奏层/心理层/温度层的文风正交分解，每层独立选择，组合灵活。

#### 对 zero-arsenal 的直接贡献

- 所有 `.cursor/rules/*.mdc` 文件的格式参照
- 所有 `.cursor/skills/*/SKILL.md` 的结构规范
- HARD-GATE 检查清单的编写范式

---

## 3. 能力矩阵对比表

| 能力维度 | ai-vn-game | ai-vn-backend | MoRanJiangHu | noveldemo | opencode | pi | superpowers |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **多Agent协作** | ❌ 无 | ✅ 5-Agent图 | ⚠️ 多阶段串行 | ❌ 单Agent | ✅ 插件协作 | ❌ 单Agent | ➖ 方法论 |
| **确定性骰子** | ❌ 无 | ❌ 无 | ⚠️ DSL模拟 | ✅ roller.py | ❌ 无 | ❌ 无 | ➖ 方法论 |
| **4阶段叙事管线** | ✅ P1-P4完整 | ⚠️ 部分 | ⚠️ 多阶段 | ❌ 无 | ❌ 无 | ❌ 无 | ➖ 方法论 |
| **向量记忆** | ❌ 无 | ✅ 四层混合 | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 | ➖ 方法论 |
| **变量精度/沙箱** | ⚠️ VM不安全 | ❌ 无 | ⚠️ DSL解析 | ❌ 无 | ❌ 无 | ❌ 无 | ➖ 方法论 |
| **提示词模块化** | ⚠️ 中等 | ⚠️ 中等 | ✅ 132模块 | ⚠️ 少量 | ❌ 无 | ❌ 无 | ✅ 文风体系 |
| **工具扩展点** | ❌ 无 | ⚠️ 有限 | ❌ 无 | ❌ 无 | ✅ Hook体系 | ✅ 钩子 | ➖ 方法论 |
| **Agent扩展点** | ❌ 无 | ⚠️ 硬编码 | ❌ 无 | ❌ 无 | ✅ Plugin | ✅ Extension | ➖ 方法论 |
| **MCP集成** | ❌ 无 | ⚠️ 有限 | ❌ 无 | ❌ 无 | ✅ 一等公民 | ⚠️ 基础 | ➖ 方法论 |
| **权限/模式** | ❌ 无 | ⚠️ AgentProfile | ❌ 无 | ❌ 无 | ✅ Ruleset | ⚠️ 基础 | ✅ HARD-GATE |
| **消息Part化** | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 | ✅ 完整 | ⚠️ 基础 | ➖ 方法论 |
| **Bus+SSE** | ⚠️ 基础 | ❌ 无 | ❌ 无 | ❌ 无 | ✅ 完整 | ❌ 无 | ➖ 方法论 |
| **章节分支/回滚** | ❌ 无 | ⚠️ 线性存档 | ❌ 无 | ✅ JSONL审计 | ✅ Fork/Revert | ✅ 会话树 | ➖ 方法论 |
| **前端完成度** | ❌ 无 | ❌ 无 | ✅ 完整React | ❌ 无 | ✅ 完整 | ❌ 无 | ➖ 方法论 |
| **可扩展性** | ⚠️ 低 | ⚠️ 中 | ⚠️ 中 | ✅ 高（轻量） | ✅ 极高 | ✅ 高 | ✅ 方法论级 |

> 图例：✅ 完整实现 ｜ ⚠️ 部分/受限实现 ｜ ❌ 缺失 ｜ ➖ 不适用（方法论项目）

---

## 4. 统合策略

### 4.1 可直接复制的代码/资产

以下内容语言无关或直接是目标语言（Python/Markdown），**直接复制，不重写**：

| 资产 | 来源项目 | 目标路径 | 备注 |
|---|---|---|---|
| `roller.py` | noveldemo | `backend/engine/dice.py` | 确认 seed 接口兼容后直接使用 |
| `RollResult` 数据类 | noveldemo | `backend/engine/dice.py` | Pydantic 模型化 |
| `OCEAN` 心理模型数值计算 | noveldemo | `backend/engine/psyche.py` | |
| 部位 HP `BodyPart` 枚举 | noveldemo | `backend/engine/combat.py` | |
| `memory/` 四层混合检索 | ai-vn-system-backend | `backend/memory/` | 解耦世界绑定后直接使用 |
| `purity_check` 函数 | ai-vn-system-backend | `backend/agents/style_agent.py` | |
| SQLite WAL 初始化代码 | ai-vn-system-backend | `backend/db/` | |
| 37+ 文风 `.md` 文件 | MoRanJiangHu | `writing-styles/` | 已在工作区存在 |
| JSONL 审计追加写入 | noveldemo | `backend/db/audit.py` | |
| SKILL.md 格式模板 | superpowers | `.cursor/skills/*/SKILL.md` | |

### 4.2 需要移植重写的部分

以下内容需要语言翻译或架构适配：

| 原始实现 | 来源 | 重写目标 | 主要变化 |
|---|---|---|---|
| 四阶段 P1-P4 管线（Express） | ai-vn-game-system | LangGraph 节点序列 | JS→Python，Express→LangGraph |
| `NarrativeGrant` 旁路机制（JS） | ai-vn-game-system | Python asyncio 异步任务 | 事件机制翻译 |
| `vm` 沙箱变量执行（Node VM） | ai-vn-game-system | RestrictedPython | 安全沙箱升级 |
| 多世界 `time_multiplier`（JS对象） | ai-vn-game-system | Python dataclass + SQLite | 持久化 |
| `TavernCommand` DSL 解析（TS） | MoRanJiangHu | Python `re` 正则解析器 | 语言翻译 |
| 提示词 132 模块（TS） | MoRanJiangHu | Python 函数 + Jinja2 模板 | 语言翻译，优先移植高频模块 |
| LangGraph 图定义（已是Python） | ai-vn-system-backend | 直接扩展，解耦世界绑定 | 架构重构 |

### 4.3 只参考架构的部分

以下来自 TypeScript 项目，**只学习架构思想，不复用任何代码**：

| 架构概念 | 来源 | Python 等价实现方案 |
|---|---|---|
| Plugin Hook 体系 | opencode | `pluggy` 库 或 手写 `asyncio` 钩子链 |
| Part 状态机 | opencode | Pydantic discriminated union + SSE |
| Permission Ruleset | opencode | YAML 规则文件 + Python 解释器 |
| Bus → SSE 三层事件流 | opencode | `asyncio.Queue` + FastAPI SSE |
| Fork/Revert 会话树 | opencode/pi | JSONL `parent_id` 链 + SQLite |
| Extension 热加载 | pi | `watchdog` + `importlib.reload` |
| `setActiveTools` 动态切换 | pi | LangGraph 条件边 + ToolRegistry |
| SKILL.md 自动扫描 | pi | `pathlib.glob` + 正则提取描述 |

### 4.4 作为方法论的部分

以下只影响**团队工作方式和 Cursor 配置**，不产生任何运行时代码：

- **superpowers 的 HARD-GATE 铁律格式**：写入 `.cursor/rules/` 的规则文件
- **superpowers 的 SKILL.md 三段式结构**：所有 Skill 文件遵循的模板
- **superpowers 的 OpenCode 插件注入为 user 消息前缀**：Cursor Agent 上下文注入方式
- **四层文风正交分解**：骨架/节奏/心理/温度各层独立，写作前 Read 文风文件的工作习惯

---

## 5. 风险与取舍

### 5.1 为什么选 Python 不选 Node.js 后端

**根本原因：生态完整性优势压倒开发速度差异。**

- LangChain/LangGraph 均是 Python 原生，JavaScript 版本功能滞后约 30%。
- ChromaDB、FAISS、sentence-transformers 只有 Python SDK，向量记忆子系统在 JS 里无法完整实现。
- `purity_check` 等 NLP 工具（spaCy、jieba）在 Python 生态远比 JS 成熟。
- ai-vn-system-backend 已是 Python 且质量最高，最大的可复用代码库是 Python。
- **权衡代价**：Node.js 的异步性能和 SillyTavern 生态接入能力会损失，通过 FastAPI + asyncio 的组合部分弥补。

### 5.2 为什么选 LangGraph 不选自研 Agent 循环

**根本原因：有向图调度的错误隔离能力是自研循环难以复现的。**

- LangGraph 的条件边（`conditional_edge`）允许在 Agent 执行失败时走特定的错误处理分支，自研 `while True` 循环通常退化为全局 `try/except`。
- LangGraph 的 checkpointing 机制支持从任意中间节点恢复执行，对长叙事的断点续写至关重要。
- 并行分叉（`fan_out`/`fan_in`）在 LangGraph 里是一等公民，自研实现需要额外的 `asyncio.gather` 封装。
- **权衡代价**：LangGraph 的 API 有学习曲线，且版本更新可能引入不兼容变更；通过锁定版本号和充分的集成测试应对。

### 5.3 为什么新建项目而不是在某一个基础上扩展

**根本原因：现有项目与具体世界/场景的耦合度过高，扩展成本高于重建成本。**

- **扩展 ai-vn-system-backend** 的问题：数据库 Schema 硬绑定 MUV-LUV 世界的 NPC 字段、积分体系、章节索引，泛化需要重写 80% 的核心模块，不如新建后按需迁移。
- **扩展 ai-vn-game-system** 的问题：Node.js 语言壁垒，无法复用 Python 生态，且前端完全缺失。
- **扩展 MoRanJiangHu** 的问题：1800+ 文件的 React 纯前端项目，添加真正的后端需要大规模架构重构。
- **新建的成本收益**：新建允许从一开始就正确设计 AgentProfile 权限、通用 WorldConfig、参数化提示词，避免积累设计债务。

### 5.4 技术债风险

| 风险项 | 严重程度 | 缓解策略 |
|---|:---:|---|
| LangGraph 版本锁定 | ⚠️ 中 | `requirements.txt` 锁定精确版本，每季度评估升级 |
| SQLite 在高并发下的写锁 | ⚠️ 中 | WAL 模式 + 写入队列，监控 `database is locked` 错误率 |
| RestrictedPython 沙箱逃逸 | 🔴 高 | 定期跟踪 CVE，生产环境考虑独立进程沙箱 |
| 提示词模块 TS→Python 移植质量 | ⚠️ 中 | 每个移植模块写输入/输出示例测试，人工校验 |
| 记忆子系统向量漂移 | ⚠️ 中 | 定期重建索引，监控召回 precision@5 指标 |
| 多 Agent 并发下的状态竞争 | ⚠️ 中 | LangGraph 的 `MemorySaver` + 乐观锁，关键字段加 `asyncio.Lock` |
| 前端 React 与后端 SSE 协议不兼容 | ⚠️ 中 | 先写 SSE 协议规范文档，前后端各自实现后做集成测试 |

---

*文档结束 · 下一文档：`02-system-architecture.md`*
