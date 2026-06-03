# 12 · 前端架构设计

> **参考来源**：MoRanJiangHu 前端的 `subsystems/zustandStore` 模式 + IndexedDB 本地缓存设计；
> opencode TUI 的差分渲染思想；pi `setActiveTools` 工具集切换。

---

## 1. 技术选型

### 1.1 核心技术栈

| 层次 | 技术 | 版本 | 选型理由 |
|------|------|------|---------|
| UI 框架 | React | 19 | Concurrent Mode + use() hook；流式渲染天然契合 SSE delta |
| 类型系统 | TypeScript | 5.5+ | 严格类型约束，Part 类型联合体安全 |
| 构建工具 | Vite | 6 | 极速 HMR，原生 ESM，SSE 开发代理无需额外配置 |
| 样式系统 | Tailwind CSS | 4 | utility-first，替代 MoRanJiangHu 的自定义 CSS 体系 |
| 组件库 | shadcn/ui | latest | 基于 Radix UI，无样式侵入，可完全自定义 |
| 状态管理 | Zustand | 5 | 轻量、无 Redux 样板、与 React 19 并发安全 |
| 本地存储 | IndexedDB（via idb） | 8 | 存储 Part 数据，刷新后快速恢复 |
| SSE 客户端 | 自实现 SSEClient | — | 支持 `Last-Event-ID` 断线重连 + 指数退避 |
| 路由 | TanStack Router | 1.x | 类型安全路由，比 React Router v6 更好的 TS 支持 |

### 1.2 为什么选择 Tailwind + shadcn/ui

MoRanJiangHu 使用了大量手写 CSS 类和自定义变量，维护成本高。
Tailwind + shadcn/ui 的优势：

- **设计系统内置**：通过 CSS 变量实现暗色/亮色主题切换，一行代码搞定
- **shadcn/ui 的骰子面板、对话框（PermissionDialog）有现成 Radix 基础**
- **不锁定版本**：shadcn/ui 将组件代码复制到项目内，可随意修改

### 1.3 项目结构

```
src/
├── components/
│   ├── layout/          # Header、三栏布局
│   ├── parts/           # Part 渲染器（核心，见第 4 节）
│   ├── chapter/         # ChapterTree
│   ├── character/       # CharacterPanel、属性展示
│   ├── dice/            # DiceRollPart、DicePanel
│   └── ui/              # shadcn/ui 组件（复制入项目）
├── stores/              # Zustand store 切片（见第 3 节）
├── services/
│   ├── sse-client.ts    # SSE 客户端（见第 5 节）
│   ├── api-client.ts    # REST API 封装
│   └── idb-cache.ts     # IndexedDB 缓存层（见第 9 节）
├── hooks/               # 自定义 React hooks
├── types/               # TypeScript 类型定义
│   ├── session.ts
│   ├── parts.ts         # MessagePart 联合类型
│   ├── character.ts
│   └── events.ts        # BusEvent 类型
├── pages/
│   ├── SessionPage.tsx  # 主游戏页面
│   ├── LobbyPage.tsx    # 会话列表
│   └── ConfigPage.tsx   # 配置页面
└── main.tsx
```

---

## 2. 页面布局

### 2.1 总体布局

```
┌─────────────────────────────────────────────────────────────────┐
│  Header                                                          │
│  [会话标题]  [世界插件: MLA]  [● play ○ plan ○ review]  [设置]   │
├──────────────┬───────────────────────────────┬──────────────────┤
│              │                               │                  │
│  章节树       │       主叙事区                 │  角色卡侧边栏      │
│  ChapterTree │       StoryCanvas             │  CharacterPanel  │
│              │       (Part 渲染)              │                  │
│  ● 序章 ✓   │                               │  林峰             │
│  ● 第一章    │  [叙事文本流式输出]             │  HP ████░ 7/7   │
│    ├ 主线    │  [骰子结果卡片]                │  SP 2400         │
│    └ 分支①  │  [DM 注释（折叠）]             │                  │
│              │  [NPC 对话气泡]               │  属性/技能折叠     │
│              │  [奖励提示 Toast]             │  装备列表          │
│              │                               │  伏笔列表          │
│  [+ 新分支]  │                               │                  │
├──────────────┴───────────────────────────────┴──────────────────┤
│  骰子面板（▼ 展开）   DM工具箱（▼ 展开）                          │
│  d10 ● ● ○ ○ ○  成功 4/7  [重投]  [修正 ±1]                    │
├─────────────────────────────────────────────────────────────────┤
│  [A: 迎战]  [B: 撤退]  [C: 呼叫支援]  [D: 自定义...]             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  输入框（也可直接描述行动）                                  │   │
│  └──────────────────────────────────────────────────────────┘   │
│  [发送]                                                          │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 响应式断点

| 断点 | 布局调整 |
|------|---------|
| `< 768px`（手机） | 单栏，章节树和角色卡收入底部抽屉 |
| `768px ~ 1280px`（平板） | 双栏（叙事区 + 角色卡），章节树收入左侧抽屉 |
| `> 1280px`（桌面） | 三栏完整布局 |

### 2.3 布局组件结构

```tsx
// pages/SessionPage.tsx
export const SessionPage: React.FC = () => {
    const { sessionId } = useParams()

    return (
        <div className="flex flex-col h-screen bg-background">
            <SessionHeader sessionId={sessionId} />
            <main className="flex flex-1 overflow-hidden">
                <aside className="w-64 hidden xl:flex flex-col border-r">
                    <ChapterTree sessionId={sessionId} />
                </aside>
                <section className="flex-1 flex flex-col overflow-hidden">
                    <StoryCanvas sessionId={sessionId} />
                    <DicePanel />
                    <PlayerInputBar sessionId={sessionId} />
                </section>
                <aside className="w-80 hidden lg:flex flex-col border-l">
                    <CharacterPanel sessionId={sessionId} />
                </aside>
            </main>
        </div>
    )
}
```

---

## 3. Zustand Store 切片

### 3.1 设计原则

来自 MoRanJiangHu 的 `subsystems/zustandStore` 模式：
- 每个关注点独立一个 store 文件
- Store 之间通过 action 调用而非直接订阅对方
- 使用 `immer` middleware 简化深层嵌套更新
- 敏感状态（角色卡）使用 `devtools` 中间件方便调试

### 3.2 SessionStore

```typescript
// stores/sessionStore.ts
import { create } from 'zustand'
import { devtools } from 'zustand/middleware'

