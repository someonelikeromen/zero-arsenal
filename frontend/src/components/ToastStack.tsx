/**
 * ToastStack — 全局通知栈。
 * 从 useUIStore.notifications 读取并渲染，固定右下角，最多 4 条可见，
 * 默认 4200ms 自动消失（duration=0 时常驻）。三色 tone：success/error/warning/info。
 */
import { useEffect } from 'react'
import { useUIStore, type Notification, type NotificationType } from '../stores/ui'

const TONE: Record<NotificationType, { bg: string; border: string; icon: string }> = {
  success: { bg: 'bg-emerald-950/90', border: 'border-emerald-600', icon: '✓' },
  error: { bg: 'bg-red-950/90', border: 'border-red-600', icon: '✕' },
  warning: { bg: 'bg-amber-950/90', border: 'border-amber-600', icon: '!' },
  info: { bg: 'bg-zinc-900/90', border: 'border-zinc-600', icon: 'i' },
}

const DEFAULT_DURATION = 4200

function ToastItem({ n }: { n: Notification }) {
  const remove = useUIStore((s) => s.removeNotification)
  const duration = n.duration ?? DEFAULT_DURATION

  useEffect(() => {
    if (duration <= 0) return
    const t = setTimeout(() => remove(n.id), duration)
    return () => clearTimeout(t)
  }, [n.id, duration, remove])

  const tone = TONE[n.type] ?? TONE.info
  return (
    <div
      className={`${tone.bg} ${tone.border} animate-slide-in-top pointer-events-auto flex items-start gap-2 rounded border px-3 py-2 text-xs text-zinc-100 shadow-lg backdrop-blur`}
      role="status"
    >
      <span className="mt-0.5 font-bold opacity-80">{tone.icon}</span>
      <span className="flex-1 whitespace-pre-wrap break-words">{n.message}</span>
      <button
        onClick={() => remove(n.id)}
        className="ml-1 text-zinc-400 hover:text-zinc-100"
        aria-label="关闭通知"
      >
        ×
      </button>
    </div>
  )
}

export function ToastStack() {
  const notifications = useUIStore((s) => s.notifications)
  const visible = notifications.slice(-4)

  if (visible.length === 0) return null

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[9999] flex w-72 flex-col gap-2">
      {visible.map((n) => (
        <ToastItem key={n.id} n={n} />
      ))}
    </div>
  )
}
