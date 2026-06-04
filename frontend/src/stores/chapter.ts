/**
 * Zustand Chapter Store — 章节树状态管理
 * 使用 immer middleware（12-frontend-architecture.md §3）
 */
import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { api } from '../lib/api'

export interface ChapterNode {
  id: string
  title: string
  chapter_index: number
  status: 'draft' | 'active' | 'consolidated'
  is_consolidated: boolean
  parent_chapter_id: string | null
  branch_label: string | null
  end_message_id: string | null
  created_at: number
  summary?: string
}

interface ChapterStore {
  chapters: ChapterNode[]
  activeChapterId: string | null
  loading: boolean

  loadChapters: (sessionId: string) => Promise<void>
  setActiveChapter: (id: string | null) => void
  updateChapter: (id: string, patch: Partial<ChapterNode>) => void
  addChapter: (chapter: ChapterNode) => void
  markConsolidated: (id: string, summary?: string) => void
}

/** 递归展平嵌套树（后端返回 {chapter_id, children: [...]} 结构） */
function flattenTree(nodes: Record<string, unknown>[], depth = 0): ChapterNode[] {
  const result: ChapterNode[] = []
  for (const n of nodes) {
    result.push({
      id: (n.chapter_id ?? n.id) as string,
      title: (n.title ?? '') as string,
      chapter_index: (n.chapter_index ?? depth) as number,
      status: (n.status ?? (n.is_consolidated ? 'consolidated' : 'active')) as ChapterNode['status'],
      is_consolidated: Boolean(n.is_consolidated),
      parent_chapter_id: (n.parent_chapter_id ?? null) as string | null,
      branch_label: (n.branch_label ?? null) as string | null,
      end_message_id: (n.end_message_id ?? null) as string | null,
      created_at: (n.created_at ?? 0) as number,
      summary: n.summary as string | undefined,
    })
    const children = n.children as Record<string, unknown>[] | undefined
    if (children?.length) {
      result.push(...flattenTree(children, depth + 1))
    }
  }
  return result
}

export const useChapterStore = create<ChapterStore>()(
  immer((set) => ({
    chapters: [],
    activeChapterId: null,
    loading: false,

    loadChapters: async (sessionId) => {
      set((state) => { state.loading = true })
      try {
        // 统一走 apiFetch（NEW-C13-03/04：消除裸 fetch + 复活 api.getChapters）
        const data = await api.getChapters(sessionId) as { chapters?: Record<string, unknown>[] }
        const raw: Record<string, unknown>[] = data.chapters ?? []
        const flat = flattenTree(raw)
        set((state) => {
          state.chapters = flat
          const active = flat.find((c) => !c.is_consolidated)
          state.activeChapterId = active?.id ?? null
          state.loading = false
        })
      } catch {
        set((state) => { state.loading = false })
      }
    },

    setActiveChapter: (id) =>
      set((state) => {
        state.activeChapterId = id
      }),

    updateChapter: (id, patch) =>
      set((state) => {
        const idx = state.chapters.findIndex((c) => c.id === id)
        if (idx !== -1) {
          Object.assign(state.chapters[idx], patch)
        }
      }),

    addChapter: (chapter) =>
      set((state) => {
        const exists = state.chapters.some((c) => c.id === chapter.id)
        if (!exists) {
          state.chapters.push(chapter)
        }
      }),

    markConsolidated: (id, summary) =>
      set((state) => {
        const idx = state.chapters.findIndex((c) => c.id === id)
        if (idx !== -1) {
          state.chapters[idx].is_consolidated = true
          state.chapters[idx].status = 'consolidated'
          if (summary) state.chapters[idx].summary = summary
        }
      }),
  }))
)