interface Session {
    sessionId: string
    title: string
    worldPlugin: string
    currentMode: 'play' | 'plan' | 'review'
    status: 'active' | 'processing' | 'idle' | 'error'
    lastActiveAt: string
}

interface SessionStore {
    currentSessionId: string | null
    sessions: Session[]
    currentMode: 'play' | 'plan' | 'review'

    // Actions
    setCurrentSession: (sessionId: string) => void
    setMode: (mode: 'play' | 'plan' | 'review') => void
    setSessionStatus: (sessionId: string, status: Session['status']) => void
    loadSessions: () => Promise<void>
    createSession: (params: CreateSessionParams) => Promise<Session>
}

export const useSessionStore = create<SessionStore>()(
    devtools(
        (set, get) => ({
            currentSessionId: null,
            sessions: [],
            currentMode: 'play',

            setCurrentSession: (sessionId) =>
                set({ currentSessionId: sessionId }),

            setMode: async (mode) => {
                const { currentSessionId } = get()
                if (!currentSessionId) return
                await apiClient.post(`/sessions/${currentSessionId}/mode`, { mode })
                set({ currentMode: mode })
            },

            setSessionStatus: (sessionId, status) =>
                set((state) => ({
                    sessions: state.sessions.map((s) =>
                        s.sessionId === sessionId ? { ...s, status } : s
                    ),
                })),

            loadSessions: async () => {
                const data = await apiClient.get('/sessions')
                set({ sessions: data.items })
            },

            createSession: async (params) => {
                const session = await apiClient.post('/sessions', params)
                set((state) => ({ sessions: [session, ...state.sessions] }))
                return session
            },
        }),
        { name: 'SessionStore' }
    )
)
```

### 3.3 StoryStore（正文消息和 Part）

```typescript
// stores/storyStore.ts
import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'

export type PartType =
    | 'narrative'
    | 'dice_roll'
    | 'state_patch'
    | 'dm_note'
    | 'npc_action'
    | 'system_grant'
    | 'chapter_end'
    | 'permission_ask'

export interface MessagePart {
    partId: string
    messageId: string
    type: PartType
    content: string | null
    payload: Record<string, unknown> | null
    isStreaming: boolean
    createdAt: string
}

interface StoryStore {
    messages: Message[]
    parts: Record<string, MessagePart>
    streamingPartIds: Set<string>

    // SSE 事件处理 actions
    createPart: (data: { partId: string; type: PartType; messageId: string }) => void
    appendPartDelta: (data: { partId: string; delta: string }) => void
    finalizePart: (data: { partId: string; finalContent?: string; payload?: unknown }) => void

    // REST 加载
    loadMessages: (sessionId: string) => Promise<void>
    loadParts: (sessionId: string) => Promise<void>

    // 回滚清理
    revertToMessage: (messageId: string) => void
}

export const useStoryStore = create<StoryStore>()(
    immer((set) => ({
        messages: [],
        parts: {},
        streamingPartIds: new Set(),

        createPart: ({ partId, type, messageId }) =>
            set((state) => {
                state.parts[partId] = {
                    partId,
                    messageId,
                    type,
                    content: type === 'narrative' ? '' : null,
                    payload: null,
                    isStreaming: true,
                    createdAt: new Date().toISOString(),
                }
                state.streamingPartIds.add(partId)
            }),

        appendPartDelta: ({ partId, delta }) =>
            set((state) => {
                const part = state.parts[partId]
                if (part && part.type === 'narrative') {
                    part.content = (part.content ?? '') + delta
                }
            }),

        finalizePart: ({ partId, finalContent, payload }) =>
            set((state) => {
                const part = state.parts[partId]
                if (!part) return
                part.isStreaming = false
                if (finalContent !== undefined) part.content = finalContent
                if (payload !== undefined) part.payload = payload as Record<string, unknown>
                state.streamingPartIds.delete(partId)
            }),

        loadMessages: async (sessionId) => {
            const data = await apiClient.get(`/sessions/${sessionId}/messages`, {
                params: { include_parts: true, limit: 100 },
            })
            set((state) => {
                state.messages = data.items
            })
        },

        revertToMessage: (messageId) =>
            set((state) => {
                const msgIndex = state.messages.findIndex(
                    (m) => m.messageId === messageId
                )
                if (msgIndex === -1) return
                const toDelete = state.messages.slice(msgIndex + 1)
                toDelete.forEach((msg) => {
                    msg.parts?.forEach((p: { partId: string }) => {
                        delete state.parts[p.partId]
                    })
                })
                state.messages = state.messages.slice(0, msgIndex + 1)
            }),
    }))
)
```

### 3.4 CharacterStore

```typescript
// stores/characterStore.ts
import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'

