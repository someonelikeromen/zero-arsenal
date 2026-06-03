# conf_b12 · 设计符合度审计 — 维度 B「前端架构」

> 审计对象：`docs/design/12-frontend-architecture.md` ↔ `frontend/src/**`
> 复审基准日期：2026-06-03 · 行级证据以当前文件为准
> 关键结构性事实：设计写 `services/` + `types/` + `hooks/` + `shadcn-ui`，实现实际采用 `lib/` + 内联类型 + store 内聚 + 手写 Tailwind 组件；设计 §3.5 的「四 store 孤儿」警告**已过时**（现已全部接线）。

---

### §1.1 核心技术栈 — React 19
- 设计要求：UI 框架 React 19（Concurrent + use() + 流式渲染）
- 实现状态：完整
- 证据：`frontend/package.json:17-18`（`react ^19.0.0` / `react-dom ^19.0.0`）；`frontend/src/main.tsx:14`（`React.StrictMode`）
- 差距：无
- 处置：无需动作

### §1.1 核心技术栈 — TypeScript 5.5+
- 设计要求：TS 5.5+，Part 类型联合体安全
- 实现状态：完整
- 证据：`frontend/package.json:28`（`typescript ^5.5.3`）；`frontend/src/stores/story.ts:12-30`（PartType 联合）
- 差距：无
- 处置：无需动作

### §1.1 核心技术栈 — Vite 6
- 设计要求：构建工具 Vite 6
- 实现状态：完整
- 证据：`frontend/package.json:29`（`vite ^6.0.0`）
- 差距：无
- 处置：无需动作

### §1.1 核心技术栈 — Tailwind CSS 4
- 设计要求：样式系统 Tailwind CSS **4**
- 实现状态：偏离
- 证据：`frontend/package.json:27`（`tailwindcss ^3.4.4` + `postcss`/`autoprefixer` 传统 PostCSS 链）
- 差距：实际为 Tailwind v3（v4 取消 postcss/autoprefixer 依赖、改用 `@tailwindcss/vite`），版本与构建方式均不符
- 处置：补/改设计文档（标注实际为 v3）或升级

### §1.1 核心技术栈 — shadcn/ui 组件库
- 设计要求：组件库 shadcn/ui（Radix 基础），复制入 `components/ui/`
- 实现状态：缺失
- 证据：无 `components/ui/` 目录（Glob 全量 55 文件无命中）；依赖仅 `lucide-react`/`clsx`（`frontend/package.json:14-15`），无 `@radix-ui/*`
- 差距：完全未引入 shadcn/ui 与 Radix；骰子面板/对话框/权限弹窗均为手写 Tailwind 组件
- 处置：补/改设计文档（说明改为纯手写组件）

### §1.1 核心技术栈 — Zustand 5
- 设计要求：状态管理 Zustand 5 + immer middleware
- 实现状态：完整
- 证据：`frontend/package.json:19`（`zustand ^5.0.0`）、`:16`（`immer ^11.1.8`）；`stores/story.ts:71-73`（devtools+immer）
- 差距：无（immer 覆盖率见 §3 单列条目）
- 处置：无需动作

### §1.1 核心技术栈 — 本地存储 IndexedDB（via idb v8）
- 设计要求：通过 `idb` 库（v8）封装，`openDB<ZeroArsenalDB>`
- 实现状态：偏离
- 证据：`frontend/src/lib/idb.ts:19-42` 直接用原生 `indexedDB.open`，无 `idb` 依赖（`package.json` 无 `idb`）
- 差距：未使用 `idb` 库，自行手写 Promise 包装；DB 名 `zero_arsenal`（设计示例 `zero-arsenal`）
- 处置：补/改设计文档（标注为原生 IndexedDB 封装）

