/**
 * MessageThread — 故事流（Part 消息列表）
 * 参考 12-frontend-architecture.md §3 StoryCanvas
 * 独立组件，负责：Part 过滤（按 Mode 可见性）+ 全量渲染 + 智能自动滚底
 * 注：当前为全量渲染（非虚拟滚动）；自动滚底会跟随流式增量，且仅在用户贴近底部时触发。
 */
import React, { useRef, useEffect, useMemo, useCallback } from 'react'
import { MessagePart } from '../stores/story'
import { PartRenderer } from './parts/PartRenderer'

type Mode = 'play' | 'plan' | 'review'

/** 各 Mode 下可见的 Part 类型 */
const VISIBLE_PARTS: Record<Mode, Set<string>> = {
  play: new Set([
    'narrative', 'dice_roll', 'state_patch', 'npc_action',
    'world_event', 'chapter_end', 'system_grant', 'action_options',
    'tool_call', 'tool_result', 'var_diff',
  ]),
  plan: new Set([
    'narrative', 'dice_roll', 'state_patch', 'npc_action',
    'world_event', 'chapter_end', 'dm_note', 'skill_load',
    'compaction', 'action_options', 'system_grant',
    'tool_call', 'tool_result', 'var_diff',
  ]),
  review: new Set([
    'narrative', 'dice_roll', 'state_patch', 'npc_action',
    'world_event', 'chapter_end', 'dm_note', 'skill_load',
    'compaction', 'permission_ask', 'system_grant', 'action_options',
    'tool_call', 'tool_result', 'var_diff', 'reasoning',
  ]),
}

interface Props {
  parts: MessagePart[]
  mode: Mode
  onSelectOption?: (text: string) => void
  className?: string
  /** 已存在的分支数（用于 Swipe 指示器） */
  branchCount?: number
  /** 从指定叙事消息分支出平行走向（Swipe 备选） */
  onForkFromMessage?: (messageId: string) => void
  /** 是否正在生成（生成中隐藏 Swipe 控件） */
  sending?: boolean
}

export const MessageThread: React.FC<Props> = ({
  parts,
  mode,
  onSelectOption,
  className = '',
  branchCount = 0,
  onForkFromMessage,
  sending = false,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  // 用户是否贴近底部（向上翻阅历史时为 false，避免被强拉到底）
  const nearBottomRef = useRef(true)

  const handleScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight
    nearBottomRef.current = dist < 120
  }, [])

  // 流式增量签名：累加各 part 的 streamBuffer 长度，使单条叙事流式输出也能触发跟随
  const streamSignature = useMemo(
    () => parts.reduce((n, p) => n + (p.streamBuffer?.length ?? 0), 0),
    [parts]
  )

  // 自动滚底：内容（条数或流式增量）变化时，仅当用户当前贴近底部才滚动
  useEffect(() => {
    if (nearBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [parts.length, streamSignature])

  const visible = VISIBLE_PARTS[mode]

  // 计算最新的 action_options part（用于抑制重复渲染）
  const lastActionOptionId = useMemo(() => {
    const optParts = parts.filter((p) => p.type === 'action_options')
    return optParts.length > 0 ? optParts[optParts.length - 1].id : null
  }, [parts])

  // 最新的已完成叙事消息（Swipe 控件锚点）
  const lastNarrativeMsgId = useMemo(() => {
    const narr = parts.filter((p) => p.type === 'narrative' && p.status !== 'streaming')
    return narr.length > 0 ? narr[narr.length - 1].message_id : null
  }, [parts])

  const visibleParts = parts.filter((p) => visible.has(p.type))

  return (
    <div ref={containerRef} onScroll={handleScroll} className={`overflow-y-auto px-4 py-4 space-y-1 ${className}`}>
      {visibleParts.map((p) => (
        <PartRenderer
          key={p.id}
          part={p}
          onSelectOption={onSelectOption}
          hideActionOptions={
            p.type === 'action_options' && p.id !== lastActionOptionId
          }
        />
      ))}

      {/* Swipe 备选指示器：在最新叙事气泡底部，可分支出平行走向 */}
      {!sending && lastNarrativeMsgId && onForkFromMessage && (
        <div className="flex items-center gap-2 pt-1 pl-1 text-[11px] text-zinc-600">
          <span className="font-mono tabular-nums" title="平行走向数（当前 + 已有分支）">
            ‹ 1/{branchCount + 1} ›
          </span>
          <button
            onClick={() => onForkFromMessage(lastNarrativeMsgId)}
            className="flex items-center gap-1 px-1.5 py-0.5 rounded hover:bg-zinc-800 hover:text-indigo-400 transition-colors"
            title="从此处分支出另一种叙事走向（创建平行分支）"
          >
            <span>⑂</span> 换一种走向
          </button>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
