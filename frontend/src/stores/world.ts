/**
 * worldStore — 世界状态（WorldPlugin 数据、NPC 档案、世界档案）
 * 设计文档 12-frontend-architecture.md §3.5
 */
import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { api } from '../lib/api'

interface WorldArchive {
  id: string
  title: string
  content: string
  archive_type: 'lore' | 'npc' | 'rule' | 'setting' | 'opening_scene'
  trigger_keywords?: string
  created_at: number
}

interface WorldState {
  sessionId: string | null
  worldPlugin: string
  archives: WorldArchive[]
  isLoading: boolean
  error: string | null

  // Actions
  setSessionId: (id: string) => void
  setWorldPlugin: (plugin: string) => void
  loadArchives: (sessionId: string) => Promise<void>
  reset: () => void
}

// 注：NPC 列表已由 WorldPanel 本地 state（api.listSessionNpcs）管理，
// 故移除 store 层无消费者的 npcs / loadNpcs / addArchive（T-D18 / NEW-C13-02）。

export const useWorldStore = create<WorldState>()(
  devtools(
    (set) => ({
      sessionId: null,
      worldPlugin: 'crossover',
      archives: [],
      isLoading: false,
      error: null,

      setSessionId: (id) => set({ sessionId: id }),
      setWorldPlugin: (plugin) => set({ worldPlugin: plugin }),

      loadArchives: async (sessionId) => {
        set({ isLoading: true, error: null })
        try {
          // 统一走 apiFetch（NEW-C13-03）
          const data = await api.getWorldArchives(sessionId)
          const archives = (Array.isArray(data)
            ? data
            : data.archives ?? []) as unknown as WorldArchive[]
          set({ archives, isLoading: false })
        } catch (e) {
          set({ error: String(e), isLoading: false })
        }
      },

      reset: () =>
        set({
          sessionId: null,
          archives: [],
          isLoading: false,
          error: null,
        }),
    }),
    { name: 'worldStore' }
  )
)
