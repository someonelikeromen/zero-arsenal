/**
 * ConfirmDialog — 全局确认对话框。
 * 读取 useConfirmStore 的一次确认请求并渲染居中模态，替代 window.confirm()。
 * 支持 danger 红色确认按钮、自定义按钮文案、Esc 取消 / Enter 确认。
 */
import { useEffect } from 'react'
import { useConfirmStore } from '../stores/confirm'

export function ConfirmDialog() {
  const open = useConfirmStore((s) => s.open)
  const options = useConfirmStore((s) => s.options)
  const respond = useConfirmStore((s) => s.respond)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') respond(false)
      else if (e.key === 'Enter') respond(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, respond])

  if (!open || !options) return null

  const { title, message, confirmText = '确认', cancelText = '取消', danger } = options

  return (
    <div
      className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={() => respond(false)}
    >
      <div
        className="mx-4 w-full max-w-sm rounded-lg border border-zinc-700 bg-zinc-900 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <h3 className="mb-2 text-sm font-semibold text-zinc-100">{title}</h3>
        <p className="mb-5 whitespace-pre-wrap text-xs leading-relaxed text-zinc-400">{message}</p>
        <div className="flex justify-end gap-2">
          <button
            onClick={() => respond(false)}
            className="rounded border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800"
          >
            {cancelText}
          </button>
          <button
            onClick={() => respond(true)}
            className={
              danger
                ? 'rounded bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-500'
                : 'rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-500'
            }
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