### §1.1 核心技术栈 — SSE 自实现客户端
- 设计要求：自实现 SSEClient，支持 Last-Event-ID 续传 + 指数退避
- 实现状态：完整
- 证据：`frontend/src/lib/sse.ts:16`（class SSEClient）、`:60-66`（lastEventId 拼 URL）、`:94-98`（指数退避 max 30s）、`:114-125`（额外 heartbeat 超时重连）
- 差距：无（细节差异见 §5）
- 处置：无需动作

### §1.1 核心技术栈 — TanStack Router
- 设计要求：路由 TanStack Router 1.x
- 实现状态：完整
- 证据：`frontend/package.json:13`（`@tanstack/react-router ^1.170.10`）；`frontend/src/router.tsx:9-15,97`
- 差距：无
- 处置：无需动作

### §1.3 项目结构（services / types / hooks / ui 目录）
- 设计要求：`src/` 下含 `services/`（sse-client/api-client/idb-cache）、`hooks/`、`types/`（session/parts/character/events）、`components/{layout,chapter,character,dice,ui}`
- 实现状态：偏离
- 证据：Glob 全量 55 文件——实际为 `lib/{sse.ts,api.ts,idb.ts,bindSSEToStores.ts}`、`components/parts/`、`components/panels/`；无 `services/`、`hooks/`、`types/`、`components/ui|layout|chapter|character|dice` 目录（`Glob {types,hooks,services,prompts}` 返回 0 命中）
- 差距：目录命名与分层重组——`services→lib`、类型内联各 store/`lib/api.ts`、无独立 hooks 层、面板统一收纳于 `components/panels/`
- 处置：补/改设计文档（同步实际目录树）

### §1.3 项目结构 — pages 三页面
- 设计要求：`pages/{SessionPage, LobbyPage, ConfigPage}`
- 实现状态：部分
- 证据：`pages/SessionPage.tsx` ✓；`pages/HomePage.tsx`（代 LobbyPage）；`pages/SettingsPage.tsx`（代 ConfigPage）；`router.tsx:43-49,52-58` 中 `/settings`、`/sessions` 仅做 redirect 到首页
- 差距：SessionPage 一致；Lobby→Home、Config→Settings 重命名且未挂独立路由（设置/列表合并进 HomePage Tab）
- 处置：补/改设计文档

### §2.1 / §2.3 总体三栏布局 + 骰子底栏
- 设计要求：Header + 三栏（ChapterTree w-64 / StoryCanvas / CharacterPanel w-80），中栏底部为 `DicePanel` + DM 工具箱横条，再下为行动选项+输入框
- 实现状态：偏离
- 证据：`pages/SessionPage.tsx:420-526`——左栏 `w-52`、右栏 `w-64` 且为**标签式多功能面板**（`RIGHT_TABS` 8 个 tab，`:89-98`），`DicePanel` 收入右栏 `dice` tab（`:382`）而非中栏底栏；中栏仅 `MessageThread`+`InputBar`，无 DM 工具箱横条
- 差距：骰子面板位置、CharacterPanel 单列侧栏均被「右侧 8-tab 面板」取代；Header 无独立「世界插件/设置」按钮（顶栏为 `:440` 站名+模型+ModeSelector）
- 处置：补/改设计文档（更新布局图为右侧 Tab 面板架构）

### §2.2 响应式断点（手机/平板/桌面三档抽屉）
- 设计要求：<768 单栏+底抽屉；768~1280 双栏+左抽屉；>1280 三栏
- 实现状态：完整
- 证据：`pages/SessionPage.tsx:44-73`（Drawer 组件）、`:424`（`hidden xl:flex` 左栏）、`:524`（`hidden lg:flex` 右栏）、`:529-536`（左/右抽屉），断点 xl/lg 对应桌面/平板
- 差距：断点语义与设计一致（实现用 lg=1024 而非 1280，量级吻合）
- 处置：无需动作

