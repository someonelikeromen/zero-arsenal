import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import { api } from '../lib/api'

interface InventoryItem {
  id: string
  key: string
  name: string
  count: number
  quality?: string
  description?: string
  metadata?: Record<string, unknown>
}

/**
 * 归一化角色卡 inventory 条目。
 * 后端各扩展写入的字段不统一（name/type/quantity/description/durability...），
 * 这里映射为前端 InventoryItem 结构，并补齐缺失的 id/key/count。
 */
function normalizeInventory(raw: unknown): InventoryItem[] {
  if (!Array.isArray(raw)) return []
  return raw.map((it, idx) => {
    const item = (it ?? {}) as Record<string, unknown>
    const name = String(item.name ?? item.key ?? `物品${idx + 1}`)
    const key = String(item.key ?? item.id ?? name)
    return {
      id: String(item.id ?? key ?? idx),
      key,
      name,
      count: Number(item.count ?? item.quantity ?? 1),
      quality: (item.quality as string | undefined) ?? (item.rarity as string | undefined),
      description: (item.description as string | undefined) ?? (item.desc as string | undefined),
      metadata: item,
    }
  })
}

interface Attribute {
  base: number
  [key: string]: unknown
}

interface Character {
  attributes?: Record<string, Attribute>
  meta?: Record<string, unknown>
  [key: string]: unknown
}

/** 快照条目（用于 state_patch 回滚）。 */
interface CharacterSnapshot {
  /** 快照时间戳（Date.now()） */
  ts: number
  /** 快照时的 character 深克隆 */
  character: Character
}

/** 快照队列最大长度（保留最近 N 次 state_patch 前的状态）。 */
const SNAPSHOT_LIMIT = 20

interface CharacterStore {
  character: Character | null
  schemaVersion: string
  loading: boolean
  inventory: InventoryItem[]
  activeSkills: string[]
  /** 历史快照队列（最新在末尾），配合 state_patch Part 使用。 */
  snapshotHistory: CharacterSnapshot[]

  loadCharacter: (sessionId: string) => Promise<void>
  updateLocal: (data: Character) => void
  applyPatch: (patches: Array<{ cmd: string; key: string; value: string; delta: number | null }>) => void
  setPsyche: (psycheData: Record<string, unknown>) => void
  /**
   * 手动推入一个快照（一般在 applyPatch 前由外部调用，
   * 或通过 applyPatch 第二个参数 `snapshot=true` 自动触发）。
   */
  pushSnapshot: () => void
  /**
   * 回滚到上一个快照（弹出末尾快照并恢复）。
   * 若历史为空则无操作，返回 false。
   */
  restoreSnapshot: () => boolean
  /** 清空快照历史（切换 session 时调用）。 */
  clearSnapshots: () => void
}

export const useCharacterStore = create<CharacterStore>()(
  devtools(
    (set, get) => ({
      character: null,
      schemaVersion: '4.0',
      loading: false,
      inventory: [],
      activeSkills: [],
      snapshotHistory: [],

      loadCharacter: async (sessionId) => {
        set({ loading: true })
        try {
          const res = await api.getCharacter(sessionId) as { character: Character; schema_version: string }
          const char = res.character
          // 同步 inventory 和 activeSkills 从 character 数据（归一化字段）
          const inventory = normalizeInventory(char?.inventory)
          const skills = char?.skills as Record<string, unknown> | undefined
          const activeSkills = skills ? Object.keys(skills) : []
          set({ character: char, schemaVersion: res.schema_version, inventory, activeSkills })
        } catch {
          // no character yet
        } finally {
          set({ loading: false })
        }
      },

      updateLocal: (data) => set({ character: data }),

      applyPatch: (patches) =>
        set((s) => {
          if (!s.character) return s
          // 应用前自动推入快照，供回滚使用
          const snapshot: CharacterSnapshot = {
            ts: Date.now(),
            character: JSON.parse(JSON.stringify(s.character)),
          }
          const snapshotHistory = [...s.snapshotHistory, snapshot].slice(-SNAPSHOT_LIMIT)

          // 深克隆避免 immer-like 问题
          const updated: Character = JSON.parse(JSON.stringify(s.character))

          const getNestedParent = (obj: Record<string, unknown>, parts: string[]) => {
            let cur: Record<string, unknown> = obj
            for (let i = 0; i < parts.length - 1; i++) {
              if (cur[parts[i]] === undefined) cur[parts[i]] = {}
              cur = cur[parts[i]] as Record<string, unknown>
            }
            return cur
          }

          for (const p of patches) {
            const parts = p.key.split('.')
            const leaf = parts[parts.length - 1]
            const parent = getNestedParent(updated as unknown as Record<string, unknown>, parts)

            if (p.cmd === 'SET') {
              // 若叶节点是 {base,current} 结构，则更新 base/current
              if (parent[leaf] && typeof parent[leaf] === 'object' && 'base' in (parent[leaf] as object)) {
                const prev = parent[leaf] as Record<string, unknown>
                parent[leaf] = { ...prev, base: Number(p.value), current: Number(p.value) }
              } else {
                parent[leaf] = p.value
              }
            } else if (p.cmd === 'ADD' && p.delta !== null) {
              if (parent[leaf] && typeof parent[leaf] === 'object' && 'base' in (parent[leaf] as object)) {
                const prev = parent[leaf] as Record<string, number>
                const newBase = (prev.base ?? 0) + p.delta
                parent[leaf] = { ...prev, base: newBase, current: newBase }
              } else {
                const cur = typeof parent[leaf] === 'number' ? (parent[leaf] as number) : 0
                parent[leaf] = cur + p.delta
              }
            } else if (p.cmd === 'PUSH') {
              const lst = Array.isArray(parent[leaf]) ? [...(parent[leaf] as unknown[])] : []
              lst.push(p.value)
              parent[leaf] = lst
            } else if (p.cmd === 'POP') {
              const lst = Array.isArray(parent[leaf]) ? [...(parent[leaf] as unknown[])] : []
              lst.pop()
              parent[leaf] = lst
            }
          }
          return { character: updated, snapshotHistory, inventory: normalizeInventory(updated.inventory) }
        }),

      setPsyche: (psycheData) =>
        set((s) => ({
          character: s.character
            ? { ...s.character, psyche: psycheData }
            : s.character,
        })),

      pushSnapshot: () =>
        set((s) => {
          if (!s.character) return s
          const snapshot: CharacterSnapshot = {
            ts: Date.now(),
            character: JSON.parse(JSON.stringify(s.character)),
          }
          return {
            snapshotHistory: [...s.snapshotHistory, snapshot].slice(-SNAPSHOT_LIMIT),
          }
        }),

      restoreSnapshot: () => {
        const { snapshotHistory } = get()
        if (!snapshotHistory.length) return false
        const prev = snapshotHistory[snapshotHistory.length - 1]
        set({
          character: JSON.parse(JSON.stringify(prev.character)),
          snapshotHistory: snapshotHistory.slice(0, -1),
        })
        return true
      },

      clearSnapshots: () => set({ snapshotHistory: [] }),
    }),
    { name: 'characterStore' }
  )
)
