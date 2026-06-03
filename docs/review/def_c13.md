# 代码缺陷复审 — 分片 C13（前端 stores + lib）

> 复审基准日期：2026-06-03
> 范围：`frontend/src/stores/*`（session/world/character/dice/story/chapter/ui/confirm）+ `frontend/src/lib/*`（api/sse/idb/bindSSEToStores）
> 方法：逐文件通读 + 全前端 Grep 验证「死字段/死 action/未接线 API」是否真无引用，行级证据。

---

## 一、旧报告条目复核

### M-03 · character.ts inventory/activeSkills 字段从未写入
- 状态：🔄已变化（inventory 已修复；activeSkills 仍死）
- 类别：dead
- 严重度：🟢次要
- 位置：`frontend/src/stores/character.ts:64-65, 94-106, 170`
- 证据：`inventory` 现在被写入（`loadCharacter` 106 行 `set({..., inventory ...})`、`applyPatch` 170 行返回 `inventory: normalizeInventory(...)`）且被消费（`pages/SessionPage.tsx:396 <InventoryPanel items={inventory} />`）；但 `activeSkills`（94/106 写入）全局仅出现在 character.ts，无任何组件读取（Grep `activeSkills` 仅命中 store 自身）。
- 修复方向：要么在某技能面板消费 `activeSkills`，要么删除该 state 字段。

### T-D15 · api.ts deleteSession 用裸 fetch 不走 apiFetch
- 状态：✅已修复
- 类别：degradation
- 严重度：🟢次要
- 位置：`frontend/src/lib/api.ts:291-292`
- 证据：`deleteSession: (sessionId) => apiFetch<{deleted:boolean}>(\`/sessions/${sessionId}\`, { method:'DELETE' })`，已走统一 `apiFetch`（含 `!res.ok` 抛错）；调用点 `components/SessionManager.tsx:52`。
- 修复方向：无需动作。

### T-D16 · importNpcToSession/grantItemToSession 已定义但无 UI 调用
- 状态：✅已修复
- 类别：unwired
- 严重度：🟢次要
- 位置：`frontend/src/lib/api.ts:442, 458`
- 证据：两者均在资产库被接线——`components/AssetLibrary.tsx:171 await api.importNpcToSession(npcId, currentSessionId)`、`AssetLibrary.tsx:261 await api.grantItemToSession(itemId, currentSessionId)`。
- 修复方向：无需动作。

### T-D17 · story.ts loadMessages action 从未被调用
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`frontend/src/stores/story.ts:99-113`
- 证据：`pages/SessionPage.tsx:101` 解构 `loadMessages`，`SessionPage.tsx:191 loadMessages(sessionId)` 实际调用。
- 修复方向：无需动作。

### T-D18 · world.ts loadNpcs 从 archives 推导而非请求 /npcs
- 状态：⚠️仍存在（且现已彻底变成死代码）
- 类别：degradation + dead
- 严重度：🟡降级
- 位置：`frontend/src/stores/world.ts:72-83`
- 证据：store 的 `loadNpcs(_sessionId)` 仍忽略 sessionId、从 `archives.filter(a.archive_type==='npc')` 推导 npcs（72-83 行，参数名 `_sessionId` 标志未用）；而真正的 NPC 列表已改由 `components/panels/WorldPanel.tsx:56-63` 内部本地 `loadNpcs` → `api.listSessionNpcs(sessionId)` + 本地 `setNpcs` 提供。故 store 的 `loadNpcs`/`npcs` 全局无外部消费者（Grep `loadNpcs` 命中均为 WorldPanel 本地函数与 world.ts 自身）。
- 修复方向：删除 store 的 `loadNpcs`/`npcs`（已被 WorldPanel 本地实现取代），或改 store 直接调 `api.listSessionNpcs` 并让 WorldPanel 消费。

