/**
 * Zustand 确认对话框 Store — 全局承载一次确认请求 + Promise resolver。
 * 配合 <ConfirmDialog /> 全局组件与 useConfirmDialog() hook 使用，
 * 替代浏览器原生 window.confirm()，支持自定义文案与危险态样式。
 */
import { create } from 'zustand'

export interface ConfirmOptions {
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  /** 危险操作：确认按钮显示为红色 */
  danger?: boolean
}

interface ConfirmState {
  open: boolean
  options: ConfirmOptions | null
  _resolve: ((ok: boolean) => void) | null
  request: (options: ConfirmOptions) => Promise<boolean>
  respond: (ok: boolean) => void
}

export const useConfirmStore = create<ConfirmState>((set, get) => ({
  open: false,
  options: null,
  _resolve: null,

  request: (options) =>
    new Promise<boolean>((resolve) => {
      // 若已有未决请求，先拒绝旧的，避免 resolver 泄漏
      const prev = get()._resolve
      if (prev) prev(false)
      set({ open: true, options, _resolve: resolve })
    }),

  respond: (ok) => {
    const resolve = get()._resolve
    set({ open: false, options: null, _resolve: null })
    if (resolve) resolve(ok)
  },
}))

/**
 * 便捷 hook：返回 requestConfirm(options) => Promise<boolean>。
 * 用法：const ok = await requestConfirm({ title, message, danger: true })
 */
export function useConfirmDialog() {
  const request = useConfirmStore((s) => s.request)
  return { requestConfirm: request }
}

/** 非组件上下文（事件处理器/工具函数）直接调用 */
export function requestConfirm(options: ConfirmOptions): Promise<boolean> {
  return useConfirmStore.getState().request(options)
}
