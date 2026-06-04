/**
 * NarrativePart — 流式叙事渲染，useRef + textContent 直写优化
 * 参考 12-frontend-architecture.md §4.3 + §6
 *
 * 流式阶段：useEffect 监听 streamBuffer 变化，直接 node.textContent 写入，跳过 React diff
 * 完成后：React state 接管，触发一次完整渲染（支持 Markdown 基础格式）
 */
import React, { useRef, useEffect } from 'react'
import { MessagePart, useStoryStore } from '../../stores/story'

interface Props {
  part: MessagePart
}

export const NarrativePart: React.FC<Props> = ({ part }) => {
  const containerRef = useRef<HTMLDivElement>(null)

  // 流式阶段（conf_b12 细粒度订阅）：直接订阅 store 的 streamBuffers[part.id]，
  // 每个 delta 仅通过 imperative subscribe 回调直写 DOM textContent，
  // 既跳过 React diff，也不触发列表/兄弟组件重渲染。
  useEffect(() => {
    if (part.status !== 'streaming') return
    const partId = part.id
    const write = (buf: string | undefined) => {
      if (containerRef.current != null) containerRef.current.textContent = buf ?? ''
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
  }, [part.id, part.status])

  const agentLabel = part.agent && part.agent !== 'narrator' ? `[${part.agent}]` : ''

  if (part.status === 'streaming') {
    return (
      <div className="narrative-part my-3 leading-relaxed text-zinc-100">
        <StatusLed status="streaming" />
        {agentLabel && (
          <span className="text-[10px] text-zinc-600 mr-1">{agentLabel}</span>
        )}
        <div ref={containerRef} className="inline whitespace-pre-wrap" />
        <span className="inline-block w-1.5 h-4 bg-zinc-400 animate-pulse ml-0.5 align-middle" />
      </div>
    )
  }

  if (part.status === 'error') {
    const finalText = (part.content.text as string) ?? part.streamBuffer ?? ''
    return (
      <div className="narrative-part my-3 leading-relaxed text-red-300">
        <StatusLed status="error" />
        {agentLabel && <span className="text-[10px] text-zinc-600 mr-1">{agentLabel}</span>}
        <span className="whitespace-pre-wrap">{finalText || '叙事生成出错'}</span>
      </div>
    )
  }

  // 完成态：Markdown 基础渲染
  const finalText = (part.content.text as string) ?? part.streamBuffer ?? ''
  const paragraphs = finalText.split(/\n\n+/).filter(Boolean)

  return (
    <div className="narrative-part my-3 leading-relaxed text-zinc-100 space-y-3">
      {agentLabel && (
        <span className="text-[10px] text-zinc-600">
          <StatusLed status="done" />{agentLabel}
        </span>
      )}
      {paragraphs.map((para, i) => (
        <p
          key={i}
          className="text-zinc-100"
          dangerouslySetInnerHTML={{ __html: renderInline(para) }}
        />
      ))}
    </div>
  )
}

/** 流式状态指示 LED：streaming(脉冲蓝) / done(绿) / error(红) */
const StatusLed: React.FC<{ status: 'streaming' | 'done' | 'error' }> = ({ status }) => {
  const cfg = {
    streaming: { cls: 'bg-indigo-400 animate-pulse', title: '生成中' },
    done:      { cls: 'bg-emerald-500',              title: '已完成' },
    error:     { cls: 'bg-red-500',                  title: '出错' },
  }[status]
  return (
    <span
      title={cfg.title}
      className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle ${cfg.cls}`}
    />
  )
}

/** 基础 Markdown inline 渲染（已做 HTML escape，安全）*/
function renderInline(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br>')
}
