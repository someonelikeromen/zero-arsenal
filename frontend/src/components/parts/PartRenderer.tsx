/**
 * Part 渲染器 — 根据 Part 类型分发到对应渲染组件
 * 参考 opencode Part 模型 + pi TUI 差异渲染思路
 *
 * 懒加载策略（设计文档 12-frontend-architecture.md §4.1）：
 * - 高频核心 Part（NarrativePart / StatePatchPart / DmNotePart）：直接 import，减少首屏 Suspense 闪烁
 * - 低频/重型 Part（DiceRollPart / ReasoningPart / ToolCallPart 等）：React.lazy 懒加载
 */
import React, { Suspense } from 'react'
import { MessagePart } from '../../stores/story'

// ── 高频核心 Part：直接导入（每条消息几乎都会出现）──────────────────────────
import { NarrativePart } from './NarrativePart'
import { StatePatchPart } from './StatePatchPart'
import { DmNotePart } from './DmNotePart'
import { TextPart } from './TextPart'

// ── 低频 / 重型 Part：懒加载（减少首屏 bundle）──────────────────────────────
const DiceRollPart    = React.lazy(() => import('./DiceRollPart').then(m => ({ default: m.DiceRollPart })))
const NpcActionPart   = React.lazy(() => import('./NpcActionPart').then(m => ({ default: m.NpcActionPart })))
const WorldEventPart  = React.lazy(() => import('./WorldEventPart').then(m => ({ default: m.WorldEventPart })))
const ReasoningPart   = React.lazy(() => import('./ReasoningPart').then(m => ({ default: m.ReasoningPart })))
const ToolCallPart    = React.lazy(() => import('./ToolCallPart').then(m => ({ default: m.ToolCallPart })))
const ToolResultPart  = React.lazy(() => import('./ToolResultPart').then(m => ({ default: m.ToolResultPart })))
const VarDiffPart     = React.lazy(() => import('./VarDiffPart').then(m => ({ default: m.VarDiffPart })))

/** 懒加载期间的骨架占位符（避免布局抖动）*/
const PartSkeleton: React.FC = () => (
  <div className="h-4 w-full animate-pulse rounded bg-zinc-800/50 my-1" />
)

interface Props {
  part: MessagePart
  onSelectOption?: (text: string) => void  // action_options 选项回调
  hideActionOptions?: boolean              // 隐藏内联选项卡（底部栏已展示最新）
}