### §3.2 SessionStore 切片
- 设计要求：`{currentSessionId, sessions, currentMode}` + `setCurrentSession/setMode/setSessionStatus/loadSessions/createSession`，devtools 中间件
- 实现状态：部分
- 证据：`stores/session.ts:32-85`——有 `sessions/currentSessionId/mode/loadSessions/createSession/setMode`、`selectSession`(=setCurrentSession)；新增 `sseClient/pendingAsks/connectSSE/disconnectSSE/addPendingAsk`；**缺 `setSessionStatus` 与 `Session.status` 状态机**；未用 devtools
- 差距：会话 `status`（active/processing/idle/error）未在 store 内建模，改由 `uiStore.inputDisabled` + SSE 事件代理；store 兼任 SSE 连接与权限询问职责
- 处置：补/改设计文档

### §3.3 StoryStore 切片
- 设计要求：`parts: Record<string, MessagePart>`、`streamingPartIds: Set`、`createPart/appendPartDelta/finalizePart/loadMessages/loadParts/revertToMessage`，immer
- 实现状态：部分
- 证据：`stores/story.ts:51-69`——`parts: MessagePart[]`（**数组而非 Record**）、`streamingPartId: string`（**单值而非 Set**）；动作名 `addPart/appendDelta/finalizePart`（语义对应）；额外 `loadFromCache/updatePartContent/clearSession`；immer ✓（`:73`）
- 差距：数据结构由「Record+Set」改为「数组+单 id」；`MessagePart.content` 为 `Record<string,unknown>`（设计为 `string|null`+独立 `payload`）；功能等价
- 处置：补/改设计文档

### §3.4 CharacterStore 切片
- 设计要求：`CharacterV4` + `snapshotHistory:[{messageId,snapshot}]` + `applyTavernCommands(commands,messageId)`（op: set/increment/append/remove）+ `restoreSnapshot(messageId)`，immer
- 实现状态：偏离
- 证据：`stores/character.ts:60-85,116-201`——快照按 `ts` 而非 messageId（`:50-55`）；`applyPatch(patches)` 用 `cmd: SET/ADD/PUSH/POP`（`:143-168`）而非 set/increment/append/remove；`restoreSnapshot()` 为 LIFO 弹栈、无 messageId 参数（`:192-201`）；未用 immer，改 `devtools`+手动 `JSON.parse(JSON.stringify)` 深克隆（`:88,127`）
- 差距：快照键、命令枚举、回滚定位方式、不可变实现手段均与设计不同（功能上仍支持打补丁+回滚）
- 处置：补/改设计文档（统一命令枚举与快照模型）

### §3.5 其余四 store（chapter/dice/ui/world）创建 + 接线状态
- 设计要求：四 store 已创建但「**未接入任何组件（孤儿）**」（设计文档第二十九轮补录）
- 实现状态：完整（设计描述已过时）
- 证据：`DicePanel.tsx:4,22` 消费 `useDiceStore`；`ChapterTree.tsx:7,155` 消费 `useChapterStore`；`SessionPage.tsx:14-15,105-107` 消费 `useDiceStore/useWorldStore`；`bindSSEToStores.ts:109-120` 向 diceStore 推送
- 差距：设计 §3.5 的孤儿警告**不再成立**——四 store 均已接线生效
- 处置：补/改设计文档（删除/更新孤儿警告）

### §3.5 UIStore 结构
- 设计要求：`{isDicePanelOpen, isDmToolboxOpen, isChapterTreeOpen, isCharacterPanelOpen, permissionDialog}` + `toggleDicePanel/showPermissionDialog/closePermissionDialog`
- 实现状态：偏离
- 证据：`stores/ui.ts:28-48`——实际为 `{activePanel, sidebarOpen, notifications, inputDisabled, theme}` + 通知/主题动作；权限弹窗由 `sessionStore.pendingAsks` 控制（`session.ts:20`），非 uiStore
- 差距：UI 状态字段与设计完全不同；抽屉开合改用 SessionPage 局部 `useState`（`SessionPage.tsx:169-170`），权限弹窗职责移交 sessionStore
- 处置：补/改设计文档

