# def_c14 · 前端 组件 + 页面 + parts 代码缺陷复审

> 切片 C14｜复审基准 2026-06-03｜维度 A（行级证据，以当前文件实际内容为准）
> 范围：`frontend/src/components/**`、`frontend/src/pages/**`、`frontend/src/components/parts/**`、`panels/*`
> 交叉核实：`frontend/src/lib/api.ts` 与 `backend/api/routers/{sessions,worlds,characters,assets}.py` 端点存在性

---

## 一、旧报告条目逐条判定

### STUB-T02 · SessionManager 重命名 PATCH /sessions/{id} 后端缺端点
- 状态：✅已修复
- 类别：stub
- 严重度：🔴核心
- 位置：`frontend/src/components/SessionManager.tsx:68`、`backend/api/routers/sessions.py:303`
- 证据：前端 `await api.patch(\`/sessions/${id}\`, { title: ... })`；后端 `@router.patch("/sessions/{session_id}")` → `async def patch_session(...)`（注释“当前支持 title 重命名”），`PatchSessionRequest.title` 字段存在。
- 修复方向：无需动作；端点与请求体已对齐。

### STUB-T03 · WorldManager 用 'tmp' ID 发 SSE 请求
- 状态：✅已修复
- 类别：stub
- 严重度：🔴核心
- 位置：`frontend/src/components/WorldManager.tsx:261-266, 274, 323, 330, 335`
- 证据：`ensureWorldCreated()` 先 `api.createWorld(...)` 拿到真实 `world_id` 并 `setCreatedWorldId`，`runSSE` 与 `handleFetch/handleParse` 均用真实 `wid`/`createdWorldId` 拼接 `/worlds/${wid}/fetch-lore`，已无 `'tmp'` 占位 ID。
- 修复方向：无需动作。

### T-D20 · WorldManager worldId prop 未用于编辑已有世界
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`frontend/src/components/WorldManager.tsx:474-499, 555-564, 619-622`
- 证据：新增 `WorldInlineEditor` + `handleEditSave(wid, update)` 调 `api.updateWorld`；列表行“编辑”按钮 `setEditingId(w.id)` 后渲染行内编辑器，已有世界可改 name/description。
- 修复方向：无需动作（见 NEW-C14-04 关于创建 Modal 仍无法对已有世界重跑抓取的残留限制）。

### T-D21 · WorldManager 无 api.updateWorld，已有世界只能删不能改
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`frontend/src/lib/api.ts:393`、`backend/api/routers/worlds.py:148`
- 证据：`updateWorld: (wid, req) => apiFetch(\`/worlds/${wid}\`, { method: 'PATCH', ... })`；后端 `@router.patch("/worlds/{wid}")` 存在。
- 修复方向：无需动作。

### T-D22 · AssetLibrary NPC 导入/物品发放 API 存在但无 UI 入口
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`frontend/src/components/AssetLibrary.tsx:211-215（导入会话）, 317-321（发放）`、`backend/api/routers/assets.py:131, 230`
- 证据：NPC 卡片有“导入会话”按钮 → `api.importNpcToSession(npc.id, currentSessionId)`；物品卡片有“发放”按钮 → `api.grantItemToSession(item.id, ...)`；后端 `/assets/npcs/{nid}/import`、`/assets/items/{iid}/grant` 端点均存在。无会话时 `notify.warning` 提示先打开会话。
- 修复方向：无需动作。

### T-D23 · CharacterCreator getCharacterTemplate/updateCharacterTemplate 无 UI
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`frontend/src/components/CharacterCreator.tsx:416-477, 426, 443, 606`
- 证据：`EditModal` 在挂载时 `api.getCharacterTemplate(cid)` 加载，保存时 `api.updateCharacterTemplate(cid, ...)`；卡片 `onEdit={() => setEditId(c.id)}` 打开该 Modal。后端 `characters.py:208 @router.patch("/characters/{cid}")` 存在。
- 修复方向：无需动作。