### T-D19 · ui.ts theme 只改内存无持久化
- 状态：✅已修复
- 类别：degradation
- 严重度：🟢次要
- 位置：`frontend/src/stores/ui.ts:52-60, 102-111`
- 证据：`_loadPersistedTheme()` 启动读 `localStorage.getItem('za_theme')`（52-60），`setTheme` 写 `localStorage.setItem('za_theme', theme)` 并 `applyTheme(theme)`（105-110）。
- 修复方向：无需动作。

### T-M03 · character.ts pushSnapshot/restoreSnapshot/clearSnapshots 无 UI 调用
- 状态：⚠️仍存在
- 类别：dead
- 严重度：🟢次要
- 位置：`frontend/src/stores/character.ts:180-203`
- 证据：三个 action 全局仅出现在 character.ts 自身（Grep `pushSnapshot|restoreSnapshot|clearSnapshots` 无其他命中）。`applyPatch`（120-124 行）内部已自动 push 快照，但「显式 push / 回滚 / 清空」对外无调用者——尤其 `restoreSnapshot`（state_patch 回滚 affordance）无任何 UI 触发；`clearSnapshots` 未在切换 session 时被调（注释声称应在切 session 调用，实际未接）。
- 修复方向：在角色面板/撤销按钮接线 `restoreSnapshot`，并在 `selectSession`/`clearSession` 时调 `clearSnapshots`；否则删除冗余 action。

### T-M04 · dice.ts 仅内存 history 不调 api.getDiceHistory
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`frontend/src/stores/dice.ts:69-102`
- 证据：`loadHistory` 现调用 `api.getDiceHistory(sessionId, 50)`（71 行）并映射后端字段；调用点 `pages/SessionPage.tsx:105`（`loadHistory: loadDiceHistory`）+ `SessionPage.tsx:193 loadDiceHistory(sessionId)`。（另：`DicePanel.tsx:34` 亦直接调 `api.getDiceHistory`。）
- 修复方向：无需动作。

### T-M05 · api.ts 6 个死 API 方法
- 状态：✅已修复（5 个已接线，1 个已删除）
- 类别：unwired
- 严重度：🟢次要
- 位置：`frontend/src/lib/api.ts:185, 187, 191, 205, 312`
- 证据：`listWorldPlugins`→`pages/SettingsPage.tsx:133`；`listMcpServers`→`SettingsPage.tsx:727`；`connectMcp`→`SettingsPage.tsx:738`；`disconnectMcp`→`SettingsPage.tsx:750`；`getWritingStyles`→`components/panels/WritingStylePanel.tsx:53`。`listAgentProfiles` 在当前 api.ts 中已不存在（Grep 无命中），即已删除而非遗留死方法。
- 修复方向：无需动作。

### T-M14 · story.ts 注释"虚拟滚动"实为普通 map
- 状态：🔄已变化（注释已不在 story.ts，移至渲染组件，问题本体仍在）
- 类别：optimize
- 严重度：🟢次要
- 位置：`frontend/src/components/MessageThread.tsx:4, 76-89`
- 证据：story.ts 已无「虚拟滚动」字样；该声明现位于 `MessageThread.tsx:4`「虚拟滚动（当前简单实现）」，但渲染仍是 `visibleParts.map(...)`（80 行）全量渲染，无 windowing/虚拟化，长会话仍全量挂载 DOM。
- 修复方向：注释改为「全量渲染」，或引入 react-window/virtuoso 真正虚拟化。

---

## 二、新发现（NEW-C13-*）

### NEW-C13-01 · api.ts 重复且死的 NPC CRUD 方法
- 状态：🆕新发现
- 类别：dead
- 严重度：🟢次要
- 位置：`frontend/src/lib/api.ts:353-372`
- 证据：`listNpcs/createNpc/updateNpc/deleteNpc`（353-372）与上方 `listSessionNpcs/createSessionNpc/updateSessionNpc/deleteSessionNpc`（253-266）指向同一组 `/sessions/{id}/npcs` 端点，属重复定义；Grep `api.listNpcs|api.createNpc|api.updateNpc|api.deleteNpc` 全前端无任何调用（实际接线的是 `Session*` 系列，见 WorldPanel:59/77）。
- 修复方向：删除 353-372 这组未使用的重复方法，统一用 `*SessionNpc` 系列。

