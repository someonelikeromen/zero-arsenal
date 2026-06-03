/**
 * VarDiffPart — 展示变量差异（before → after）
 * 参考 pi TUI 差异渲染 + StatePatchPart 功能超集
 * 支持：数值增减、布尔切换、字符串替换、数组差异
 */
import React from 'react'
import { MessagePart } from '../../stores/story'

interface VarChange {
  key: string
  label?: string
  before: unknown
  after: unknown
  unit?: string
}

interface Props {
  part: MessagePart
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'boolean') return v ? '✓' : '✗'
  if (typeof v === 'number') return String(v)
  if (typeof v === 'string') return `"${v}"`
  if (Array.isArray(v)) return `[${v.length} 项]`
  return JSON.stringify(v)
}

function DeltaBadge({ before, after }: { before: unknown; after: unknown }) {
  if (typeof before === 'number' && typeof after === 'number') {
    const delta = after - before
    if (delta === 0) return null
    return (
      <span
        className={`text-[10px] font-mono px-1 rounded ${
          delta > 0 ? 'text-green-500' : 'text-red-400'
        }`}
      >
        {delta > 0 ? `+${delta}` : delta}
      </span>
    )
  }
  return null
}

export const VarDiffPart: React.FC<Props> = ({ part }) => {
  const d = part.content as {
    changes?: VarChange[]
    character?: string
    source?: string
  }

  const changes: VarChange[] = d.changes ?? []

  if (changes.length === 0) return null

  return (
    <div className="var-diff-part my-1.5 border border-zinc-800 rounded text-xs overflow-hidden">
      {/* 头部 */}
      <div className="flex items-center gap-2 px-3 py-1 bg-zinc-900 border-b border-zinc-800">
        <span className="text-zinc-600">◎</span>
        <span className="text-zinc-500 font-medium">
          {d.character ? `${d.character} 属性变化` : '状态变化'}
        </span>
        {d.source && (
          <span className="ml-auto text-zinc-700 text-[10px]">{d.source}</span>
        )}
      </div>

      {/* 变化列表 */}
      <div className="divide-y divide-zinc-900">
        {changes.map((ch, i) => {
          const isNumeric = typeof ch.before === 'number' && typeof ch.after === 'number'
          const increased = isNumeric && (ch.after as number) > (ch.before as number)
          const decreased = isNumeric && (ch.after as number) < (ch.before as number)

          return (
            <div key={i} className="flex items-center gap-2 px-3 py-1.5 bg-zinc-950">
              {/* 指示条 */}
              <div
                className={`w-0.5 h-4 rounded-full flex-shrink-0 ${
                  increased
                    ? 'bg-green-600'
                    : decreased
                    ? 'bg-red-600'
                    : 'bg-zinc-600'
                }`}
              />

              {/* 属性名 */}
              <span className="text-zinc-400 w-24 flex-shrink-0 truncate">
                {ch.label ?? ch.key}
              </span>

              {/* before → after */}
              <div className="flex items-center gap-1.5 flex-1 font-mono">
                <span className="text-zinc-600">{formatValue(ch.before)}</span>
                <span className="text-zinc-700">→</span>
                <span
                  className={
                    increased
                      ? 'text-green-400'
                      : decreased
                      ? 'text-red-400'
                      : 'text-zinc-300'
                  }
                >
                  {formatValue(ch.after)}
                </span>
                {ch.unit && (
                  <span className="text-zinc-600">{ch.unit}</span>
                )}
                <DeltaBadge before={ch.before} after={ch.after} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