### T-D24 · SessionManager handleExport 只导出 Session 列表 JSON
- 状态：✅已修复
- 类别：degradation
- 严重度：🟢次要
- 位置：`frontend/src/components/SessionManager.tsx:77-104`
- 证据：`handleExport` 用 `Promise.allSettled` 并发拉取 `getMessages/getParts/getCharacter` 并并入 `exportData.{messages,parts,character}` 后导出，文件名 `session_<id8>.json`。已非仅导出会话元信息。
- 修复方向：无需动作。

### T-D25 · InputBar directSelectOption 未保证父组件 setState
- 状态：🔄已变化（⚠️ 时序脆弱仍存在）
- 类别：optimize
- 严重度：🟢次要
- 位置：`frontend/src/components/InputBar.tsx:135-141`、`frontend/src/pages/SessionPage.tsx:512-513`
- 证据：`handleOptionClick` 调 `onSelectOption?.(opt.text)`（父级 `onSelectOption={(text)=>setInput(text)}`）后 `setTimeout(() => sendBtnRef.current?.click(), 50)`。仍依赖“50ms 内 React 完成 setState + 重渲染、发送按钮的 `value.trim()` 已就绪”这一时序假设；非确定性，而非把待发文本作为参数显式回传给 `onSend`。
- 修复方向：让 `onSelectOption` 直接返回/携带文本触发发送（或父级提供 `onSendText(text)`），去除 setTimeout 竞态。

### M-04 · parts/PartRenderer 未知 type → return null 无降级 UI
- 状态：✅已修复
- 类别：degradation
- 严重度：🟢次要
- 位置：`frontend/src/components/parts/PartRenderer.tsx:169-188`
- 证据：`default` 分支不再静默返回 null，渲染灰色虚线占位块 `未知内容类型：[type: <type>]` 并附 `content` 的 120 字 JSON 预览，便于发现遗漏类型。
- 修复方向：无需动作。

### T-M01 · App.tsx return null 死组件
- 状态：✅已修复
- 类别：dead
- 严重度：🟢次要
- 位置：`frontend/src/main.tsx:13-19`（无 `App.tsx`）
- 证据：Glob `frontend/src/App.tsx` 无结果；`main.tsx` 直接渲染 `<RouterProvider router={router} />` + `<ToastStack/>` + `<ConfirmDialog/>`，死组件已删除。
- 修复方向：无需动作。

### T-M02 · router.tsx /settings /sessions 重定向到组件 ()=>null
- 状态：🔄已变化
- 类别：dead
- 严重度：🟢次要
- 位置：`frontend/src/router.tsx:42-58`
- 证据：`/settings` 与 `/sessions` 改为 `beforeLoad: () => { throw redirect({ to: '/' }) }` 的正规重定向，不再使用 `component: () => null` 死组件。属保留的兼容路由（设置/会话列表已并入首页 Tab）。
- 修复方向：无需动作（如需可在设计文档标注这两条为兼容重定向）。

### T-M15 · MessageThread 注释“虚拟滚动”未实现
- 状态：⚠️仍存在
- 类别：optimize
- 严重度：🟢次要
- 位置：`frontend/src/components/MessageThread.tsx:4, 76, 80`
- 证据：文件头注释“虚拟滚动（当前简单实现）”；实际 `visibleParts = parts.filter(...)` 后 `.map` 全量渲染，无窗口化/虚拟列表。长会话 Part 多时仍全量挂载。
- 修复方向：接入 `@tanstack/react-virtual` 或按可视区窗口化；或更新注释删除“虚拟滚动”措辞以免误导。

---

## 二、新增问题（NEW-C14-xx）

### NEW-C14-01 · createSession 类型缺 world_id / character_template_id，靠 as 强转绕过
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`frontend/src/lib/api.ts:46-51`、`frontend/src/pages/HomePage.tsx:77-82`
- 证据：`CreateSessionReq` 仅声明 `world_plugin/agent_profile/title/character_data`，未含 `world_id`/`character_template_id`；`HomePage.handleCreate` 传入这两字段并 `as Parameters<typeof api.createSession>[0]` 强制绕过 TS。后端 `CreateSessionRequest`（sessions.py:31-32）实际支持，功能正常，但前端类型与契约脱节，失去编译期校验。
- 修复方向：在 `CreateSessionReq` 补 `world_id?: string; character_template_id?: string`，去掉强转。