### NEW-C13-02 · world store addArchive / npcs 字段为死状态
- 状态：🆕新发现
- 类别：dead
- 严重度：🟢次要
- 位置：`frontend/src/stores/world.ts:27-28, 36, 69-70, 72-83`
- 证据：`addArchive` 仅在 world.ts 内定义（Grep 无外部 `addArchive` 调用，新档案由 WorldPanel 调 `loadArchives` 重拉而非 push）；`npcs` 数组与 `loadNpcs` 同 T-D18，均无消费者（WorldPanel 用本地 `npcs` state）。整个 store 实际只有 `archives/loadArchives/setWorldPlugin` 被用。
- 修复方向：精简 world store，删除 `npcs/loadNpcs/addArchive` 或将 WorldPanel 的 NPC 状态迁回 store 统一管理。

### NEW-C13-03 · stores 多处裸 fetch 绕过 apiFetch 统一错误处理
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`frontend/src/stores/story.ts:103,119,197`、`stores/world.ts:57`、`stores/chapter.ts:66`
- 证据：`loadMessages`/`loadParts`/`revertToMessage`（story）、`loadArchives`（world）、`loadChapters`（chapter）均用原生 `fetch('/api/...')`，与 `lib/api.ts` 的 `apiFetch`（统一 header + `!res.ok` 抛错带 body）并存，错误处理不一致（部分仅 `catch` 静默吞错，无 toast）。与已修复的 T-D15 同源问题，但发生在 store 层。
- 修复方向：将上述请求改走 `api.getMessagesPaged`/`api.getParts`/`api.revertToMessage`/`api.getWorldArchives`/`api.getChapters`，统一错误语义。

### NEW-C13-04 · api.getChapters / getParts 等已被 store 裸 fetch 架空
- 状态：🆕新发现
- 类别：dead
- 严重度：🟢次要
- 位置：`frontend/src/lib/api.ts:138-139(getChapters), 150-157(getParts)`
- 证据：`chapter.ts:66` 自行 `fetch('/chapters')`、`story.ts:119` 自行 `fetch('/parts')`，导致 `api.getChapters`/`api.getParts` 全前端无调用（Grep `api.getChapters` 无命中）。与 NEW-C13-03 互为表里：定义了规范方法却被裸 fetch 旁路。
- 修复方向：与 NEW-C13-03 一并整改，让 store 复用这些方法或删除冗余定义。

---

## 三、小计

| 分类 | 计数 | 条目 |
|---|---|---|
| ✅ 已修复 | 6 | T-D15, T-D16, T-D17, T-D19, T-M04, T-M05 |
| ⚠️ 仍存在 | 2 | T-D18, T-M03 |
| 🔄 已变化 | 2 | M-03（inventory 修复/activeSkills 仍死）, T-M14（注释移位，本体未优化） |
| 🆕 新发现 | 4 | NEW-C13-01, NEW-C13-02, NEW-C13-03, NEW-C13-04 |

**仍死/未接线的字段与方法清单（行级）**：
- `character.ts` `activeSkills`（M-03）— 写入未读取
- `character.ts` `pushSnapshot` / `restoreSnapshot` / `clearSnapshots`（T-M03）— 3 个 action 无 UI 调用
- `world.ts` `loadNpcs` / `npcs` / `addArchive`（T-D18 + NEW-C13-02）— store 层被 WorldPanel 本地态架空
- `api.ts` `listNpcs` / `createNpc` / `updateNpc` / `deleteNpc`（NEW-C13-01）— 4 个重复死方法
- `api.ts` `getChapters` / `getParts`（NEW-C13-04）— 2 个被裸 fetch 旁路

合计仍死/未接线 **13** 项（1 字段 + 3 快照 action + 3 world store 成员 + 6 api 方法）。
