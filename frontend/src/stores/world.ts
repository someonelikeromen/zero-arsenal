/**
 * worldStore — 世界状态（WorldPlugin 数据、NPC 档案、世界档案）
 * 设计文档 12-frontend-architecture.md §3.5
 */
import { create } from 'zustand'
import { devtools } from 'zustand/middleware'

interface NpcProfile {
  id: string
  key: string
  name: string
  profile_json: Record<string, unknown>
}

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
  npcs: NpcProfile[]
  isLoading: boolean
  error: string | null

  // Actions
  setSessionId: (id: string) => void
  setWorldPlugin: (plugin: string) => void
  loadArchives: (sessionId: string) => Promise<void>
  addArchive: (archive: WorldArchive) => void
  loadNpcs: (sessionId: string) => Promise<void>
  reset: () => void
}

export const useWorldStore = create<WorldState>()(
  devtools(
    (set, get) => ({
      sessionId: null,
      worldPlugin: 'crossover',
      archives: [],
      npcs: [],
      isLoading: false,
      error: null,

      setSessionId: (id) => set({ sessionId: id }),
      setWorldPlugin: (plugin) => set({ worldPlugin: plugin }),

      loadArchives: async (sessionId) => {
        set({ isLoading: true, error: null })
        try {
          const res = await fetch(`/api/sessions/${sessionId}/world-archives`)
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          const data = await res.json() as { archives?: WorldArchive[] } | WorldArchive[]
          const archives = Array.isArray(data)
            ? data
            : (data as { archives?: WorldArchive[] }).archives ?? []
          set({ archives, isLoading: false })
        } catch (e) {
          set({ error: String(e), isLoading: false })
        }
      },

      addArchive: (archive) =>
        set((s) => ({ archives: [archive, ...s.archives] })),

      loadNpcs: async (_sessionId) => {
        const { archives } = get()
        const npcArchives = archives.filter((a) => a.archive_type === 'npc')
        set({
          npcs: npcArchives.map((a) => ({
            id: a.id,
            key: a.id,
            name: a.title,
            profile_json: { content: a.content },
          })),
        })
      },

      reset: () =>
        set({
          sessionId: null,
          archives: [],
          npcs: [],
          isLoading: false,
          error: null,
        }),
    }),
    { name: 'worldStore' }
  )
)
