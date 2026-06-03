/**
 * ToolCallPart — 展示工具调用（名称 + 参数 + 结果）
 * 参考 opencode Part 模型（tool_call / tool_result）
 * 默认折叠参数；结果成功为绿色，失败为红色。
 */
import React, { useState } from 'react'
import { MessagePart } from '../../stores/story'

interface Props {
  part: MessagePart
}

export const ToolCallPart: React.FC<Props> = ({ part }) => {
  const [showArgs, setShowArgs] = useState(false)

  const d = part.content as {
    tool_name?: string
    tool_id?: string
    args?: Record<string, unknown>
    result?: unknown
    error?: string
    duration_ms?: number
    status?: 'pending' | 'done' | 'error'
  }

  const toolName  = d.tool_name ?? '未知工具'
  const hasResult = d.result !== undefined || d.error !== undefined
  const isError   = !!d.error || d.status === 'error'
  const isPending = part.status === 'streaming' || d.status === 'pending'

  const resultStr = d.error
    ? d.error
    : d.result !== undefined
    ? typeof d.result === 'string'
      ? d.result
      : JSON.stringify(d.result, null, 2)
    : ''

  return (
    <div
      className={`tool-call-part my-1 border rounded text-xs font-mono overflow-hidden ${
        isError
          ? 'border-red-800 bg-red-950/30'
          : hasResult
          ? 'border-zinc-800 bg-zinc-950'
          : 'border-zinc-800 bg-zinc-900/50'
      }`}
    >
      {/* 工具名行 */}
      <div className="flex items-center gap-2 px-3 py-1.5">
        {isPending ? (
          <span className="text-amber-500 animate-pulse">⚙</span>
        ) : isError ? (
          <span className="text-red-500">✗</span>
        ) : (
          <span className="text-green-600">✓</span>
        )}
        <span className={`font-semibold ${isError ? 'text-red-400' : 'text-zinc-300'}`}>
          {toolName}
        </span>
        {d.duration_ms !== undefined && (
          <span className="text-zinc-600 ml-auto">{d.duration_ms.toFixed(0)}ms</span>
        )}
        {d.args && Object.keys(d.args).length > 0 && (
          <button
            onClick={() => setShowArgs(s => !s)}
            className="text-zinc-600 hover:text-zinc-400 transition-colors text-[10px] ml-1"
          >
            {showArgs ? '收起参数 ▲' : '查看参数 ▼'}
          </button>
        )}
      </div>

      {/* 参数区（折叠） */}
      {showArgs && d.args && (
        <div className="px-3 pb-1.5 border-t border-zinc-800 bg-zinc-950">
          <pre className="text-zinc-500 text-[10px] leading-relaxed whitespace-pre-wrap overflow-x-auto max-h-32">
            {JSON.stringify(d.args, null, 2)}
          </pre>
        </div>
      )}

      {/* 结果区 */}
      {hasResult && (
        <div
          className={`px-3 py-1.5 border-t ${
            isError ? 'border-red-900 text-red-400' : 'border-zinc-800 text-zinc-500'
          } max-h-24 overflow-y-auto`}
        >
          <pre className="text-[10px] whitespace-pre-wrap leading-relaxed">{resultStr}</pre>
        </div>
      )}
    </div>
  )
}
