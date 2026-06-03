# 报告一：架构与代码质量对比

> 生成时间：2026-06-03 | 数据来源：L1-L4 子代理扫描（D01+D02）

---

## 1. 项目全景速览

| 项目 | 技术栈 | 规模 | 架构模式 | 层次清晰度 |
|------|--------|------|----------|------------|
| **zero-arsenal** | Python(FastAPI+LangGraph) + React(TS+Vite+Tailwind) | ~28k-35k LOC，114后端/45前端文件 | 多Agent流水线 + SSE + WorldPlugin | 4/5 |
| **ai-vn-game-system** | Node.js(Express) + Vanilla JS | ~167文件，shop.js单文件4600+行 | 薄路由层 + core/content/engine/features/routes五层 | 4/5（shop.js破坏整体）|
| **ai-vn-system-backend** | Python(FastAPI) + React(JSX) | ~134文件，55个后端模块/8个前端组件 | FastAPI分层 + agents/memory/db | 4/5 |
| **MoRanJiangHu** | React(TS+Vite+Tailwind) + IndexedDB | ~1447 TS/TSX文件，~100 Vitest测试 | 超大useGame Hook + 领域workflow文件夹 + 渐进Zustand迁移 | 3/5 |
| **noveldemo** | Python CLI | ~625行roller.py骰子引擎 | 简单脚本 | 4/5（规模小）|

---

## 2. 架构深度分析

### 2.1 zero-arsenal（A1）——当前主线项目

**分层结构（后端）**
```
api/（REST+SSE）
  └─ agents/（LangGraph StateGraph）
       └─ rules→dm→parallel_npc_world→narrator→style→var→chronicler
  └─ engine/（d10骰子池 + TavernCommand VM）
  └─ memory/（四层召回：segment/episode/semantic/world）
  └─ extensions/（<id>/manifest.json + plugin.py + tools.py + hooks.py）
  └─ bus/（EventBus — Redis stub，降级内存）
  └─ db/（aiosqlite，JSONL审计只追加）
```

**前端分层**
```
pages/（HomePage + SessionPage）
  └─ components/parts/（PartRenderer 17种Part类型，高频直引+低频lazy）
  └─ stores/（Zustand：useUIStore + useSessionStore等）
  └─ lib/（bindSSEToStores — BusEvent与Zustand解耦核心）
```

**核心设计亮点**
- `parallel_npc_world`节点用`asyncio.gather + return_exceptions`降级，NPC/World并发生成
- 三级扩展发现（内置/用户/项目）+ manifest声明式加载，零侵入
- `LlmRoutesTab`运行时`PUT /config/llm-routes`改路由，无需重启
- `PartRenderer`高频Part直接引入，低频`React.lazy`，首屏不阻塞

**已知技术债**
| STUB编号 | 描述 | 风险 |
|----------|------|------|
| STUB-03 | `rules_agent` LLM失败默认`pass`（静默绕过规则裁判） | **高** — 安全漏洞 |
| STUB-02 | Redis EventBus降级内存，单进程限制 | 中 |
| STUB-MCP | Hub无MCP管理面板，后端MCPToolBridge完整度不足 | 中 |
| - | `useUIStore.addNotification`已实现但全项目零调用 | 中（体验） |
| - | `setTheme`已实现但无UI调用，CSS固定暗色 | 低 |

### 2.2 ai-vn-game-system（A2）——游戏前端原型

**核心架构**
- `server.js`极薄（纯路由注册）；业务逻辑按domain拆分进`core/content/engine/features/`
- 前端多页应用（MPA）：`index.html`游戏主界面 + `hub.html`配置控制台 + `shop.html/character.html/preset.html/settings.html`
- 全站共享`public/ui-feedback.js`（Toast/confirmDanger/renderEmpty/renderLoadingLines）
- `gachaEngine.js`带权重抽卡、`sessionManager.js`存档锁

**主要问题**：`shop.js`体量极大（4600+行），维护风险高；无自动化测试套件

### 2.3 ai-vn-system-backend（A3）——后端原型

**核心架构**
- FastAPI分层：`api/ → agents/ → memory/ → db/`，边界清晰
- `backend/tests/`含9个pytest文件（db/utils/agents/api/exchange）
- 前端仅8个React组件，业务集中在Modal（`ProtagonistGeneratorModal` + `NovelPickerModal`）

**值得保留的设计**
- 三栏TRPG布局（`left|center|right` CSS Grid）已在zero-arsenal中实现
- SSE多路分流：`log/thought/novel_text/system_grant/error`分别路由到不同UI区域