### §3 immer 中间件统一使用
- 设计要求：所有 store 使用 immer 简化深层更新
- 实现状态：部分
- 证据：story/dice/chapter/ui 用 immer（`story.ts:73`、`dice.ts:39`、`chapter.ts:58`、`ui.ts:75`）；**session/character/world 未用 immer**（`session.ts:32` 裸 create；`character.ts:88` devtools+手动克隆；`world.ts:42` devtools）
- 差距：immer 覆盖 4/7 store
- 处置：补/改设计文档或补齐 immer

### §4.1 / §4.2 PartRenderer（switch 分派 + 懒加载）
- 设计要求：按 `part.type` switch 分派子组件；DiceRoll/Reward 等用 `React.lazy`
- 实现状态：完整
- 证据：`components/parts/PartRenderer.tsx:38-189` switch 分派；高频 Part 直接 import（`:13-16`），低频/重型 `React.lazy`（`:19-25`）+ Suspense 骨架（`:28-30`）；新增「未知类型兜底」（`:169-188`）
- 差距：懒加载粒度比设计更细分（高频直载/低频懒载），优于设计
- 处置：无需动作

### §4.2 state_patch 无 UI（仅触发 store）
- 设计要求：`state_patch` 返回 `null` 不渲染，在 PartRenderer 的 `useEffect` 内调用 `applyTavernCommands`
- 实现状态：偏离
- 证据：`PartRenderer.tsx:43-44` 渲染 `<StatePatchPart>`（有 UI）；命令应用位于 `bindSSEToStores.ts:99-105`（SSE `part.done` 时 `applyPatch`），而非 PartRenderer useEffect
- 差距：state_patch 改为「可视化差异卡片 + SSE 层应用补丁」，与设计「无 UI + 渲染层应用」相反
- 处置：补/改设计文档

### §4.3 / §6 NarrativePart 流式差分优化
- 设计要求：用 `useStoryStore.subscribe` 细粒度订阅 + `slice` 取增量 delta 直写 DOM，**绕过 React re-render**；流式结束后一次 setState 接管
- 实现状态：部分
- 证据：`components/parts/NarrativePart.tsx:19-23` 仅 `useEffect([part.streamBuffer])` + `textContent` 直写；无 `store.subscribe`，仍随父组件 `MessageThread` 重渲染触发；完成态 `:52-68` 用 React 段落渲染
- 差距：核心「绕过 reconciler 的 store.subscribe + delta slice」优化未实现——每个 delta 仍走 React 渲染路径（DOM 直写只省了 innerHTML diff）
- 处置：补实现（接 store.subscribe 细粒度订阅）或补/改设计文档降级说明

### Part 类型联合（附录 types/parts.ts）
- 设计要求：8 种 Part 类型（narrative/dice_roll/state_patch/dm_note/npc_action/system_grant/chapter_end/permission_ask）
- 实现状态：完整（超集）
- 证据：`stores/story.ts:12-30` 覆盖全部 8 种，并扩展 9 种（world_event/compaction/skill_load/action_options/reasoning/text/tool_call/tool_result/var_diff）
- 差距：实现为设计的严格超集；`system_grant→RewardToast`/`chapter_end→ChapterDivider`/`permission_ask→PermissionDialog` 三个独立组件未建，改为 PartRenderer 内联 JSX（`PartRenderer.tsx:95-143`），其中 system_grant 渲染为「行内授权提示」而非设计的 Toast
- 处置：补/改设计文档（登记扩展类型，标注内联渲染）

