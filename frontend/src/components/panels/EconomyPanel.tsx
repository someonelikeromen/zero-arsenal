/**
 * EconomyPanel — 会话经济系统面板
 * 展示货币余额 / 徽章 / 战斗积分 + 按 world_plugin 对应的卡池或商城目录。
 * 数据来自 GET /engine/economy/{sessionId}。
 */
import React, { useEffect, useState, useCallback } from 'react'
import { api } from '../../lib/api'
import { notify } from '../../stores/ui'

interface Props {
  sessionId: string
}

interface Pool {
  id: string
  display_name?: string
  cost_per_draw?: number
  description?: string
}

type Economy = Awaited<ReturnType<typeof api.getEconomy>>

export const EconomyPanel: React.FC<Props> = ({ sessionId }) => {
  const [data, setData] = useState<Economy | null>(null)
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState<'pools' | 'shop'>('pools')

  const load = useCallback(() => {
    setLoading(true)
    api.getEconomy(sessionId)
      .then(d => {
        setData(d)
        setView(d.pools.length > 0 ? 'pools' : 'shop')
      })
      .catch(e => notify.error(`加载经济数据失败：${(e as Error).message}`))
      .finally(() => setLoading(false))
  }, [sessionId])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="text-xs text-zinc-600 px-3 py-3">加载中...</div>
  if (!data) return <div className="text-xs text-zinc-600 px-3 py-3">暂无经济数据</div>

  if (!data.has_economy) {
    return (
      <div className="text-xs text-zinc-600 px-3 py-4 text-center">
        当前世界（{data.world_plugin}）未配置经济系统。
      </div>
    )
  }

  const shopItems = Array.isArray(data.shop) ? data.shop as Record<string, unknown>[] : []

  return (
    <div className="flex flex-col text-xs bg-zinc-900 rounded-lg border border-zinc-800">
      {/* 余额栏 */}
      <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between">
        <div>
          <div className="text-zinc-500 text-[10px]">{data.currency}</div>
          <div className="text-amber-400 font-bold text-base">{data.balance.toLocaleString()}</div>
        </div>
        <div className="text-right text-[10px] text-zinc-500 space-y-0.5">
          <div>🎖 徽章 ×{data.badges.length}</div>
          <div>⚔ 战斗积分 {data.battle_points}</div>
          <button onClick={load} className="text-indigo-400 hover:text-indigo-300">刷新</button>
        </div>
      </div>

      {/* 视图切换 */}
      <div className="flex gap-1 px-2 pt-2">
        {data.pools.length > 0 && (
          <button onClick={() => setView('pools')}
            className={`text-[10px] px-2 py-0.5 rounded ${view === 'pools' ? 'bg-indigo-700 text-white' : 'bg-zinc-800 text-zinc-400'}`}>
            卡池 ({data.pools.length})
          </button>
        )}
        {shopItems.length > 0 && (
          <button onClick={() => setView('shop')}
            className={`text-[10px] px-2 py-0.5 rounded ${view === 'shop' ? 'bg-indigo-700 text-white' : 'bg-zinc-800 text-zinc-400'}`}>
            商城 ({shopItems.length})
          </button>
        )}
      </div>

      <div className="px-2 py-2 space-y-1.5 max-h-72 overflow-y-auto">
        {view === 'pools' && data.pools.map((p: Pool) => {
          const affordable = (p.cost_per_draw ?? 0) <= data.balance
          return (
            <div key={p.id} className="bg-zinc-800 rounded px-2 py-1.5">
              <div className="flex items-center justify-between">
                <span className="text-zinc-200 font-medium">{p.display_name ?? p.id}</span>
                <span className={affordable ? 'text-amber-400' : 'text-zinc-600'}>
                  {p.cost_per_draw?.toLocaleString()} /抽
                </span>
              </div>
              {p.description && <p className="text-[10px] text-zinc-500 mt-0.5 leading-relaxed">{p.description}</p>}
              <div className="text-[9px] text-zinc-600 mt-1">
                抽卡请在对话中向 DM 描述（如「我用综合池抽一次」），由抽卡引擎结算
              </div>
            </div>
          )
        })}

        {view === 'shop' && shopItems.map((it, i) => (
          <div key={(it.id as string) ?? i} className="bg-zinc-800 rounded px-2 py-1.5">
            <div className="flex items-center justify-between">
              <span className="text-zinc-200 font-medium">{String(it.name ?? it.title ?? it.id ?? `商品${i + 1}`)}</span>
              {it.price != null && <span className="text-amber-400">{String(it.price)}</span>}
            </div>
            {it.description != null && (
              <p className="text-[10px] text-zinc-500 mt-0.5 leading-relaxed line-clamp-2">{String(it.description)}</p>
            )}
          </div>
        ))}

        {view === 'pools' && data.pools.length === 0 && (
          <div className="text-zinc-600 text-center py-3">该世界无卡池</div>
        )}
        {view === 'shop' && shopItems.length === 0 && (
          <div className="text-zinc-600 text-center py-3">该世界无商城</div>
        )}
      </div>
    </div>
  )
}

export default EconomyPanel