interface CharacterV4 {
    name: string
    age: number
    attributes: Record<string, number>
    skills: Record<string, number>
    resources: {
        hp: { current: number; max: number }
        willpower: { current: number; max: number }
        sp: number
    }
    inventory: InventoryItem[]
    activeSkills: string[]
    psycheModel: Record<string, number>
}

type TavernCommand =
    | { op: 'set'; path: string; value: unknown }
    | { op: 'increment'; path: string; value: number }
    | { op: 'append'; path: string; value: unknown }
    | { op: 'remove'; path: string; itemId: string }

interface CharacterStore {
    character: CharacterV4 | null
    snapshotHistory: Array<{ messageId: string; snapshot: CharacterV4 }>

    loadCharacter: (sessionId: string) => Promise<void>

    // 响应 state_patch Part（由 PartRenderer 触发）
    applyTavernCommands: (commands: TavernCommand[], messageId: string) => void

    // 回滚到某消息时刻的快照
    restoreSnapshot: (messageId: string) => void
}

export const useCharacterStore = create<CharacterStore>()(
    immer((set, get) => ({
        character: null,
        snapshotHistory: [],

        loadCharacter: async (sessionId) => {
            const data = await apiClient.get(`/sessions/${sessionId}/character`)
            set((state) => {
                state.character = data.data
            })
        },

        applyTavernCommands: (commands, messageId) =>
            set((state) => {
                if (!state.character) return
                // 保存快照
                state.snapshotHistory.push({
                    messageId,
                    snapshot: JSON.parse(JSON.stringify(state.character)),
                })
                // 应用命令（简化实现，生产中用 immer path resolver）
                commands.forEach((cmd) => {
                    applyCommandToCharacter(state.character!, cmd)
                })
            }),

        restoreSnapshot: (messageId) =>
            set((state) => {
                const entry = state.snapshotHistory.find(
                    (h) => h.messageId === messageId
                )
                if (entry) state.character = entry.snapshot
            }),
    }))
)
```

### 3.5 其他 Store 切片

> ⚠️ **实现状态（第二十九轮补录）**：`chapter`、`dice`、`ui`、`world` 四个 store 文件已创建（脚手架完整），
> 但目前**未接入任何组件**（孤儿状态）。  
> - `DicePanel` 使用组件内 `useState` + `api.getDiceHistory`，未消费 `useDiceStore`  
> - `ChapterTree` 使用组件内 `useState` + `fetch`，未消费 `useChapterStore`  
> - `WorldPanel` 使用组件内 `state`，未消费 `useWorldStore`  
> - `uiStore.theme` 有 `setTheme` 但无 UI 调用，`PermissionDialog` 由 `sessionStore.pendingAsks` 控制而非 `uiStore.showPermissionDialog`  
> 接线工作属于已知技术债，待前端完善阶段处理。

```typescript
// stores/diceStore.ts — 骰子历史
interface DiceStore {
    rollHistory: DiceRoll[]
    addRoll: (roll: DiceRoll) => void
    clearHistory: () => void
}

// stores/chapterStore.ts — 章节树
interface ChapterStore {
    chapters: ChapterNode[]
    currentChapterId: string | null
    loadChapters: (sessionId: string) => Promise<void>
    setCurrentChapter: (chapterId: string) => void
    markConsolidated: (chapterId: string) => void
}

// stores/uiStore.ts — UI 状态
interface UIStore {
    isDicePanelOpen: boolean
    isDmToolboxOpen: boolean
    isChapterTreeOpen: boolean
    isCharacterPanelOpen: boolean
    permissionDialog: PermissionAskData | null

    toggleDicePanel: () => void
    showPermissionDialog: (data: PermissionAskData) => void
    closePermissionDialog: () => void
}
```

---

## 4. Part 渲染器（核心）

### 4.1 设计原则

Part 渲染器是前端最核心的组件，负责将后端推送的各类 `MessagePart` 转换为对应的 UI。

设计要点：
- **switch 分派**：按 `part.type` 分派到对应子组件，新增 Part 类型只需新增一个 case
- **`state_patch` 无 UI**：触发 CharacterStore 更新，不渲染任何元素
- **流式正文**：`NarrativePart` 使用 `useRef` + 直接 DOM 操作，避免每个 delta 触发 React re-render
- **懒加载**：`DiceRollPart` 和 `RewardToast` 使用 `React.lazy` 减少首屏 bundle

### 4.2 PartRenderer 组件

```tsx
// components/parts/PartRenderer.tsx
import React, { useEffect } from 'react'
import { useCharacterStore } from '@/stores/characterStore'