### 2.4 MoRanJiangHu（A4）——最复杂前端

**架构痛点**
- 核心状态聚集在`hooks/useGame.ts`（~1200+行）+ `hooks/useGameState.ts`，成为"超级Hook"
- Zustand迁移中期：React `useState`（主路径）与Zustand slice（渐进迁移）双轨并存
- Toast实现双份：`notificationSystem.ts`（函数式）与`zustandStore.ts` UI slice（状态式）互相存在

**架构优势**
- `utils/moduleRegistry/`：window事件`modal:open/close` + lazy注册，实现低耦合Modal系统
- `hooks/useGame/**`按域拆分（sendWorkflow/opening/image/world等），意图清晰
- ~100个Vitest测试，集中覆盖关键工作流

### 2.5 noveldemo + opencode/pi/superpowers（L4架构参考）

| 参考点 | 来源 | 对zero-arsenal的价值 |
|--------|------|----------------------|
| d10骰池完整算法（大失败/失败/勉强/成功/大成功/传奇） | noveldemo/roller.py | zero-arsenal已迁移核心，待迁：完整Character类、CLI先攻子命令 |
| Effect ToolRegistry：工具定义可按模型/agent过滤 | opencode | zero-arsenal工具注册表增强 |
| 声明式per-tool allow/ask/deny + 运行时`permission.asked`事件 | opencode | zero-arsenal有AgentProfile但缺ask交互流 |
| 完整MCP Service（stdio/HTTP/SSE+OAuth+ListTools） | opencode | zero-arsenal MCPBridge对标对象 |
| SKILL.md YAML frontmatter + `<skill>`XML注入 | pi | zero-arsenal skill_loader已部分实现 |
| HARD-GATE模式（无批准禁止执行） | superpowers | Rules/Planner Agent强制审批流 |

---

## 3. 测试覆盖率对比

| 项目 | 测试文件 | 框架 | 覆盖重点 | 覆盖率估算 |
|------|----------|------|----------|------------|
| zero-arsenal | unit×5 + integration×1 + e2e×3 | pytest + playwright | Gacha/Extension/Memory/E2E | <25% LOC |
| ai-vn-game-system | 0（仅tools/test-*.js手工脚本） | 无 | — | ~0% |
| ai-vn-system-backend | 9个pytest文件 | pytest | db/utils/agents/api/exchange | ~30-40% |
| MoRanJiangHu | ~100个Vitest文件 | Vitest + jsdom | useGame工作流单元测试 | ~15-20% |
| noveldemo | 无正式测试 | — | — | ~0% |

---

## 4. 核心架构模式传承链

```
noveldemo (2024)
  └─ d10骰子算法 → zero-arsenal engine/dice.py ✓
  └─ writing-styles分类 → zero-arsenal 38个Skills（前端未接线！）
  └─ rules/*.md设计 → zero-arsenal PromptManager

ai-vn-system-backend (2025)
  └─ FastAPI分层 → zero-arsenal api/架构 ✓
  └─ SSE多路分流 → zero-arsenal bindSSEToStores ✓
  └─ ProtagonistGenerator → zero-arsenal CharacterCreator ✓

ai-vn-game-system (2025)
  └─ UIFeedback(toast/confirm) → zero-arsenal addNotification未接线 ⚠️
  └─ 新游戏三步向导 → zero-arsenal 会话创建单页表单 ⚠️
  └─ healthList体检 → zero-arsenal 部分实现

MoRanJiangHu (2024-2025)
  └─ WorldPlugin思路 → zero-arsenal extension系统 ✓
  └─ InAppConfirmModal → zero-arsenal window.confirm ⚠️
  └─ Toast栈 → zero-arsenal addNotification未接线 ⚠️
```

---

## 5. 优先技术改进建议

| 优先级 | 改进项 | 难度 | 影响 |
|--------|--------|------|------|
| **P0** | 修复`rules_agent` LLM失败默认`pass` | 小 | 安全/正确性 |
| **P0** | 接线`useUIStore.addNotification`→Toast UI | 小 | 用户体验 |
| **P1** | 统一确认对话框（替换`window.confirm`） | 小 | 体验一致性 |
| **P1** | Redis EventBus真实实现 | 大 | 扩展性 |
| **P1** | 完善MCP Hub管理面板 | 中 | 扩展生态 |
| **P2** | `shop.js`体量拆分（借鉴ai-vn-game-system迁移） | 大 | 维护性 |
| **P2** | 前端writing-styles选择器接线 | 中 | 功能完整性 |
