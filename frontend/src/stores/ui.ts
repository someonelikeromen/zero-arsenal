/**
 * Zustand UI Store — 全局 UI 状态（面板展开/折叠、主题、通知等）
 * 使用 immer middleware（12-frontend-architecture.md §3）
 */
import { create } from 'zustand'
import { immer } from 'zustand/middleware/immer'

export type PanelId =
  | 'character'
  | 'chapter'
  | 'dice'
  | 'world'
  | 'memory'
  | 'inventory'
  | 'history'
  | 'settings'

export type NotificationType = 'info' | 'success' | 'warning' | 'error'

export interface Notification {
  id: string
  type: NotificationType
  message: string
  duration?: number // ms，0 = 不自动关闭
  created_at: number
}

interface UIStore {
  /** 当前激活的侧边面板 */
  activePanel: PanelId | null
  /** 移动端侧边栏展开 */
  sidebarOpen: boolean
  /** 全局通知列表 */
  notifications: Notification[]
  /** 输入框是否禁用（Agent 处理中） */
  inputDisabled: boolean
  /** 当前主题（system = 跟随系统） */
  theme: 'dark' | 'light' | 'system'

  setActivePanel: (panel: PanelId | null) => void
  togglePanel: (panel: PanelId) => void
  setSidebarOpen: (open: boolean) => void
  setInputDisabled: (disabled: boolean) => void
  setTheme: (theme: 'dark' | 'light' | 'system') => void
  addNotification: (notification: Omit<Notification, 'id' | 'created_at'>) => string
  removeNotification: (id: string) => void
  clearNotifications: () => void
}

let _notifSeq = 0

function _loadPersistedTheme(): 'dark' | 'light' | 'system' {
  try {
    const saved = localStorage.getItem('za_theme')
    if (saved === 'dark' || saved === 'light' || saved === 'system') return saved
  } catch {
    // localStorage 不可用
  }
  return 'dark'
}

/** 将主题应用到 <html>：设置 color-scheme + theme-* class（system 跟随媒体查询）。 */
export function applyTheme(theme: 'dark' | 'light' | 'system'): void {
  if (typeof document === 'undefined') return
  let effective: 'dark' | 'light' = theme === 'system'
    ? (window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
    : theme
  const root = document.documentElement
  root.classList.remove('theme-dark', 'theme-light')
  root.classList.add(`theme-${effective}`)
  root.style.colorScheme = effective
}

export const useUIStore = create<UIStore>()(
  immer((set) => ({
    activePanel: 'character',
    sidebarOpen: false,
    notifications: [],
    inputDisabled: false,
    theme: _loadPersistedTheme(),

    setActivePanel: (panel) =>
      set((state) => {
        state.activePanel = panel
      }),

    togglePanel: (panel) =>
      set((state) => {
        state.activePanel = state.activePanel === panel ? null : panel
      }),

    setSidebarOpen: (open) =>
      set((state) => {
        state.sidebarOpen = open
      }),

    setInputDisabled: (disabled) =>
      set((state) => {
        state.inputDisabled = disabled
      }),

    setTheme: (theme) =>
      set((state) => {
        state.theme = theme
        try {
          localStorage.setItem('za_theme', theme)
        } catch {
          // localStorage 不可用时静默忽略
        }
        applyTheme(theme)
      }),

    addNotification: (notif) => {
      const id = `notif-${++_notifSeq}-${Date.now()}`
      set((state) => {
        state.notifications.push({ ...notif, id, created_at: Date.now() })
        // 最多保留 20 条
        if (state.notifications.length > 20) {
          state.notifications.splice(0, state.notifications.length - 20)
        }
      })
      return id
    },

    removeNotification: (id) =>
      set((state) => {
        const idx = state.notifications.findIndex((n) => n.id === id)
        if (idx !== -1) state.notifications.splice(idx, 1)
      }),

    clearNotifications: () =>
      set((state) => {
        state.notifications = []
      }),
  }))
)

/**
 * 便捷通知函数 — 可在任意上下文（含非组件、事件处理器、catch 块）调用。
 * 用法：notify.success('已保存') / notify.error('删除失败: ' + e)
 */
export const notify = {
  info: (message: string, duration?: number) =>
    useUIStore.getState().addNotification({ type: 'info', message, duration }),
  success: (message: string, duration?: number) =>
    useUIStore.getState().addNotification({ type: 'success', message, duration }),
  warning: (message: string, duration?: number) =>
    useUIStore.getState().addNotification({ type: 'warning', message, duration }),
  error: (message: string, duration?: number) =>
    useUIStore.getState().addNotification({ type: 'error', message, duration }),
}
