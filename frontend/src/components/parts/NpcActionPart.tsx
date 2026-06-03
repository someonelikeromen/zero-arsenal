/**
 * NPC 行为 Part — 展示 NPC Agent 输出的行动/台词
 */
import React, { useState } from 'react'
import { MessagePart } from '../../stores/story'

interface NpcReaction {
  npc_name: string
  intention: string
  dialogue?: string | null
  emotion: string
}

interface Props {
  part: MessagePart
}

export const NpcActionPart: React.FC<Props> = ({ part }) => {
  const [expanded, setExpanded] = useState(false)
  // 后端每条 npc_action Part 是一个扁平 NpcReaction 对象（非 reactions 数组）
  const raw = part.content as unknown as NpcReaction & { reactions?: NpcReaction[] }
  // 兼容两种格式：扁平对象 或 {reactions:[...]} 包裹
  const reactions: NpcReaction[] = raw.reactions ?? (raw.npc_name ? [raw] : [])
  if (reactions.length === 0) return null

  return (
    <div className="npc-action-part my-2 border border-zinc-800 rounded bg-zinc-900/50">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-300"
      >
        <span className="text-zinc-600">[NPC]</span>
        <span>{reactions.map(r => r.npc_name).join(' / ')}</span>
        <span className="ml-auto">{expanded ? '▲' : '▼'}</span>
      </button>
      {expanded && (
        <div className="px-3 pb-2 space-y-2">
          {reactions.map((r, i) => (
            <div key={i} className="text-xs">
              <div className="flex items-center gap-2">
                <span className="font-medium text-amber-400">{r.npc_name}</span>
                <span className="text-zinc-500 text-[10px]">[{r.emotion}]</span>
              </div>
              <div className="text-zinc-400 mt-0.5">{r.intention}</div>
              {r.dialogue && (
                <div className="mt-1 pl-2 border-l border-amber-700 text-zinc-300 italic">
                  「{r.dialogue}」
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
