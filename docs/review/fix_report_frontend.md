# 前端缺陷修复报告（2026-06）

> 范围：仅 `frontend/`。基准证据：`docs/review/def_c13.md`、`def_c14.md`、`conf_b09.md`、`REVIEW_TODO_2026-06.md`。
> 构建验证：`npm install` + `npm run build`（tsc -b && vite build）均通过。

| item | status | evidence(file:line) | note |
|---|---|---|---|
| P0-5 · Hub 会话 Tab 合并「列表+创建」 | ✅真实实现 | `frontend/src/pages/HomePage.tsx:40,95-101,189-193,239`（移除独立 `archives` Tab，会话 Tab 顶部「+新建会话」折叠面板 + 下方 `SessionManager` 列表） | 创建与存档列表合并到同一「会话」Tab；导航去掉「存档」项 |
| NEW-C14-02 · 按生成完成事件解锁输入（替代固定 10s） | ✅真实实现 | `frontend/src/pages/SessionPage.tsx:120-149,355-359`、`bindSSEToStores.ts:46,63-66`（`onActivity` 活动计数 + 空闲看门狗） | 由 `session.idle/error` 即时解锁；兜底仅在「30s 无任何新 SSE 活动」时软解锁，长生成不再被提前放开 |
| NEW-C13-03 · stores 裸 fetch 统一走 apiFetch | ✅真实实现 | `frontend/src/lib/api.ts:91`（导出 `apiFetch`）、`stores/story.ts:103-126,196-201`、`stores/world.ts:54-66`、`stores/chapter.ts:63-71` | story 用 `apiFetch`/`api.revertToMessage`，world 用 `api.getWorldArchives`，chapter 用 `api.getChapters`；统一错误/baseURL 语义 |
| 死字段清理 · character.activeSkills | ✅真实实现 | `frontend/src/stores/character.ts`（删除字段、初值、写入逻辑） | 全前端无消费者，已删 |
| 死字段清理 · 3 个快照 action + snapshotHistory | ✅真实实现 | `frontend/src/stores/character.ts`（删除 `pushSnapshot/restoreSnapshot/clearSnapshots`、`snapshotHistory`、`CharacterSnapshot`、`SNAPSHOT_LIMIT`，并清理 applyPatch 内自动快照） | 无 UI 调用，连带删除无消费者的快照队列与自动 push |
| 死字段清理 · world store loadNpcs/npcs/addArchive | ✅真实实现 | `frontend/src/stores/world.ts:8-39`（删除 `NpcProfile`/`npcs`/`loadNpcs`/`addArchive`，reset 同步精简） | NPC 列表由 `WorldPanel` 本地 `api.listSessionNpcs` 管理，store 层已无消费者 |
| 死代码清理 · 重复 NPC CRUD（NEW-C13-01） | ✅真实实现 | `frontend/src/lib/api.ts:353` 处（删除 `listNpcs/createNpc/updateNpc/deleteNpc`） | 与 `*SessionNpc` 系列重复且无调用，已删 |
| 死代码清理 · api.getChapters 被旁路（NEW-C13-04） | ✅真实实现 | `frontend/src/stores/chapter.ts:65-67`（loadChapters 改用 `api.getChapters`） | 复活 getChapters；`api.getParts` 仍被 `SessionManager.tsx:85` 使用，故保留 |
| NEW-C14-01 · CreateSessionReq 缺字段靠 as 强转 | ✅真实实现 | `frontend/src/lib/api.ts:46-58`（补 `world_id?`/`character_template_id?`）、`HomePage.tsx:77-82`（移除 `as` 强转） | 恢复编译期校验 |
| NEW-C14-03 · PromptManager 未按 sort_order 排序 | ✅真实实现 | `frontend/src/components/PromptManager.tsx:128-156,261-266`（按 sort_order 排序 + 上/下移控件，归一化写回 sort_order） | 列表稳定排序，新增 ▲▼ 重排按钮 |
| NEW-C14-04 · WorldModal 已有世界无法重跑抓取 | ✅真实实现 | `frontend/src/components/WorldManager.tsx:236-260,357-359,503-507,639-651,701-709`（worldId+initial 预填、标题区分、世界行「补充抓取」入口、统一 modalState） | 已有世界可再次走 URL 抓取/文档解析 SSE 流程 |
| conf_b09 · SSE 在 HTTP 4xx 终止重连 | ✅真实实现 | `frontend/src/lib/sse.ts:90-97,114-160`（onerror→`_handleError`→`_probeTerminal` 探测状态码，4xx 终止并派发 `connection.failed`，否则退避） | 4xx（404/410/401/403）停止重连；非 4xx 指数退避（含 jitter） |
| conf_b09 · 超限/失败派发 connection.failed + UI 提示 | ✅真实实现 | `frontend/src/lib/sse.ts:128-138`、`bindSSEToStores.ts:178-198`（connection.failed → 解锁 + dm_note 提示 + 派发窗口事件） | 补齐设计 §5「超 maxRetry → connection.failed」缺口与 UI 提示 |
| D21 · 升级 Tailwind 到 v4 | ✅真实实现 | `package.json:22-30`（`tailwindcss ^4.1`、新增 `@tailwindcss/postcss ^4.1`、移除 autoprefixer）、`postcss.config.js`、`src/index.css:1-4`（`@import "tailwindcss"` + `@config`）、`tailwind.config.js` | 构建产出 CSS 49.11 kB，样式正常生成 |
| D22 · IndexedDB 改 LRU 驱逐 | ✅真实实现 | `frontend/src/lib/idb.ts:44-118`（`STORE_LIMITS`、`enforceLimit` 按 `ts` 升序驱逐、`idbTouch` 读时刷新 last-access；getSession/getCharacter/getPartsBySession 触碰） | 由「仅时间过期」升级为「时间过期 + LRU（最后访问）」；`sse_cursor:` 续传游标不被驱逐 |
| 前端优化 · 自动滚底不仅依赖 parts.length（NEW-C14-05） | ✅真实实现 | `frontend/src/components/MessageThread.tsx:55-77,90`（贴底判定 `nearBottomRef` + 流式增量签名 `streamSignature` 触发滚动） | 用户上翻历史时不被强拉到底；流式增量持续跟随 |
| 前端优化 · 虚拟滚动注释/实现（T-M15） | ⚠️部分 | `frontend/src/components/MessageThread.tsx:1-6`（注释改为「全量渲染」） | 未引入 react-window/virtuoso 真正窗口化（避免新增依赖/破坏渲染，按「保持安全」取舍）；仅修正误导性注释并改进滚动跟随 |
| 前端优化 · NarrativePart 细粒度订阅（conf_b12） | ❌未实现 | — | 本批次未触及 NarrativePart 的 store.subscribe 细粒度订阅改造；与构建无关，留待后续 |

