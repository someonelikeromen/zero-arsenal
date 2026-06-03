/**
 * Zustand Session Store — 会话状态管理
 */
import { create } from 'zustand'
import { api, Session } from '../lib/api'
import { SSEClient, BusEvent } from '../lib/sse'

export interface PendingAsk {
  ask_id: string
  tool_name: string
  tool_args: unknown
  reason: string
}

interface SessionStore {
  sessions: Session[]
  currentSessionId: string | null
  mode: 'play' | 'plan' | 'review'
  sseClient: SSEClient | null
  pendingAsks: PendingAsk[]

  loadSessions: () => Promise<void>
  createSession: (worldPlugin?: string, title?: string) => Promise<string>
  selectSession: (id: string) => void
  setMode: (mode: 'play' | 'plan' | 'review') => Promise<void>
  connectSSE: (sessionId: string, onEvent: (e: BusEvent) => void) => void
  disconnectSSE: () => void
  addPendingAsk: (ask: PendingAsk) => void
  removePendingAsk: (ask_id: string) => void
}

export const useSessionStore = create<SessionStore>((set, get) => ({
  sessions: [],
  currentSessionId: null,
  mode: 'play',
  sseClient: null,
  pendingAsks: [],

  loadSessions: async () => {
    const res = await api.listSessions()
    set({ sessions: res.items ?? [] })
  },

  createSession: async (worldPlugin = 'crossover', title?) => {
    const res = await api.createSession({ world_plugin: worldPlugin, title })
    await get().loadSessions()
    return res.session_id
  },

  selectSession: (id) => {
    // 切换会话时清空旧会话的挂起询问
    set({ currentSessionId: id, pendingAsks: [] })
  },

  setMode: async (mode) => {
    const { currentSessionId } = get()
    if (!currentSessionId) return
    await api.setMode(currentSessionId, mode)
    set({ mode })
  },

  connectSSE: (sessionId, onEvent) => {
    get().disconnectSSE()
    const client = new SSEClient(sessionId)
    client.onAny(onEvent)
    client.connect()
    set({ sseClient: client })
  },

  disconnectSSE: () => {
    get().sseClient?.disconnect()
    // 断线时清空 pendingAsks（避免残留旧会话的询问弹窗）
    set({ sseClient: null, pendingAsks: [] })
  },

  addPendingAsk: (ask) =>
    set((s) => {
      // ask_id 去重：同一个 ask 不重复添加
      if (s.pendingAsks.some((a) => a.ask_id === ask.ask_id)) return s
      return { pendingAsks: [...s.pendingAsks, ask] }
    }),

  removePendingAsk: (ask_id) =>
    set((s) => ({ pendingAsks: s.pendingAsks.filter((a) => a.ask_id !== ask_id) })),
}))