### §5 SSE 客户端实现
- 设计要求：connect/disconnect、`?lastEventId=` 续传、指数退避 max 30s、handleEvent switch 处理 part.created/updated/done/permission.ask/session.mode_changed/idle/error
- 实现状态：完整
- 证据：`lib/sse.ts:53-58,134-139`（connect/disconnect）、`:60-66`（续传，参数名 `last_event_id`）、`:94-98`（退避 max 30s，封顶重试 8 次）；事件处理外移到 `bindSSEToStores.ts:64-195`，覆盖设计全部事件 + permission.granted/denied + agent.started/ended + turn.complete + chapter.consolidated
- 差距：①查询参数名 `last_event_id`（设计 `lastEventId`）；②`BusEvent` 无 `id` 字段（用 EventSource 原生 `e.lastEventId`，`:73`）；③事件 switch 从 client 内移至独立模块（解耦更优）；④重试封顶 8 次（设计为连接期间不限次）
- 处置：补/改设计文档（同步参数名与事件清单）

### §5.1 useSSE Hook
- 设计要求：`hooks/useSSE.ts` 暴露 `useSSE(sessionId)` 管理 connect/disconnect 生命周期
- 实现状态：偏离
- 证据：无 `hooks/` 目录；连接生命周期内联在 `SessionPage.tsx:184-214`（`connectSSE(sessionId,onEvent)` + `return ()=>disconnectSSE()`），经 `sessionStore.connectSSE`（`session.ts:62-74`）
- 差距：无独立 hook，逻辑内聚到 SessionPage + sessionStore
- 处置：补/改设计文档

