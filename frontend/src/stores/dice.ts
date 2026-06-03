/**
 * Zustand Dice Store — 骰子历史与当前回合骰子状态
 * 使用 immer middleware 实现不可变更新（12-frontend-architecture.md §3）
 */
import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'
import { api } from '../lib/api'

export interface DiceRoll {
  roll_id: string
  pool: number
  successes: number
  outcome: 'success' | 'failure' | 'critical'
  attribute: string
  skill?: string
  modifier?: number
  detail: number[]
  created_at: number
  message_id?: string
}

interface DiceStore {
  /** 当前会话的骰子历史（最近 50 条） */
  history: DiceRoll[]
  /** 本轮骰子结果（显示在骰子面板） */
  currentRoll: DiceRoll | null
  /** 骰子面板展开状态 */
  panelOpen: boolean

  addRoll: (roll: DiceRoll) => void
  setCurrentRoll: (roll: DiceRoll | null) => void
  clearHistory: () => void
  togglePanel: () => void
  /** 从后端 API 加载历史，持久化覆盖本地状态 */
  loadHistory: (sessionId: string) => Promise<void>
}

export const useDiceStore = create<DiceStore>()(
  immer((set) => ({
    history: [],
    currentRoll: null,
    panelOpen: false,

    addRoll: (roll) =>
      set((state) => {
        state.history.unshift(roll)
        if (state.history.length > 50) {
          state.history.splice(50)
        }
        state.currentRoll = roll
      }),

    setCurrentRoll: (roll) =>
      set((state) => {
        state.currentRoll = roll
      }),

    clearHistory: () =>
      set((state) => {
        state.history = []
        state.currentRoll = null
      }),

    togglePanel: () =>
      set((state) => {
        state.panelOpen = !state.panelOpen
      }),

    loadHistory: async (sessionId) => {
      try {
        const data = await api.getDiceHistory(sessionId, 50)
        // 后端返回 { history: [...] }，字段名与前端 DiceRoll 不同，需映射
        const raw = (data as { history?: Record<string, unknown>[] }).history ?? []
        const rolls: DiceRoll[] = raw.map((r) => {
          const verdict = String(r.verdict ?? 'failure')
          const outcome: DiceRoll['outcome'] =
            verdict.includes('critical') ? 'critical'
            : verdict.includes('success') ? 'success'
            : 'failure'
          return {
            roll_id: String(r.id ?? ''),
            pool: Number(r.pool ?? 0),
            successes: Number(r.net ?? 0),
            outcome,
            attribute: String(r.attribute ?? ''),
            skill: (r.skill as string | undefined) || undefined,
            modifier: r.threshold != null ? Number(r.threshold) : undefined,
            detail: Array.isArray(r.rolls) ? (r.rolls as number[]) : [],
            created_at: Number(r.created_at ?? Date.now()),
            message_id: undefined,
          }
        })
        set((state) => {
          state.history = rolls
          if (rolls.length > 0 && !state.currentRoll) {
            state.currentRoll = rolls[0]
          }
        })
      } catch {
        // 加载失败时保留本地历史，不报错
      }
    },
  }))
)
