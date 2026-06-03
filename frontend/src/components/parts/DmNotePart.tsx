/**
 * DM 注释 Part — 折叠显示，仅在 plan/review 模式可见
 */
import React, { useState } from 'react'
import { MessagePart } from '../../stores/story'

interface Props {
  part: MessagePart
}

export const DmNotePart: React.FC<Props> = ({ part }) => {
  const [expanded, setExpanded] = useState(false)
  const note = part.content.note as string ?? ''

  return (
    <div className="dm-note-part my-1 text-xs">
      <button
        className="text-zinc-600 hover:text-zinc-400 flex items-center gap-1"
        onClick={() => setExpanded(!expanded)}
      >
        <span>{expanded ? '▾' : '▸'}</span>
        <span>[DM] {note.slice(0, 60)}{note.length > 60 ? '...' : ''}</span>
      </button>
      {expanded && (
        <div className="mt-1 pl-3 text-zinc-500 border-l border-zinc-700 whitespace-pre-wrap">
          {note}
        </div>
      )}
    </div>
  )
}