### §7 DiceRollPart 可视化
- 设计要求：`DicePayload{attribute,skill,modifier,pool,difficulty,successes,outcome,detail,rerollDetail}`，OUTCOME_CONFIG（botch/failure/success/**major_success**），DiceIcon 含 difficulty/isReroll，重骰追加点数独立展示
- 实现状态：偏离
- 证据：`components/parts/DiceRollPart.tsx:20-21` 用后端 `DiceRollResult{pool_formula,rolls,threshold,verdict,result,net,successes,ones,narrative_hint}`；`VERDICT_COLOR` 为 critical/success/failure/botch（`:8-13`，无 major_success）；`:35-47` 骰子点数按 `threshold` 上色；**无 rerollDetail 独立渲染**
- 差距：payload 形态由后端结算结果驱动，与设计前端枚举不一致；缺「重骰追加点数」可视化；outcome 枚举名不同（critical vs major_success）
- 处置：补/改设计文档（对齐后端 DiceRollResult schema）

### §8 章节树组件 ChapterTree
- 设计要求：递归 `ChapterNode`（折叠/固化图标/分支标签），消费 `useChapterStore`，含「+新建分支」
- 实现状态：完整
- 证据：`components/panels/ChapterTree.tsx:31-150` 递归节点（展开/折叠 `:83-92`、固化🔒/分支⑂/进行中○ 图标 `:95-102`、分支标签 `:45`）；消费 `useChapterStore`（`:7,155`）；含 fork 输入（`:260-279`）、整合📑、回溯↩（设计未提，为增强）
- 差距：字段命名为 snake_case（id/parent_chapter_id），但结构与行为完整覆盖并超出设计
- 处置：无需动作

### §9 IndexedDB 本地缓存
- 设计要求：`idb` 库 `DBSchema`，按 `MAX_SESSIONS=10` LRU 驱逐，`savePart` 跳过流式 Part，`getPartsForSession`，`lastSyncedEventId`，`useSessionRestore` hook
- 实现状态：部分
- 证据：`lib/idb.ts` 原生实现，store=sessions/messages/parts/character（`:24-37`）；用 `STALE_MS` 时间过期（`:97,107`）**而非 MAX_SESSIONS LRU 驱逐**；`putPart` 不跳过流式（`:123`，但 story.ts 主要缓存 done part）；`getPartsBySession`✓（`:127`）、`getLastSyncedEventId/setLastSyncedEventId`✓（`:153-172`）；恢复流程内联于 `SessionPage.tsx:189-191`（loadFromCache→loadParts），无 `useSessionRestore` hook
- 差距：驱逐策略（时间过期 vs 10 会话 LRU）、流式过滤、恢复 hook 形态均与设计不同；核心「冷启动从缓存即时显示 + lastEventId 续传」已具备
- 处置：补/改设计文档或补 LRU 驱逐

### §10 前端提示词模块（prompts/）
- 设计要求：`prompts/index.ts` 含 `OPENING_GUIDE_PROMPT`、`ACTION_OPTIONS_SYSTEM`、`OOC_COMMANDS`（/plan /play /review /save /fork /revert /help /status）
- 实现状态：缺失
- 证据：无 `prompts/` 目录（`Glob {...,prompts}` 0 命中；`Grep OPENING_GUIDE_PROMPT|OOC_COMMANDS|ACTION_OPTIONS_SYSTEM` 仅命中 node_modules）；开场提示改由后端 `api.generateOpening`（`SessionPage.tsx:244`）；OOC 指令内联在 `SessionPage.tsx:252-336`，指令集为 `/mode /fork /stats /clear /help`（与设计 `/plan //play /review /save /revert /status` 不一致）
- 差距：前端提示词常量模块完全未建（提示词整体下沉后端）；OOC 命令动词不同
- 处置：补/改设计文档（说明提示词下沉后端、登记实际 OOC 命令集）

### 设计未覆盖的前端实现（实现 > 设计）
- 设计要求：（设计仅描述 dice/character/chapter 三类面板与上列组件）
- 实现状态：偏离（扩展）
- 证据：`components/panels/` 另有 `MemoryPanel/EconomyPanel/CombatPanel/WritingStylePanel/HistoryPanel/InventoryPanel/WorldPanel/CharacterPanel`（`SessionPage.tsx:28-33` 懒加载）；顶层另有 `ToastStack/ConfirmDialog/LlmConfigBanner/ThemeGuideModal/CharacterCreator/CharacterEditor/AssetLibrary/WorldManager/ScraperRulesPanel/ExtensionsPanel/PromptManager/SessionManager/ModeSelector/MessageThread/InputBar`
- 差距：大量面板/组件与扩展 Part 类型（var_diff/tool_call 等）在设计文档中无登记
- 处置：补/改设计文档（增补右侧 8-tab 面板与扩展组件章节）

---

## 符合度小计

| 状态 | 计数 | 条目 |
|------|------|------|
| 完整 | 12 | React19 / TS5.5 / Vite6 / Zustand5 / SSE自实现 / TanStackRouter / §2.2响应式 / §3.5四store接线 / §4.2 PartRenderer / Part类型联合 / §5 SSE客户端 / §8 ChapterTree |
| 部分 | 6 | §1.3 pages / §3.2 SessionStore / §3.3 StoryStore / §3 immer / §4.3+§6流式优化 / §9 IndexedDB |
| 缺失 | 2 | §1.1 shadcn/ui / §10 前端提示词模块 |
| 偏离 | 10 | Tailwind4(→v3) / idb库 / §1.3目录结构 / §2布局 / §3.4 CharacterStore / §3.5 uiStore / §4.2 state_patch无UI / §5.1 useSSE hook / §7 DiceRollPart / 设计未覆盖扩展 |

**总条目：30**

**整体符合度估计：约 62%**
- 核心运行链路（React19/Zustand/SSE 续传/PartRenderer 分派/ChapterTree/IndexedDB 冷启动/响应式三栏）**功能齐备且多处超出设计**；
- 失分集中在**结构性偏离**（services→lib、无 types/hooks/shadcn、布局改右侧 Tab、CharacterStore/uiStore 重塑、前端 prompts 下沉后端）与**两项性能/规范缺口**（NarrativePart 未做 store.subscribe 细粒度订阅、IndexedDB 用时间过期代 LRU）；
- 多数偏离属「实现更优/职责重组」而非缺陷，主要处置为**回写设计文档**，仅 §4.3 流式优化与 §9 LRU 驱逐为可选补实现项。
- ⚠️ 设计文档 §3.5「四 store 孤儿」警告已确认过时，应优先更新。
