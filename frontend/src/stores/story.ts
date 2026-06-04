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
import { api, apiFetch } from '../lib/api'

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
  /**
   * 流式增量缓冲区（conf_b12 细粒度订阅）：按 partId 隔离存放流式文本。
   * 关键点——流式 delta 只更新本 map，**不**触碰 `parts` 数组引用，
   * 因此订阅 `parts` 的列表（含虚拟滚动）不会随每个 delta 重渲染；
   * 仅订阅 `streamBuffers[partId]` 的 NarrativePart 自身更新（直写 DOM）。
   */
  streamBuffers: Record<string, string>
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
      streamBuffers: {},
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
          // 统一走 apiFetch（NEW-C13-03），保留 cursor 分页参数
          const data = await apiFetch<{ items?: Message[]; messages?: Message[] }>(
            `/sessions/${sessionId}/messages?limit=100&include_parts=false`
          )
          set((state) => {
            state.messages = data.items ?? data.messages ?? []
            state.isLoading = false
          })
        } catch {
          set((state) => { state.isLoading = false })
        }
      },

      loadParts: async (sessionId) => {
        set((state) => { state.isLoading = true })
        try {
          // 统一走 apiFetch（NEW-C13-03），保留 cursor 分页参数
          const data = await apiFetch<{ items?: MessagePart[]; parts?: MessagePart[] }>(
            `/sessions/${sessionId}/parts?limit=200`
          )
          const parts = (data.items ?? data.parts ?? []) as MessagePart[]
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
          // streamBuffer 不入 parts（避免后续 delta 改动 parts 引用）；改用 streamBuffers map
          const { streamBuffer: _sb, ...rest } = part
          state.parts.push(rest as MessagePart)
          if (part.status === 'streaming') {
            state.streamingPartId = part.id
            state.streamBuffers[part.id] = _sb ?? ''
          }
        })
        const sid = get().sessionId
        if (sid) {
          cache.putPart(part.id, sid, part).catch(() => {})
        }
      },

      appendDelta: (partId, delta) =>
        // 仅更新 streamBuffers[partId]——parts 数组引用保持不变，列表不重渲染
        set((state) => {
          state.streamBuffers[partId] = (state.streamBuffers[partId] ?? '') + delta
        }),

      finalizePart: (partId, finalContent) => {
        set((state) => {
          const p = state.parts.find((p) => p.id === partId)
          if (p) {
            p.status = 'done'
            // 服务端 finalContent 缺正文时，用累计的流式缓冲兜底
            if (finalContent && (finalContent.text || Object.keys(finalContent).length > 0)) {
              p.content = finalContent
            } else if (state.streamBuffers[partId]) {
              p.content = { ...p.content, text: state.streamBuffers[partId] }
            }
            delete state.streamBuffers[partId]
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
          // 统一走 apiFetch（NEW-C13-03）
          await api.revertToMessage(sessionId, messageId)
          await get().loadParts(sessionId)
        } catch (e) {
          console.error('[StoryStore] revertToMessage failed:', e)
        }
      },

      clearSession: () =>
        set((state) => {
          state.streamBuffers = {}
          state.parts = []
          state.messages = []
          state.streamingPartId = null
          state.sessionId = null
        }),
    })),
    { name: 'storyStore' }
  )
)