export const PartRenderer: React.FC<Props> = ({ part, onSelectOption, hideActionOptions }) => {
  switch (part.type) {
    // ── 高频核心（直接渲染）────────────────────────────────────────────────
    case 'narrative':
      return <NarrativePart part={part} />
    case 'state_patch':
      return <StatePatchPart part={part} />
    case 'dm_note':
      return <DmNotePart part={part} />
    case 'text':
      return <TextPart part={part} />

    // ── 低频 / 重型（懒加载，Suspense 包裹）────────────────────────────────
    case 'dice_roll':
      return (
        <Suspense fallback={<PartSkeleton />}>
          <DiceRollPart part={part} />
        </Suspense>
      )
    case 'npc_action':
      return (
        <Suspense fallback={<PartSkeleton />}>
          <NpcActionPart part={part} />
        </Suspense>
      )
    case 'world_event':
      return (
        <Suspense fallback={<PartSkeleton />}>
          <WorldEventPart part={part} />
        </Suspense>
      )
    case 'reasoning':
      return (
        <Suspense fallback={<PartSkeleton />}>
          <ReasoningPart part={part} />
        </Suspense>
      )
    case 'tool_call':
      return (
        <Suspense fallback={<PartSkeleton />}>
          <ToolCallPart part={part} />
        </Suspense>
      )
    case 'tool_result':
      return (
        <Suspense fallback={<PartSkeleton />}>
          <ToolResultPart part={part} />
        </Suspense>
      )
    case 'var_diff':
      return (
        <Suspense fallback={<PartSkeleton />}>
          <VarDiffPart part={part} />
        </Suspense>
      )

    // ── 内联渲染（无独立组件，轻量 JSX）───────────────────────────────────
    case 'chapter_end':
      return (
        <div className="my-4 flex items-center gap-2 text-sm text-zinc-500">
          <div className="flex-1 h-px bg-zinc-700" />
          <span>第 {String(part.content.chapter_num ?? '?')} 章结束</span>
          <div className="flex-1 h-px bg-zinc-700" />
        </div>
      )
    case 'permission_ask':
      return (
        <div className="my-2 p-3 border border-amber-700 rounded text-xs text-amber-300">
          <div className="font-medium mb-1">权限请求</div>
          <div className="text-amber-400">{String(part.content.reason ?? '')}</div>
          <div className="text-zinc-500 mt-1">工具：{String(part.content.tool_name ?? '')}</div>
        </div>
      )
    case 'compaction': {
      const d = part.content as { summary?: string; tokens_before?: number; tokens_after?: number }
      return (
        <div className="compaction-part my-2 px-3 py-2 bg-zinc-900 border border-zinc-700 rounded text-xs text-zinc-500 flex items-center gap-2">
          <span>⚡</span>
          <span>上下文已压缩 {d.tokens_before ? `${d.tokens_before}→${d.tokens_after} tokens` : ''}</span>
          {d.summary && <span className="text-zinc-600 truncate">{d.summary.slice(0, 60)}</span>}
        </div>
      )
    }
    case 'skill_load': {
      const d = part.content as { skill_name?: string; trigger?: string }
      return (
        <div className="skill-load-part my-1 text-xs text-indigo-500 flex items-center gap-1">
          <span>◈</span>
          <span>技能已激活：{d.skill_name ?? '未知'}</span>
          {d.trigger && <span className="text-zinc-600">({d.trigger})</span>}
        </div>
      )
    }
    case 'system_grant': {
      const d = part.content as { tool_name?: string; reason?: string; decision?: string }
      const granted = d.decision !== 'deny'
      return (
        <div className={`my-1 flex items-center gap-2 text-xs px-2 py-1 rounded ${
          granted ? 'text-green-500' : 'text-red-500'
        }`}>
          <span>{granted ? '✓' : '✗'}</span>
          <span>工具 {d.tool_name ?? '?'} {granted ? '已授权' : '已拒绝'}</span>
          {d.reason && <span className="text-zinc-600 truncate">— {d.reason}</span>}
        </div>
      )
    }
    case 'action_options': {
      if (hideActionOptions) return null
      const d = part.content as { options?: { label: string; text: string }[]; context?: string }
      const options = d.options ?? []
      return (
        <div className="my-2 border border-zinc-800 rounded-lg overflow-hidden bg-zinc-900/50">
          <div className="px-3 py-1.5 text-[10px] text-zinc-600 border-b border-zinc-800">
            ── 建议行动（历史快照）──
          </div>
          <div className="flex flex-wrap gap-1.5 p-2">
            {options.map((opt) => (
              <button
                key={opt.label}
                onClick={() => onSelectOption?.(opt.text)}
                className="px-2.5 py-1 bg-zinc-800 border border-zinc-700/50 hover:border-indigo-600 hover:bg-zinc-700 rounded text-xs text-zinc-400 transition-colors text-left"
                title="点击填入输入框"
              >
                <span className="text-indigo-500 font-medium mr-1">{opt.label}.</span>
                {opt.text}
              </button>
            ))}
          </div>
        </div>
      )
    }
    default: {
      // 兜底：未知 Part 类型不再静默丢弃，渲染灰色占位块便于发现遗漏
      const unknownType = String((part as { type?: unknown }).type ?? 'unknown')
      let preview = ''
      try {
        preview = JSON.stringify((part as { content?: unknown }).content ?? {}).slice(0, 120)
      } catch {
        preview = ''
      }
      return (
        <div className="my-1 px-3 py-2 bg-zinc-800/40 border border-dashed border-zinc-700 rounded text-xs text-zinc-500">
          <div className="flex items-center gap-1.5">
            <span>❔</span>
            <span>未知内容类型：</span>
            <code className="text-zinc-400">[type: {unknownType}]</code>
          </div>
          {preview && <div className="mt-1 text-zinc-600 truncate font-mono">{preview}</div>}
        </div>
      )
    }
  }
}