const NarrativePart = React.lazy(() => import('./NarrativePart'))
const DiceRollPart = React.lazy(() => import('./DiceRollPart'))
const DMNotePart = React.lazy(() => import('./DMNotePart'))
const NPCBubble = React.lazy(() => import('./NPCBubble'))
const RewardToast = React.lazy(() => import('./RewardToast'))
const ChapterDivider = React.lazy(() => import('./ChapterDivider'))
const PermissionDialog = React.lazy(() => import('./PermissionDialog'))

interface PartRendererProps {
    part: MessagePart
}

export const PartRenderer: React.FC<PartRendererProps> = ({ part }) => {
    const applyTavernCommands = useCharacterStore((s) => s.applyTavernCommands)

    // state_patch：无 UI，仅触发 store 更新
    useEffect(() => {
        if (part.type === 'state_patch' && part.payload) {
            applyTavernCommands(
                part.payload.commands as TavernCommand[],
                part.messageId
            )
        }
    }, [part.partId]) // 仅在 Part 首次挂载时执行

    if (part.type === 'state_patch') return null

    return (
        <React.Suspense fallback={<PartSkeleton type={part.type} />}>
            {part.type === 'narrative' && <NarrativePart part={part} />}
            {part.type === 'dice_roll' && <DiceRollPart part={part} />}
            {part.type === 'dm_note' && <DMNotePart part={part} />}
            {part.type === 'npc_action' && <NPCBubble part={part} />}
            {part.type === 'system_grant' && <RewardToast part={part} />}
            {part.type === 'chapter_end' && <ChapterDivider part={part} />}
            {part.type === 'permission_ask' && <PermissionDialog part={part} />}
        </React.Suspense>
    )
}
```

### 4.3 NarrativePart（流式优化版）

```tsx
// components/parts/NarrativePart.tsx
import React, { useRef, useEffect, memo } from 'react'
import { useStoryStore } from '@/stores/storyStore'

interface NarrativePartProps {
    part: MessagePart & { type: 'narrative' }
}

/**
 * 流式正文渲染：使用 ref 直接操作 DOM，避免每个 delta 触发 React re-render。
 * 只在 part.content 整体变化时（如从 IndexedDB 恢复）才走 React 渲染路径。
 */
export const NarrativePart: React.FC<NarrativePartProps> = memo(({ part }) => {
    const containerRef = useRef<HTMLDivElement>(null)
    const isStreamingRef = useRef(part.isStreaming)

    // 订阅 delta 事件，直接更新 DOM
    useEffect(() => {
        const unsubscribe = useStoryStore.subscribe(
            (state) => state.parts[part.partId],
            (updatedPart) => {
                if (!containerRef.current || !updatedPart) return
                containerRef.current.textContent = updatedPart.content ?? ''
                isStreamingRef.current = updatedPart.isStreaming

                // 流式结束后，让 React 接管（触发语法高亮、分段等后处理）
                if (!updatedPart.isStreaming) {
                    // 此时触发一次 forceUpdate 完成最终渲染
                }
            }
        )
        return unsubscribe
    }, [part.partId])

    // 初始内容（从历史加载或 IndexedDB 恢复时）
    useEffect(() => {
        if (containerRef.current && part.content) {
            containerRef.current.textContent = part.content
        }
    }, []) // 仅挂载时执行一次

    return (
        <div
            ref={containerRef}
            className={[
                'narrative-part',
                'text-foreground leading-relaxed',
                'prose prose-stone dark:prose-invert max-w-none',
                part.isStreaming ? 'after:content-["▋"] after:animate-pulse' : '',
            ].join(' ')}
            data-part-id={part.partId}
        />
    )
})

NarrativePart.displayName = 'NarrativePart'
```

---

## 5. SSE 客户端实现

```typescript
// services/sse-client.ts
import { useStoryStore } from '@/stores/storyStore'
import { useCharacterStore } from '@/stores/characterStore'
import { useSessionStore } from '@/stores/sessionStore'
import { useUiStore } from '@/stores/uiStore'

type BusEvent = {
    id: string
    type: string
    data: Record<string, unknown>
}

class SSEClient {
    private eventSource: EventSource | null = null
    private sessionId: string | null = null
    private lastEventId: string | null = null
    private retryDelay = 1000         // 初始 1 秒
    private readonly maxRetryDelay = 30_000  // 最大 30 秒
    private retryTimer: ReturnType<typeof setTimeout> | null = null
    private isConnected = false

    connect(sessionId: string): void {
        this.sessionId = sessionId
        this.isConnected = true
        this._connect()
    }

    disconnect(): void {
        this.isConnected = false
        this.eventSource?.close()
        this.eventSource = null
        if (this.retryTimer) clearTimeout(this.retryTimer)
    }

