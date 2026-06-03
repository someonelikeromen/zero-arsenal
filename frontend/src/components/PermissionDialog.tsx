/**
 * PermissionDialog — 权限确认弹窗
 * 当 Agent 请求 ask 权限的工具调用时，弹出此窗口让玩家决策
 */
import React, { useState } from 'react'
import { api } from '../lib/api'

interface Props {
  ask: {
    ask_id: string
    tool_name: string
    tool_args: unknown
    reason: string
  }
  sessionId: string
  onResolved: (decision: 'allow' | 'deny') => void
}

export const PermissionDialog: React.FC<Props> = ({ ask, sessionId, onResolved }) => {
  const [loading, setLoading] = useState(false)

  const handleDecision = async (decision: 'allow' | 'deny') => {
    if (loading) return
    setLoading(true)
    try {
      await api.resolveAsk(sessionId, ask.ask_id, decision)
      onResolved(decision)
    } catch {
      setLoading(false)
    }
  }

  const argsPreview = (() => {
    try {
      const s = JSON.stringify(ask.tool_args, null, 2)
      return s.length > 200 ? s.slice(0, 200) + '…' : s
    } catch {
      return String(ask.tool_args)
    }
  })()

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* dialog */}
      <div className="relative z-10 w-full max-w-md mx-4 bg-zinc-900 border border-zinc-700 rounded-xl shadow-2xl overflow-hidden">
        {/* header */}
        <div className="px-5 py-4 border-b border-zinc-800">
          <h2 className="text-base font-semibold text-amber-400">权限请求</h2>
        </div>

        {/* body */}
        <div className="px-5 py-4 space-y-3">
          <div>
            <span className="text-xs text-zinc-500 uppercase tracking-wide">工具</span>
            <p className="mt-0.5 text-sm font-mono text-zinc-100">{ask.tool_name}</p>
          </div>

          <div>
            <span className="text-xs text-zinc-500 uppercase tracking-wide">原因</span>
            <p className="mt-0.5 text-sm text-zinc-200">{ask.reason}</p>
          </div>

          {argsPreview && (
            <div>
              <span className="text-xs text-zinc-500 uppercase tracking-wide">参数预览</span>
              <pre className="mt-0.5 text-xs font-mono text-zinc-400 bg-zinc-800 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
                {argsPreview}
              </pre>
            </div>
          )}
        </div>

        {/* footer */}
        <div className="px-5 py-3 border-t border-zinc-800 flex gap-3 justify-end">
          <button
            onClick={() => handleDecision('deny')}
            disabled={loading}
            className="px-4 py-1.5 text-sm rounded bg-red-700 hover:bg-red-600
                       disabled:opacity-50 text-white transition-colors"
          >
            拒绝
          </button>
          <button
            onClick={() => handleDecision('allow')}
            disabled={loading}
            className="px-4 py-1.5 text-sm rounded bg-green-700 hover:bg-green-600
                       disabled:opacity-50 text-white transition-colors"
          >
            允许
          </button>
        </div>
      </div>
    </div>
  )
}
