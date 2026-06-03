/**
 * ThemeGuideModal — 首次进入时的主题选择引导
 * localStorage 无 za_has_visited 时弹出，三张预览卡（暗色/亮色/跟随系统）
 */
import { useState } from 'react'
import { useUIStore } from '../stores/ui'

const LS_VISITED = 'za_has_visited'

type ThemeChoice = 'dark' | 'light' | 'system'

const CHOICES: { id: ThemeChoice; label: string; desc: string; preview: string }[] = [
  { id: 'dark',   label: '暗色',     desc: '默认沉浸式深色界面', preview: 'bg-zinc-900 border-zinc-700' },
  { id: 'light',  label: '亮色',     desc: '明亮清爽，适合白天', preview: 'bg-zinc-100 border-zinc-300' },
  { id: 'system', label: '跟随系统', desc: '随操作系统自动切换', preview: 'bg-gradient-to-br from-zinc-900 to-zinc-100 border-zinc-500' },
]

export function shouldShowThemeGuide(): boolean {
  try {
    return !localStorage.getItem(LS_VISITED)
  } catch {
    return false
  }
}

export function ThemeGuideModal({ onClose }: { onClose: () => void }) {
  const setTheme = useUIStore(s => s.setTheme)
  const current = useUIStore(s => s.theme)
  const [selected, setSelected] = useState<ThemeChoice>(current)

  const confirm = () => {
    setTheme(selected)
    try { localStorage.setItem(LS_VISITED, '1') } catch { /* ignore */ }
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 w-[460px] max-w-[92vw] shadow-2xl">
        <h2 className="text-lg font-bold text-zinc-100 mb-1">欢迎使用零度武库</h2>
        <p className="text-sm text-zinc-500 mb-5">先选择一个外观主题，稍后可在「设置 → 外观」中更改。</p>

        <div className="grid grid-cols-3 gap-3 mb-6">
          {CHOICES.map(c => (
            <button
              key={c.id}
              onClick={() => setSelected(c.id)}
              className={`rounded-lg border p-3 text-left transition-colors ${
                selected === c.id ? 'border-indigo-500 bg-indigo-600/10' : 'border-zinc-700 hover:border-zinc-500'
              }`}
            >
              <div className={`h-16 rounded border mb-2 ${c.preview}`} />
              <div className="text-sm font-medium text-zinc-200">{c.label}</div>
              <div className="text-[10px] text-zinc-500 mt-0.5 leading-snug">{c.desc}</div>
            </button>
          ))}
        </div>

        <button
          onClick={confirm}
          className="w-full bg-indigo-600 hover:bg-indigo-500 text-white py-2.5 rounded text-sm font-medium transition-colors"
        >
          开始使用
        </button>
      </div>
    </div>
  )
}