    private _connect(): void {
        const url = `/api/sessions/${this.sessionId}/events`
        const fullUrl = this.lastEventId
            ? `${url}?lastEventId=${encodeURIComponent(this.lastEventId)}`
            : url

        this.eventSource = new EventSource(fullUrl)

        this.eventSource.onopen = () => {
            this.retryDelay = 1000  // 重置退避
        }

        this.eventSource.onmessage = (e: MessageEvent) => {
            try {
                const event: BusEvent = JSON.parse(e.data)
                this.lastEventId = event.id
                this.handleEvent(event)
            } catch (err) {
                console.error('[SSEClient] Failed to parse event:', err)
            }
        }

        this.eventSource.onerror = () => {
            this.eventSource?.close()
            this.scheduleReconnect()
        }
    }

    private handleEvent(event: BusEvent): void {
        const storyStore = useStoryStore.getState()
        const uiStore = useUiStore.getState()
        const sessionStore = useSessionStore.getState()

        switch (event.type) {
            case 'part.created':
                storyStore.createPart(event.data as Parameters<typeof storyStore.createPart>[0])
                break

            case 'part.updated':
                storyStore.appendPartDelta(event.data as Parameters<typeof storyStore.appendPartDelta>[0])
                break

            case 'part.done':
                storyStore.finalizePart(event.data as Parameters<typeof storyStore.finalizePart>[0])
                // 若是 dice_roll Part，同步更新 diceStore
                if ((event.data as { type?: string }).type === 'dice_roll') {
                    useDiceStore.getState().addRoll(
                        (event.data as { payload: DiceRoll }).payload
                    )
                }
                break

            case 'permission.ask':
                uiStore.showPermissionDialog(event.data as PermissionAskData)
                break

            case 'session.mode_changed':
                sessionStore.setMode(
                    (event.data as { current_mode: 'play' | 'plan' | 'review' }).current_mode
                )
                break

            case 'session.idle':
                sessionStore.setSessionStatus(this.sessionId!, 'idle')
                break

            case 'session.error':
                sessionStore.setSessionStatus(this.sessionId!, 'error')
                console.error('[SSEClient] Agent error:', event.data)
                break

            default:
                console.debug('[SSEClient] Unhandled event type:', event.type)
        }
    }

    private scheduleReconnect(): void {
        if (!this.isConnected) return
        this.retryTimer = setTimeout(() => {
            this._connect()
            // 指数退避，最大 30 秒
            this.retryDelay = Math.min(this.retryDelay * 2, this.maxRetryDelay)
        }, this.retryDelay)
    }
}

// 单例模式，全局共享
export const sseClient = new SSEClient()
```

### 5.1 在 React 中使用

```tsx
// hooks/useSSE.ts
import { useEffect } from 'react'
import { sseClient } from '@/services/sse-client'

export const useSSE = (sessionId: string | null): void => {
    useEffect(() => {
        if (!sessionId) return
        sseClient.connect(sessionId)
        return () => sseClient.disconnect()
    }, [sessionId])
}

// 在 SessionPage 中调用：
// useSSE(sessionId)
```

---

## 6. 流式正文渲染（差分优化）

### 6.1 问题描述

原生 React state 每次 `setState` 都会触发 re-render。
在 SSE 流式场景下，每秒可能有 10-20 个 delta 事件，
如果每个 delta 都触发 `setState` → re-render → DOM diff，
会导致明显的性能开销，在低端设备上可见卡顿。

### 6.2 解决方案：useRef + 直接 DOM 写入

来自 opencode TUI 差分渲染的思路：

```tsx
// 核心思路：
// 1. 流式阶段：直接操作 DOM textContent，绕过 React reconciler
// 2. 流式结束：触发一次 setState，让 React 完成最终渲染（语法高亮、分段等）

const NarrativePart: React.FC<{ part: MessagePart }> = ({ part }) => {
    const containerRef = useRef<HTMLDivElement>(null)
    const [isFinalized, setIsFinalized] = useState(!part.isStreaming)
    const [finalContent, setFinalContent] = useState(part.content ?? '')

    // 订阅 Zustand store 的细粒度更新（避免整个组件重渲染）
    useEffect(() => {
        return useStoryStore.subscribe(
            // selector：只订阅该 Part 的变化
            (state) => state.parts[part.partId],
            (updatedPart, previousPart) => {
                if (!containerRef.current || !updatedPart) return

                // 差分更新：只写入新增的 delta 部分
                if (
                    updatedPart.isStreaming &&
                    updatedPart.content &&
                    previousPart?.content
                ) {
                    const delta = updatedPart.content.slice(
                        previousPart.content.length
                    )
                    // 直接 DOM 操作，不触发 React re-render
                    containerRef.current.textContent += delta
                }

                // 流式结束：触发一次 React 渲染
                if (!updatedPart.isStreaming && previousPart?.isStreaming) {
                    setFinalContent(updatedPart.content ?? '')
                    setIsFinalized(true)
                }
            }
        )
    }, [part.partId])

    if (isFinalized) {
        // 流式结束后的最终渲染（可加语法高亮、Markdown 解析等）
        return (
            <div
                className="narrative-part prose dark:prose-invert max-w-none"
                dangerouslySetInnerHTML={{ __html: processNarrative(finalContent) }}
            />
        )
    }

    // 流式阶段：纯 ref 容器
    return (
        <div
            ref={containerRef}
            className="narrative-part leading-relaxed after:content-['▋'] after:animate-pulse"
            aria-live="polite"
            aria-label="正在生成叙事文本"
        />
    )
}
```

---

## 7. 骰子面板可视化

### 7.1 DiceRollPart 组件

```tsx
// components/parts/DiceRollPart.tsx
interface DicePayload {
    attribute: string
    skill: string
    modifier: number
    pool: number
    difficulty: number
    successes: number
    outcome: 'botch' | 'failure' | 'success' | 'major_success'
    detail: number[]      // 每颗骰子的点数
    rerollDetail: number[] // 重骰（10点触发）追加的点数
}

