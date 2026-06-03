/**
 * Zustand Story Store — 故事流/Part 渲染状态
 * 新增：IndexedDB 缓存、messages 列表、loadMessages、revertToMessage
 * 使用 immer middleware 实现不可变更新（12-frontend-architecture.md §3）
 * 设计文档 12-frontend-architecture.md §3.3
 */
import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { immer } from 'zustand/middleware/immer'
import { cache } from '../lib/idb'

export type PartType =
  | 'narrative'
  | 'dm_note'
  | 'dice_roll'
  | 'state_patch'
  | 'system_grant'
  | 'npc_action'
  | 'world_event'
  | 'chapter_end'
  | 'permission_ask'
  | 'compaction'
  | 'skill_load'
  | 'action_options'
  | 'reasoning'       // Agent 推理过程（review 模式可见）
  | 'text'            // 纯文本（TextPart，设计文档要求）
  | 'tool_call'       // 工具调用（来自 opencode Part 模型）
  | 'tool_result'     // 工具调用结果
  | 'var_diff'        // 变量差异展示（StatePatchPart 的结构化超集）

export interface MessagePart {
  id: string
  message_id: string
  type: PartType
  content: Record<string, unknown>
  status: 'streaming' | 'done' | 'error'
  agent: string
  // 流式文本 buffer（仅 narrative 使用）
  streamBuffer?: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  turn_index: number
  status: 'active' | 'reverted'
  created_at: number
  parts: MessagePart[]
}

interface StoryStore {
  parts: MessagePart[]
  messages: Message[]
  streamingPartId: string | null
  sessionId: string | null
  isLoading: boolean

  setSessionId: (id: string) => void
  loadFromCache: (sessionId: string) => Promise<void>
  loadMessages: (sessionId: string) => Promise<void>
  loadParts: (sessionId: string) => Promise<void>
  addPart: (part: MessagePart) => void
  appendDelta: (partId: string, delta: string) => void
  finalizePart: (partId: string, finalContent?: Record<string, unknown>) => void
  /** StyleAgent 润色替换：更新已 done 的 part content（不改变 status） */
  updatePartContent: (partId: string, content: Record<string, unknown>) => void
  revertToMessage: (sessionId: string, messageId: string) => Promise<void>
  clearSession: () => void
}

export const useStoryStore = create<StoryStore>()(
  devtools(
    immer((set, get) => ({
      parts: [],
      messages: [],
      streamingPartId: null,
      sessionId: null,
      isLoading: false,

      setSessionId: (id) =>
        set((state) => {
          state.sessionId = id
        }),

      loadFromCache: async (sessionId) => {
        try {
          const cached = await cache.getPartsBySession(sessionId)
          if (cached.length > 0) {
            set((state) => {
              state.parts = cached as MessagePart[]
              state.sessionId = sessionId
            })
          }
        } catch {
          // IndexedDB 不可用时静默跳过
        }
      },

      loadMessages: async (sessionId) => {
        set((state) => { state.isLoading = true })
        try {
          // 使用新的 cursor 分页 API（11-api-design.md §messages）
          const res = await fetch(`/api/sessions/${sessionId}/messages?limit=100&include_parts=false`)
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          const data = await res.json()
          set((state) => {
            state.messages = data.items ?? data.messages ?? data ?? []
            state.isLoading = false
          })
        } catch {
          set((state) => { state.isLoading = false })
        }
      },

      loadParts: async (sessionId) => {
        set((state) => { state.isLoading = true })
        try {
          // 使用新的 cursor 分页 API（11-api-design.md §parts）
          const res = await fetch(`/api/sessions/${sessionId}/parts?limit=200`)
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          const data = await res.json()
          const parts = (data.items ?? data.parts ?? data ?? []) as MessagePart[]
          set((state) => {
            state.parts = parts
            state.isLoading = false
          })
          // 写回 IndexedDB
          for (const p of parts) {
            cache.putPart(p.id, sessionId, p).catch(() => {})
          }
        } catch {
          set((state) => { state.isLoading = false })
        }
      },

      addPart: (part) => {
        set((state) => {
          state.parts.push(part)
          if (part.status === 'streaming') {
            state.streamingPartId = part.id
          }
        })
        const sid = get().sessionId
        if (sid) {
          cache.putPart(part.id, sid, part).catch(() => {})
        }
      },

      appendDelta: (partId, delta) =>
        set((state) => {
          const p = state.parts.find((p) => p.id === partId)
          if (p) {
            p.streamBuffer = (p.streamBuffer ?? '') + delta
          }
        }),

      finalizePart: (partId, finalContent) => {
        set((state) => {
          const p = state.parts.find((p) => p.id === partId)
          if (p) {
            p.status = 'done'
            if (finalContent) p.content = finalContent
            delete p.streamBuffer
            if (state.streamingPartId === partId) {
              state.streamingPartId = null
            }
          } else {
            // Upsert 路径：part.done 先于 part.created 到达（乱序）
            state.parts.push({
              id: partId,
              message_id: '',
              type: 'dm_note',
              content: finalContent ?? {},
              status: 'done',
              agent: '',
            })
          }
        })
        const sid = get().sessionId
        if (sid) {
          const updated = get().parts.find((p) => p.id === partId)
          if (updated) cache.putPart(partId, sid, updated).catch(() => {})
        }
      },

      updatePartContent: (partId, content) => {
        set((state) => {
          const p = state.parts.find((p) => p.id === partId)
          if (p) {
            p.content = content
          }
        })
      },

      revertToMessage: async (sessionId, messageId) => {
        try {
          const res = await fetch(`/api/sessions/${sessionId}/revert`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message_id: messageId }),
          })
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          await get().loadParts(sessionId)
        } catch (e) {
          console.error('[StoryStore] revertToMessage failed:', e)
        }
      },

      clearSession: () =>
        set((state) => {
          state.parts = []
          state.messages = []
          state.streamingPartId = null
          state.sessionId = null
        }),
    })),
    { name: 'storyStore' }
  )
)
