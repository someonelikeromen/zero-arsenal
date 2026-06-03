# def_c16 · UX / 新手体验接线核实

> 复审子代理 C16 | 维度 A（代码缺陷复审，"未接线" 归入 unwired 类别）
> 基准：`docs/comparison/06-ux-gap-action-plan.md` P0/P1 清单 + `00-executive-summary.md`
> 复审对象：`frontend/src/` 当前实际代码（行级证据，只读复审）

核对结论概览：comparison 报告写于 2026-06-03，断言"基础设施已有但零接线"。
当前代码已大幅推进——P0 五项中 3 项已真正接线生效，1 项部分接线，1 项仍未接线。

---

### NEW-C16-01 · P0-1 Toast 通知系统已全量接线
- 状态：✅已修复
- 类别：unwired（原"零调用"已消除）
- 严重度：🟡降级
- 位置：`frontend/src/main.tsx:16`、`frontend/src/stores/ui.ts:142-151`
- 证据：`<ToastStack />` 已在根渲染挂载；`notify.success/error/warning` 被 14+ 文件、40+ 处调用（`WorldManager.tsx`、`SettingsPage.tsx`、`CharacterCreator.tsx`、`AssetLibrary.tsx`、`ChapterTree.tsx`、`SessionManager.tsx` 等创建/删除/保存/导入操作均已接 toast 反馈）。
- 修复方向：无需动作。报告所述"全项目零调用"已不成立。

### NEW-C16-02 · P0-2 统一确认对话框已替换 window.confirm
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`frontend/src/main.tsx:17`、`frontend/src/stores/confirm.ts:55`
- 证据：`<ConfirmDialog />` 已挂载；`requestConfirm(...)` 在 `WorldPanel`/`WorldManager`/`ScraperRulesPanel`/`MemoryPanel`/`ChapterTree`/`CharacterCreator`/`HistoryPanel`/`PromptManager`/`SessionManager`/`AssetLibrary`/`SessionPage` 共 11 个组件的危险操作调用；全仓 `window.confirm` 仅剩 2 处源码**注释**（`ConfirmDialog.tsx:3`、`confirm.ts:4`），无任何残留真实调用。
- 修复方向：无需动作。

### NEW-C16-03 · P0-3 危险操作内联 Warning 文字仅在确认弹窗内，缺独立内联红字
- 状态：🔄已变化
- 类别：unwired（部分接线）
- 严重度：🟢次要
- 位置：`SessionManager.tsx:46`、`WorldManager.tsx:541`、`ChapterTree.tsx:55`、`CharacterCreator.tsx:531`、`WorldPanel.tsx:73`
- 证据：危险操作的"此操作不可撤销 / 此操作将删除之后的叙事内容"等警示语**已写入 `requestConfirm` 的 message**，弹窗内有警告；但报告 P0-3 要求的"按钮下方/旁边一行 `text-amber-500` 静态内联小字"（KoboldCpp 风格、点击前可见）在设置/重置类按钮处**未见**（`SettingsPage.tsx` 重置/覆盖按钮无内联警告）。
- 修复方向：在破坏性按钮旁补 `<p className="text-xs text-amber-500">` 静态提示，与确认弹窗互补。

### NEW-C16-04 · P0-4 首次进入 LLM 配置检测 Banner 已挂载且有检测逻辑
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`frontend/src/components/LlmConfigBanner.tsx:14-25`、`frontend/src/pages/HomePage.tsx:311`
- 证据：`<LlmConfigBanner onGoSettings={() => setActiveTab('settings')} />` 已挂在 Hub 内容区顶部；组件内 `api.getLlmRoutes()` 判空（无路由→橙色"去配置"）+ `api.getMemoryHealth()` 判降级（黄色提示），正常时返回 `null`。检测逻辑真实生效，并非空壳。
- 修复方向：无需动作（覆盖度甚至超出报告，含记忆降级提示）。

### NEW-C16-05 · P0-5 Hub 会话 Tab 仍未合并列表+创建（创建与历史割裂）
- 状态：⚠️仍存在
- 类别：unwired
- 严重度：🔴核心（报告标注为"IA 核心问题"）
- 位置：`frontend/src/pages/HomePage.tsx:236-237`（sessions→`SessionsTab` 仅创建）、`HomePage.tsx:244-245`（archives→`SessionManager` 才是历史列表）
- 证据：`SessionsTab` 自上而下只有"新建会话"表单（标题/世界/人物选择 + `handleCreate`），**无历史会话列表、无搜索**；历史会话列表仍单独留在「存档」Tab 的 `<SessionManager>`。报告 P0-5 要求的"Sessions Tab 显示会话列表(最近N条+搜索)+顶部新建按钮，存档改为章节快照"**未实施**，两处仍割裂。
- 修复方向：将 `SessionManager` 的列表/搜索并入 `SessionsTab`，存档 Tab 收敛为 chapter_anchors 快照。