const OUTCOME_CONFIG = {
    botch:         { label: 'Botch',  color: 'text-red-600',    bg: 'bg-red-100' },
    failure:       { label: '失败',   color: 'text-orange-600', bg: 'bg-orange-100' },
    success:       { label: '成功',   color: 'text-green-600',  bg: 'bg-green-100' },
    major_success: { label: '大成功', color: 'text-yellow-500', bg: 'bg-yellow-100' },
} as const

export const DiceRollPart: React.FC<{ part: MessagePart }> = ({ part }) => {
    const payload = part.payload as DicePayload
    const config = OUTCOME_CONFIG[payload.outcome]

    return (
        <div className="dice-roll-card border rounded-lg p-3 my-2 bg-card">
            {/* 来源标签 */}
            <div className="text-xs text-muted-foreground mb-2">
                {payload.attribute} + {payload.skill}
                {payload.modifier !== 0 && (
                    <span className={payload.modifier > 0 ? 'text-green-500' : 'text-red-500'}>
                        {' '}({payload.modifier > 0 ? '+' : ''}{payload.modifier})
                    </span>
                )}
                {' · '}骰池 {payload.pool} · 难度 {payload.difficulty}
            </div>

            {/* 骰子图标行 */}
            <div className="flex flex-wrap gap-1 mb-2">
                {payload.detail.map((value, i) => (
                    <DiceIcon
                        key={i}
                        value={value}
                        difficulty={payload.difficulty}
                        isReroll={false}
                    />
                ))}
                {payload.rerollDetail.map((value, i) => (
                    <DiceIcon
                        key={`r${i}`}
                        value={value}
                        difficulty={payload.difficulty}
                        isReroll={true}
                    />
                ))}
            </div>

            {/* 结果摘要 */}
            <div className="flex items-center gap-2">
                <span className="text-sm font-medium">
                    {payload.successes} 个成功
                </span>
                <span className={`text-sm font-bold px-2 py-0.5 rounded ${config.color} ${config.bg}`}>
                    {config.label}
                </span>
            </div>
        </div>
    )
}

const DiceIcon: React.FC<{
    value: number
    difficulty: number
    isReroll: boolean
}> = ({ value, difficulty, isReroll }) => {
    const isSuccess = value >= difficulty
    const isTen = value === 10
    const isOne = value === 1  // Botch 触发条件

    return (
        <div
            className={[
                'w-8 h-8 rounded flex items-center justify-center text-sm font-bold border',
                isSuccess ? 'bg-green-500 text-white border-green-600' : 'bg-muted text-muted-foreground border-border',
                isOne ? 'border-red-500' : '',
                isTen ? 'ring-2 ring-yellow-400' : '',
                isReroll ? 'opacity-70 border-dashed' : '',
            ].join(' ')}
            title={isTen ? '10点：触发重骰' : isOne ? '1点：可能Botch' : ''}
        >
            {value}
        </div>
    )
}
```

---

## 8. 章节树组件

```tsx
// components/chapter/ChapterTree.tsx
interface ChapterNode {
    chapterId: string
    parentId: string | null
    title: string
    branchLabel: string | null
    isConsolidated: boolean
    messageRange: { from: string; to: string }
    children: ChapterNode[]
}