## 构建结果

`npm install`：`added 11 packages, removed 61 packages ... found 0 vulnerabilities`

`npm run build` 最终输出关键行：

```
> tsc -b && vite build
vite v6.4.2 building for production...
✓ 177 modules transformed.
dist/assets/index-cI6vSYh7.css   49.11 kB │ gzip:   8.98 kB
dist/assets/index-Bq56gnZq.js   494.66 kB │ gzip: 145.17 kB
✓ built in 1.65s
```

退出码 0；唯一告警为 vite 的 `idb.ts` 同时被静态/动态 import 的分包提示（非错误，story.ts 既有的静态 `cache` 引用所致，不影响产物）。

## 说明（部分/未实现项）

- **T-M15（虚拟滚动）标 ⚠️部分**：仅在不引入第三方库、不改变现有 DOM 渲染契约的前提下修正了误导注释并增强了滚动跟随；真正的列表虚拟化需新增依赖（react-window 等），为避免破坏 PartRenderer 的全量挂载假设，按任务「保持安全」原则未做，标记为部分完成。
- **conf_b12 / NarrativePart 细粒度订阅标 ❌**：属 P3 优化项，本批次聚焦 P0/P1/P2 与指定项；未改动以免影响流式渲染稳定性。
- 其余 14 项均为真实实现并随 `npm run build` 通过编译。
