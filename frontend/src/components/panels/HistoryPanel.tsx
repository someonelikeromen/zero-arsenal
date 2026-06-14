/**
 * HistoryPanel — 历史记录面板（骰子历史 + 消息回溯）
 * 设计文档 12 §4.6
 */
import React, { useEffect, useState } from 'react'
import { api, apiFetch } from '../../lib/api'
import { notify } from '../../stores/ui'
import { requestConfirm } from '../../stores/confirm'

interface DiceRecord {
  id: string
  pool: number
  threshold: number
  rolls: number[]
  net: number
  verdict: string
  attribute: string
  reason: string
  created_at: number
}

interface MessageRecord {
  id: string
  role: 'user' | 'assistant' | 'system'
  content?: string
  created_at: number
  turn_index?: number
  part_ids?: string
}

interface HistoryPanelProps {
  sessionId: string
}

const VERDICT_COLORS: Record<string, string> = {
  critical: 'text-yellow-400',
  success:  'text-green-400',
  failure:  'text-red-400',
  botch:    'text-red-700',
}

type Tab = 'dice' | 'messages'

export const HistoryPanel: React.FC<HistoryPanelProps> = ({ sessionId }) => {
  const [tab, setTab]                   = useState<Tab>('dice')
  const [diceHistory, setDiceHistory]   = useState<DiceRecord[]>([])
  const [messages, setMessages]         = useState<MessageRecord[]>([])
  const [loading, setLoading]           = useState(false)
  const [reverting, setReverting]       = useState<string | null>(null)
  const [revertResult, setRevertResult] = useState<string | null>(null)

  // 加载骰子历史
  useEffect(() => {
    if (!sessionId || tab !== 'dice') return
    setLoading(true)
    api.getDiceHistory(sessionId, 30)
      .then(d => setDiceHistory((d.history ?? []) as DiceRecord[]))
      .catch((e) => notify.error(`加载骰子历史失败：${e}`))
      .finally(() => setLoading(false))
  }, [sessionId, tab])

  // 加载消息历史
  useEffect(() => {
    if (!sessionId || tab !== 'messages') return
    setLoading(true)
    apiFetch<{ messages?: Record<string, unknown>[] }>(`/sessions/${sessionId}/messages?limit=30`)
      .then(d => {
        const list: MessageRecord[] = (d.messages ?? []).map((m: Record<string, unknown>) => ({
          id:          m.id as string,
          role:        m.role as 'user' | 'assistant' | 'system',
          content:     m.content as string | undefined,
          created_at:  m.created_at as number,
          turn_index:  m.turn_index as number | undefined,
          part_ids:    m.part_ids as string | undefined,
        }))
        setMessages(list.reverse()) // 最新在上
      })
      .catch((e) => notify.error(`加载消息历史失败：${e}`))
      .finally(() => setLoading(false))
  }, [sessionId, tab])

  const handleRevert = async (messageId: string) => {
    const ok = await requestConfirm({
      title: '回溯状态',
      message: '确定回溯到此消息之前的状态？之后的内容将被移除。',
      confirmText: '回溯',
      danger: true,
    })
    if (!ok) return
    setReverting(messageId)
    setRevertResult(null)
    try {
      await api.revertToMessage(sessionId, messageId)
      setRevertResult('回溯成功，请刷新页面查看效果')
      notify.success('回溯成功，请刷新页面查看效果')
      // 重新拉消息列表
      setMessages(prev => {
        const idx = prev.findIndex(m => m.id === messageId)
        return idx >= 0 ? prev.slice(idx) : prev
      })
    } catch (e) {
      setRevertResult(`回溯失败：${e}`)
      notify.error(`回溯失败：${e}`)
    } finally {
      setReverting(null)
    }
  }

  return (
    <div className="history-panel flex flex-col bg-zinc-900 rounded-lg border border-zinc-800">
      {/* Tab 切换 */}
      <div className="flex items-center gap-1 px-3 pt-2 border-b border-zinc-800">
        {(['dice', 'messages'] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 text-xs font-medium rounded-t transition-colors -mb-px border-b-2 ${
              tab === t
                ? 'text-zinc-200 border-indigo-500'
                : 'text-zinc-600 border-transparent hover:text-zinc-400'
            }`}
          >
            {t === 'dice' ? '🎲 骰子历史' : '📜 消息回溯'}
          </button>
        ))}
      </div>

      <div className="px-2 pb-2 pt-1">
        {loading && <div className="text-xs text-zinc-600 px-1 py-2 text-center">加载中...</div>}

        {/* 骰子历史 */}
        {tab === 'dice' && !loading && (
          <>
            {diceHistory.length === 0 && (
              <div className="text-xs text-zinc-700 px-1 py-3 text-center">本局暂无骰子记录</div>
            )}
            <div className="flex flex-col gap-1 max-h-60 overflow-y-auto">
              {diceHistory.map(d => (
                <div key={d.id} className="bg-zinc-800 rounded px-2 py-1.5 text-[10px]">
                  <div className="flex items-center gap-1.5">
                    <span className={`font-bold ${VERDICT_COLORS[d.verdict] ?? 'text-zinc-400'}`}>
                      {d.verdict.toUpperCase()}
                    </span>
                    <span className="text-zinc-500">净{d.net}</span>
                    <span className="text-zinc-600 ml-auto">{d.pool}d{d.threshold}+</span>
                  </div>
                  {d.reason && (
                    <div className="text-zinc-600 truncate mt-0.5">{d.reason}</div>
                  )}
                  <div className="text-zinc-700 mt-0.5">
                    [{d.rolls?.join?.(', ') ?? ''}]
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {/* 消息回溯 */}
        {tab === 'messages' && !loading && (
          <>
            {revertResult && (
              <div className={`text-xs px-2 py-1.5 mb-1 rounded ${
                revertResult.includes('成功') ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'
              }`}>
                {revertResult}
              </div>
            )}
            {messages.length === 0 && (
              <div className="text-xs text-zinc-700 px-1 py-3 text-center">暂无消息记录</div>
            )}
            <div className="flex flex-col gap-1 max-h-60 overflow-y-auto">
              {messages.map(m => (
                <div key={m.id} className="bg-zinc-800 rounded px-2 py-1.5 text-[10px] group">
                  <div className="flex items-center justify-between gap-1">
                    <span className={`font-medium ${
                      m.role === 'user' ? 'text-indigo-400' : m.role === 'assistant' ? 'text-green-400' : 'text-zinc-500'
                    }`}>
                      {m.role === 'user' ? '玩家' : m.role === 'assistant' ? 'DM' : '系统'}
                    </span>
                    <button
                      onClick={() => handleRevert(m.id)}
                      disabled={reverting === m.id}
                      className="opacity-0 group-hover:opacity-100 px-1.5 py-0.5 bg-orange-900/60 text-orange-400 rounded text-[10px] hover:bg-orange-800/60 transition-all disabled:opacity-30"
                      title="回溯到此消息之前"
                    >
                      {reverting === m.id ? '...' : '↩ 回溯'}
                    </button>
                  </div>
                  <div className="text-zinc-500 mt-0.5 leading-tight">
                    <span className="text-zinc-600 font-mono">T{m.turn_index ?? '?'}</span>
                    {m.part_ids && (
                      <span className="text-zinc-700 ml-1">
                        · {m.part_ids.split(',').length} parts
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default HistoryPanel