const ChapterTreeNode: React.FC<{
    node: ChapterNode
    depth: number
    currentChapterId: string | null
    onSelect: (chapterId: string) => void
}> = ({ node, depth, currentChapterId, onSelect }) => {
    const [isExpanded, setIsExpanded] = useState(true)
    const isCurrent = node.chapterId === currentChapterId

    return (
        <div>
            <button
                className={[
                    'w-full text-left px-2 py-1.5 rounded text-sm flex items-center gap-1',
                    'hover:bg-accent transition-colors',
                    isCurrent ? 'bg-accent font-medium' : '',
                ].join(' ')}
                style={{ paddingLeft: `${8 + depth * 16}px` }}
                onClick={() => onSelect(node.chapterId)}
            >
                {/* 折叠/展开箭头 */}
                {node.children.length > 0 && (
                    <ChevronIcon
                        className={`w-3 h-3 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                        onClick={(e) => {
                            e.stopPropagation()
                            setIsExpanded(!isExpanded)
                        }}
                    />
                )}

                {/* 固化状态图标 */}
                {node.isConsolidated
                    ? <CheckCircleIcon className="w-3 h-3 text-green-500 shrink-0" />
                    : <CircleIcon className="w-3 h-3 text-muted-foreground shrink-0" />
                }

                {/* 章节标题 */}
                <span className="truncate">
                    {node.branchLabel ? (
                        <span className="text-muted-foreground mr-1">[分支]</span>
                    ) : null}
                    {node.title}
                </span>
            </button>

            {/* 子节点 */}
            {isExpanded && node.children.map((child) => (
                <ChapterTreeNode
                    key={child.chapterId}
                    node={child}
                    depth={depth + 1}
                    currentChapterId={currentChapterId}
                    onSelect={onSelect}
                />
            ))}
        </div>
    )
}

export const ChapterTree: React.FC<{ sessionId: string }> = ({ sessionId }) => {
    const { chapters, currentChapterId, setCurrentChapter, loadChapters } =
        useChapterStore()

    useEffect(() => {
        loadChapters(sessionId)
    }, [sessionId])

    return (
        <div className="flex flex-col h-full">
            <div className="px-3 py-2 border-b">
                <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    章节
                </h3>
            </div>
            <div className="flex-1 overflow-y-auto py-1">
                {chapters.map((node) => (
                    <ChapterTreeNode
                        key={node.chapterId}
                        node={node}
                        depth={0}
                        currentChapterId={currentChapterId}
                        onSelect={setCurrentChapter}
                    />
                ))}
            </div>
            <div className="p-2 border-t">
                <button className="w-full text-xs text-muted-foreground hover:text-foreground py-1">
                    + 新建分支
                </button>
            </div>
        </div>
    )
}
```

---

## 9. IndexedDB 本地缓存

### 9.1 设计目标

- 保存最近 10 个会话的 Part 数据
- 页面刷新后 200ms 内恢复显示（无白屏等待）
- 后端 SSE 重连后只补偿未缓存的 diff（通过 `lastEventId` 实现）

### 9.2 缓存层实现

```typescript
// services/idb-cache.ts
import { openDB, DBSchema, IDBPDatabase } from 'idb'

interface ZeroArsenalDB extends DBSchema {
    parts: {
        key: string // partId
        value: MessagePart
        indexes: { 'by-session': string; 'by-message': string }
    }
    sessions: {
        key: string
        value: { sessionId: string; lastSyncedEventId: string; cachedAt: number }
    }
}

class IdbCache {
    private db: IDBPDatabase<ZeroArsenalDB> | null = null
    private readonly MAX_SESSIONS = 10

    async init(): Promise<void> {
        this.db = await openDB<ZeroArsenalDB>('zero-arsenal', 1, {
            upgrade(db) {
                const parts = db.createObjectStore('parts', { keyPath: 'partId' })
                parts.createIndex('by-session', 'sessionId')
                parts.createIndex('by-message', 'messageId')
                db.createObjectStore('sessions', { keyPath: 'sessionId' })
            },
        })
    }

    async getPartsForSession(sessionId: string): Promise<MessagePart[]> {
        if (!this.db) return []
        return this.db.getAllFromIndex('parts', 'by-session', sessionId)
    }

    async savePart(part: MessagePart): Promise<void> {
        if (!this.db || part.isStreaming) return  // 不缓存流式中的 Part
        await this.db.put('parts', part)
    }

    async getLastSyncedEventId(sessionId: string): Promise<string | null> {
        if (!this.db) return null
        const entry = await this.db.get('sessions', sessionId)
        return entry?.lastSyncedEventId ?? null
    }

    async updateLastSyncedEventId(sessionId: string, eventId: string): Promise<void> {
        if (!this.db) return
        await this.db.put('sessions', {
            sessionId,
            lastSyncedEventId: eventId,
            cachedAt: Date.now(),
        })
        // 清理超出 MAX_SESSIONS 的旧数据
        await this.evictOldSessions()
    }

    private async evictOldSessions(): Promise<void> {
        if (!this.db) return
        const allSessions = await this.db.getAll('sessions')
        if (allSessions.length <= this.MAX_SESSIONS) return
        // 按 cachedAt 升序排序，删除最旧的
        allSessions.sort((a, b) => a.cachedAt - b.cachedAt)
        const toEvict = allSessions.slice(0, allSessions.length - this.MAX_SESSIONS)
        const tx = this.db.transaction(['parts', 'sessions'], 'readwrite')
        for (const session of toEvict) {
            // 删除该会话的所有 Part
            const parts = await tx
                .objectStore('parts')
                .index('by-session')
                .getAllKeys(session.sessionId)
            for (const key of parts) {
                await tx.objectStore('parts').delete(key)
            }
            await tx.objectStore('sessions').delete(session.sessionId)
        }
        await tx.done
    }
}

export const idbCache = new IdbCache()
```

### 9.3 恢复流程

```tsx
// hooks/useSessionRestore.ts
export const useSessionRestore = (sessionId: string) => {
    const { createPart, finalizePart } = useStoryStore()

    useEffect(() => {
        async function restore() {
            // 1. 从 IndexedDB 加载缓存的 Part
            const cachedParts = await idbCache.getPartsForSession(sessionId)
            cachedParts.forEach((part) => {
                createPart(part)
                finalizePart({ partId: part.partId, finalContent: part.content ?? undefined })
            })

            // 2. 获取最后同步的 EventId（用于 SSE 断线重连补偿）
            const lastEventId = await idbCache.getLastSyncedEventId(sessionId)
            if (lastEventId) {
                sseClient.setLastEventId(lastEventId)
            }

            // 3. 建立 SSE 连接（携带 lastEventId 补偿 diff）
            sseClient.connect(sessionId)
        }

        restore()
    }, [sessionId])
}
```

---

## 10. 提示词模块（前端侧，精简版）

### 10.1 设计原则

参考 MoRanJiangHu 的 `prompts/` 目录，但大幅精简：
- **主要提示词移到后端**：叙事生成、角色对话、战斗描写等复杂提示词由 Python 管理
- **前端只保留必需的**：UI 交互相关的轻量提示词

### 10.2 前端保留的提示词

```typescript
// prompts/index.ts

/**
 * 开场引导提示词
 * 在会话创建后、第一条消息发送前显示给用户
 */
export const OPENING_GUIDE_PROMPT = (worldPlugin: string): string => `
你进入了「${worldPlugin}」世界。
当前模式：跑团模式（play）

你可以：
- 直接描述你的行动（如：「我向北走，观察周围环境」）
- 选择下方的行动选项
- 输入 /plan 切换到策划模式
- 输入 /help 查看所有指令
`

/**
 * 行动选项生成提示词（发给后端，返回 A/B/C/D 选项）
 * 前端将响应渲染为按钮
 */
export const ACTION_OPTIONS_SYSTEM = `
根据当前叙事情境，生成 2-4 个玩家可选的行动选项。
要求：
1. 选项语义清晰，避免歧义
2. 包含至少一个积极选项和一个谨慎/观察选项
3. 每个选项不超过 15 个字
4. 以 JSON 数组格式返回：[{"key": "A", "label": "..."}, ...]
`

/**
 * OOC 指令识别（出戏命令解析）
 */
export const OOC_COMMANDS: Record<string, string> = {
    '/plan':    '切换到策划模式',
    '/play':    '切换到跑团模式',
    '/review':  '切换到审校模式',
    '/save':    '手动固化当前章节',
    '/fork':    '创建当前节点的分支',
    '/revert':  '回滚到上一条消息',
    '/help':    '显示帮助信息',
    '/status':  '显示角色当前状态',
}
```

### 10.3 行动选项渲染

```tsx
// components/PlayerInputBar.tsx
export const PlayerInputBar: React.FC<{ sessionId: string }> = ({ sessionId }) => {
    const [input, setInput] = useState('')
    const [actionOptions, setActionOptions] = useState<ActionOption[]>([])
    const isProcessing = useSessionStore(
        (s) => s.sessions.find((sess) => sess.sessionId === sessionId)?.status === 'processing'
    )

    const handleSend = async () => {
        if (!input.trim() || isProcessing) return
        // 检查 OOC 指令
        if (input.startsWith('/')) {
            handleOocCommand(input)
            setInput('')
            return
        }
        await apiClient.post(`/sessions/${sessionId}/message`, {
            content: input,
            message_type: 'player_action',
        })
        setInput('')
        setActionOptions([])  // 清空行动选项
    }

    return (
        <div className="border-t p-3 space-y-2">
            {/* 行动选项按钮 */}
            {actionOptions.length > 0 && (
                <div className="flex flex-wrap gap-2">
                    {actionOptions.map((opt) => (
                        <button
                            key={opt.key}
                            className="px-3 py-1.5 text-sm border rounded-full hover:bg-accent"
                            onClick={() => setInput(opt.label)}
                        >
                            <span className="font-bold text-muted-foreground mr-1">
                                {opt.key}:
                            </span>
                            {opt.label}
                        </button>
                    ))}
                </div>
            )}

            {/* 输入框 + 发送按钮 */}
            <div className="flex gap-2">
                <textarea
                    className="flex-1 min-h-[40px] max-h-32 resize-none rounded border px-3 py-2 text-sm"
                    placeholder="描述你的行动，或选择上方选项..."
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault()
                            handleSend()
                        }
                    }}
                    disabled={isProcessing}
                />
                <button
                    className="px-4 bg-primary text-primary-foreground rounded disabled:opacity-50"
                    onClick={handleSend}
                    disabled={isProcessing || !input.trim()}
                >
                    {isProcessing ? <SpinnerIcon /> : '发送'}
                </button>
            </div>
        </div>
    )
}
```

---

## 附录：类型定义汇总

```typescript
// types/parts.ts — MessagePart 联合类型

interface BaseMessagePart {
    partId: string
    messageId: string
    sessionId: string
    isStreaming: boolean
    createdAt: string
}

export type MessagePart =
    | (BaseMessagePart & { type: 'narrative'; content: string; payload: null })
    | (BaseMessagePart & { type: 'dice_roll'; content: null; payload: DicePayload })
    | (BaseMessagePart & { type: 'state_patch'; content: null; payload: { commands: TavernCommand[] } })
    | (BaseMessagePart & { type: 'dm_note'; content: string; payload: null })
    | (BaseMessagePart & { type: 'npc_action'; content: string; payload: { npc_name: string; emotion?: string } })
    | (BaseMessagePart & { type: 'system_grant'; content: null; payload: SystemGrantPayload })
    | (BaseMessagePart & { type: 'chapter_end'; content: string; payload: { chapter_id: string } })
    | (BaseMessagePart & { type: 'permission_ask'; content: null; payload: PermissionAskData })
```
