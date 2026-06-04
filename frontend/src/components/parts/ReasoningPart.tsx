/**
 * ReasoningPart — 展示 Agent 的推理/思考过程
 * 参考 opencode Part 模型（reasoning type）
 * 默认折叠，点击展开；流式阶段显示 loading 状态。
 */
import React, { useState, useRef, useEffect } from 'react'
import { MessagePart, useStoryStore } from '../../stores/story'

interface Props {
  part: MessagePart
}

export const ReasoningPart: React.FC<Props> = ({ part }) => {
  const [expanded, setExpanded] = useState(false)
  const contentRef = useRef<HTMLDivElement>(null)

  const text: string =
    (part.content.text as string) ??
    (part.content.reasoning as string) ??
    part.streamBuffer ??
    ''

  // 流式阶段（conf_b12）：订阅 store streamBuffers[part.id]，展开时直写 DOM（不触发列表重渲染）
  useEffect(() => {
    if (part.status !== 'streaming' || !expanded) return
    const partId = part.id
    const write = (buf: string | undefined) => {
      if (contentRef.current != null) contentRef.current.textContent = buf ?? ''
    }
    write(useStoryStore.getState().streamBuffers[partId])
    let last = useStoryStore.getState().streamBuffers[partId]
    const unsub = useStoryStore.subscribe((s) => {
      const buf = s.streamBuffers[partId]
      if (buf !== last) {
        last = buf
        write(buf)
      }
    })
    return unsub
  }, [part.id, part.status, expanded])

  const isStreaming = part.status === 'streaming'
  const agentLabel = part.agent ? part.agent : 'reasoning'

  return (
    <div className="reasoning-part my-1.5 border border-zinc-800 rounded-lg overflow-hidden text-xs">
      {/* 折叠标题栏 */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center gap-2 px-3 py-1.5 bg-zinc-900 hover:bg-zinc-800 transition-colors text-left"
      >
        <span className="text-zinc-600 font-mono text-[10px] uppercase tracking-wider">
          {agentLabel}
        </span>
        {isStreaming && (
          <span className="flex gap-0.5 items-center">
            <span className="w-1 h-1 bg-zinc-500 rounded-full animate-bounce [animation-delay:0ms]" />
            <span className="w-1 h-1 bg-zinc-500 rounded-full animate-bounce [animation-delay:150ms]" />
            <span className="w-1 h-1 bg-zinc-500 rounded-full animate-bounce [animation-delay:300ms]" />
          </span>
        )}
        <span className="flex-1" />
        {!isStreaming && (
          <span className="text-zinc-600 text-[10px]">
            {text.length > 0 ? `${text.length} 字` : ''}
          </span>
        )}
        <span className="text-zinc-600">{expanded ? '▲' : '▼'}</span>
      </button>

      {/* 内容区 */}
      {expanded && (
        <div className="px-3 py-2 bg-zinc-950 border-t border-zinc-800">
          {isStreaming ? (
            <div
              ref={contentRef}
              className="text-zinc-500 whitespace-pre-wrap leading-relaxed font-mono"
            />
          ) : (
            <div className="text-zinc-500 whitespace-pre-wrap leading-relaxed font-mono">
              {text}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
