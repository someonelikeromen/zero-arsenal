/**
 * ModeSelector — play/plan/review 模式切换按钮组
 * 参考 12-frontend-architecture.md §3
 */
import React from 'react'

type Mode = 'play' | 'plan' | 'review'

interface Props {
  mode: Mode
  onChange: (mode: Mode) => void
  disabled?: boolean
}

const MODE_LABELS: Record<Mode, { label: string; title: string }> = {
  play:   { label: 'Play',   title: '玩家模式：沉浸叙事' },
  plan:   { label: 'Plan',   title: '规划模式：显示 DM 注释，写操作需确认' },
  review: { label: 'Review', title: '审阅模式：严格只读，显示全部内部信息' },
}

export const ModeSelector: React.FC<Props> = ({ mode, onChange, disabled }) => {
  return (
    <div className="flex gap-1" role="group" aria-label="游戏模式">
      {(Object.keys(MODE_LABELS) as Mode[]).map((m) => (
        <button
          key={m}
          title={MODE_LABELS[m].title}
          disabled={disabled}
          onClick={() => onChange(m)}
          className={`px-2 py-0.5 text-xs rounded transition-colors disabled:opacity-50 ${
            mode === m
              ? 'bg-indigo-600 text-white'
              : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
          }`}
        >
          {MODE_LABELS[m].label}
        </button>
      ))}
    </div>
  )
}