### NEW-C14-02 · SessionPage 发送后 10s 无条件解锁输入，长生成时会提前放开
- 状态：🆕新发现
- 类别：degradation
- 严重度：🟡降级
- 位置：`frontend/src/pages/SessionPage.tsx:352-356`
- 证据：`await api.sendMessage(...)` 后 `setTimeout(() => setInputDisabled(false), 10_000)` 为无条件兜底解锁；当一次管线生成合法耗时 > 10s 时，输入框会在管线仍运行中重新可用，用户可并发再发一条消息，触发重叠管线（且 SSE `session.idle` 到达前状态被错误清除）。
- 修复方向：兜底解锁前校验是否已收到任何 SSE 进度/未 idle；或显著加长超时并在 `session.idle/error` 才解锁，超时仅做软提示。

### NEW-C14-03 · PromptManager 声称“排序提示”但未按 sort_order 排序
- 状态：🆕新发现
- 类别：unwired
- 严重度：🟢次要
- 位置：`frontend/src/components/PromptManager.tsx:3, 125`、`frontend/src/lib/api.ts:466-469`
- 证据：文件头注释“支持启用/禁用、排序提示”，且 `PromptTemplate.sort_order` 与 `updatePrompt({sort_order})` 均存在，但 `agentPrompts = prompts.filter(p => p.agent === activeAgent)` 未按 `sort_order` 排序，UI 也无拖拽/上移下移控件，排序能力未接线。
- 修复方向：列表 `.sort((a,b)=>a.sort_order-b.sort_order)`，并补上下移按钮回写 `sort_order`；或删除“排序”措辞。

### NEW-C14-04 · WorldModal 仅以 worldId=null 创建，已有世界无法重跑 URL/文档抓取
- 状态：🆕新发现
- 类别：unwired
- 严重度：🟢次要
- 位置：`frontend/src/components/WorldManager.tsx:354-360, 701-703`
- 证据：`WorldModal` 头部恒为“新建世界”，主组件仅 `<WorldModal worldId={null} .../>` 入口；已有世界仅能行内改名或逐条 `handleAddArchive` 手动加条目，无法对其再次走“URL 抓取/文档解析”的 SSE 提炼流程（该能力只在新建流程可达）。`worldId` 形参在编辑场景未被复用。
- 修复方向：在世界行新增“补充抓取”入口，以 `worldId={w.id}` 打开同一 Modal 复用 fetch-lore/parse-document。

### NEW-C14-05 · MessageThread 自动滚底仅依赖 parts.length，流式增量与“是否在底部”均未处理
- 状态：🆕新发现
- 类别：optimize
- 严重度：🟢次要
- 位置：`frontend/src/components/MessageThread.tsx:57-60`
- 证据：`useEffect(... bottomRef.scrollIntoView(...), [parts.length])`，仅在 Part 数量变化时滚动；注释写“仅当在底部时”但代码未检测滚动位置（用户向上翻阅时也会被强拉到底），且单条叙事流式 `streamBuffer` 增量不改变 `parts.length`，长段生成期间视图不跟随。
- 修复方向：依赖增量/内容高度变化触发滚动，并加入“当前是否贴近底部”判断后再 `scrollIntoView`。

---

## 三、小计

| 维度 | 计数 | 条目 |
|---|---|---|
| ✅已修复 | 9 | STUB-T02, STUB-T03, T-D20, T-D21, T-D22, T-D23, T-D24, M-04, T-M01 |
| 🔄已变化 | 2 | T-D25（残留时序脆弱）, T-M02 |
| ⚠️仍存在 | 1 | T-M15 |
| 🆕新发现 | 5 | NEW-C14-01 ~ NEW-C14-05 |

> 总体：旧 12 条中 9 条已修复、2 条转为低危残留/正规重定向、1 条优化项仍存在；新增 5 条多为次要/降级（其中 NEW-C14-02 为 🟡 并发风险最值得优先处理）。