### NEW-C16-06 · 主题切换持久化全链路已接线
- 状态：✅已修复
- 类别：unwired
- 严重度：🟢次要
- 位置：`ThemeGuideModal.tsx:31-35`、`stores/ui.ts:102-111`、`main.tsx:11`
- 证据：`ThemeGuideModal` 在 `HomePage.tsx:259` 按 `shouldShowThemeGuide()`（`za_has_visited`）首访弹出；`setTheme` 写 `localStorage('za_theme')` 并 `applyTheme`；启动时 `main.tsx:11` `applyTheme(useUIStore.getState().theme)` 还原。持久化 + 首启应用双向闭环。
- 修复方向：无需动作。

### NEW-C16-07 · 文风选择器 UI 已接 GET/PUT /config 与 /sessions writing-styles
- 状态：✅已修复
- 类别：dead（原标"死 API"已激活）
- 严重度：🟡降级
- 位置：`components/panels/WritingStylePanel.tsx:53-78`、`lib/api.ts:205-211`、`pages/SessionPage.tsx:33,390`
- 证据：`api.getWritingStyles()`(`GET /config/writing-styles`) + `getSessionWritingStyles` 在面板加载时并行拉取，`setSessionWritingStyles`(`PUT /sessions/{id}/writing-styles`) 保存；面板按四层模型 chip 渲染，已在 `SessionPage` 右栏 `rightTab === 'writing'` 处 lazy 挂载。原 STUB_ANALYSIS "死 API" 判定已失效。
- 修复方向：无需动作。

### NEW-C16-08 · P1-1 会话创建仍为单页表单，未做多步向导（无游戏类型步）
- 状态：⚠️仍存在
- 类别：unwired（部分增强）
- 严重度：🟡降级
- 位置：`frontend/src/pages/HomePage.tsx:95-188`（`SessionsTab`）
- 证据：当前是**增强版单页表单**（含世界/人物卡片预览 + 空状态引导 + localStorage 记忆上次选择），但报告 P1-1 的"4 步向导（Step1 游戏类型选择 + 一句话模式描述 / Step4 开局设定）"**未实现**，无分步结构、无游戏类型（TRPG/单人 RP/写作协作/沙盒）选择。
- 修复方向：按报告 4 步结构改造，或在设计文档中明确降级为单页表单。

### NEW-C16-09 · P1-2 First Message 自动触发已接线（角色 first_message + 自动开场）
- 状态：✅已修复
- 类别：unwired
- 严重度：🟡降级
- 位置：`CharacterCreator.tsx:59,155,308-311`、`SessionPage.tsx:233-250`、`lib/api.ts:175`
- 证据：`CharacterCreator` 已有 `firstMessage` 字段并随档案提交（`first_message: firstMessage`）；`SessionPage` 用 `openingTriedRef` 去重，1200ms 后判定 `parts.length === 0` 即调 `api.generateOpening(sessionId)`（`POST`），`status==='skipped'` 才解禁输入，并有"正在生成开场叙事..."提示（`SessionPage.tsx:488`）。自动开场闭环成立。
- 修复方向：无需动作。

### NEW-C16-10 · P1-4 输入框状态机 placeholder 已接线（含 # 知识库触发）
- 状态：✅已修复
- 类别：unwired
- 严重度：🟢次要
- 位置：`components/InputBar.tsx:33-41,79`、`pages/SessionPage.tsx:117,226-228,514`
- 证据：`InputBar` 定义 `SystemState`('no_llm'|'no_world'|'no_character'|'ready') + `STATE_PLACEHOLDER` 四态文案，`notReady` 时禁用并显示对应警示；`SessionPage` 检测 `getLlmRoutes`/`getSession` 后 `setSystemState('no_llm'|'no_world'|'ready')` 并传入 `systemState`。额外接了 P2-6 的 `#` Lorebook 下拉。
- 缺口（次要）：状态机定义了 `no_character`，但 `SessionPage:226-228` 检测分支从未 `setSystemState('no_character')`（仅 no_llm/no_world/ready），该态为死分支。
- 修复方向：无需大改；如需可补 character_id 缺失判定，或移除未用态。

---

## 小计

| 维度 A 状态 | 计数 | 条目 |
|---|---|---|
| ✅已修复（已真正接线） | 7 | C16-01/02/04/06/07/09/10 |
| 🔄已变化（部分接线） | 2 | C16-03（危险内联字仅在弹窗）、C16-08（单页非向导） |
| ⚠️仍存在（未接线） | 1 | C16-05（Hub 会话 Tab 未合并） |
| 🆕新发现 | 0 | （C16-10 含 1 个 no_character 死分支，归次要） |

**接线类别小计（unwired/dead 维度）**：核对 10 项，✅真正接线 7 项，🔄部分 2 项，⚠️未接线 1 项。

**原 P0 五项接线现状**：P0-1 Toast ✅、P0-2 确认框 ✅、P0-4 配置 Banner ✅ 已接线；P0-3 危险内联 Warning 🔄部分；P0-5 Hub 会话 Tab 合并 ⚠️未接线。
