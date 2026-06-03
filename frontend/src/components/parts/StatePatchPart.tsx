/**
 * 状态变更 Part — 展示角色/世界变量的增减
 */
import React from 'react'
import { MessagePart } from '../../stores/story'

interface Patch {
  key: string
  old_value?: unknown
  new_value?: unknown
  delta?: number
}

interface Props {
  part: MessagePart
}

export const StatePatchPart: React.FC<Props> = ({ part }) => {
  const patches = (part.content.patches as Patch[]) ?? []
  if (patches.length === 0) return null

  return (
    <div className="state-patch-part my-2 text-xs font-mono text-zinc-400 space-y-0.5">
      {patches.map((p, i) => {
        const delta = p.delta ?? (
          typeof p.new_value === 'number' && typeof p.old_value === 'number'
            ? p.new_value - p.old_value
            : null
        )
        return (
          <div key={i} className="flex items-center gap-1">
            <span className="text-zinc-500">[变量]</span>
            <span className="text-zinc-300">{p.key}</span>
            {delta !== null && (
              <span className={delta >= 0 ? 'text-green-400' : 'text-red-400'}>
                {delta >= 0 ? `+${delta}` : String(delta)}
              </span>
            )}
            <span className="text-zinc-600">→ {String(p.new_value ?? '?')}</span>
          </div>
        )
      })}
    </div>
  )
}
