/**
 * 骰子结果 Part — 可视化骰池
 */
import React from 'react'
import { MessagePart } from '../../stores/story'
import type { DiceRollResult } from '../../lib/api'

const VERDICT_COLOR: Record<string, string> = {
  critical: 'text-yellow-400',
  success:  'text-green-400',
  failure:  'text-zinc-400',
  botch:    'text-red-500',
}

interface Props {
  part: MessagePart
}

export const DiceRollPart: React.FC<Props> = ({ part }) => {
  const r = part.content as unknown as DiceRollResult
  const verdictColor = VERDICT_COLOR[r.verdict] ?? 'text-zinc-400'

  return (
    <div className="dice-roll-part my-3 border border-zinc-700 rounded-lg p-4 bg-zinc-900/50">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">🎲</span>
        <span className="text-sm font-mono text-zinc-300">{r.pool_formula}</span>
        {r.reason && (
          <span className="text-xs text-zinc-500 ml-auto">{r.reason}</span>
        )}
      </div>

      {/* 骰子点数 */}
      <div className="flex flex-wrap gap-1.5 my-2">
        {r.rolls.map((val, i) => (
          <span
            key={i}
            className={`
              w-8 h-8 rounded flex items-center justify-center text-sm font-bold
              ${val >= r.threshold ? 'bg-green-900 text-green-300' : ''}
              ${val === 1 ? 'bg-red-900 text-red-300' : ''}
              ${val < r.threshold && val !== 1 ? 'bg-zinc-800 text-zinc-400' : ''}
            `}
          >
            {val}
          </span>
        ))}
      </div>

      {/* 结果 */}
      <div className={`mt-2 text-base font-semibold ${verdictColor}`}>
        {r.result}
        <span className="ml-2 text-sm font-normal text-zinc-400">
          净成功 {r.net} ({r.successes}成功 / {r.ones}抵消)
        </span>
      </div>

      {/* 叙事建议 */}
      <div className="mt-1 text-xs text-zinc-500 italic">{r.narrative_hint}</div>
    </div>
  )
}
