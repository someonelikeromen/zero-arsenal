import React, { useState, useEffect, useCallback } from 'react'
import { api, DiceRollResult } from '../../lib/api'
import { useSessionStore } from '../../stores/session'
import { useDiceStore } from '../../stores/dice'

const ATTRS = ['STR', 'DEX', 'STA', 'INT', 'SPI', 'CHA', 'COM'] as const
const ATTR_MAP: Record<string, string> = {
  STR: 'strength', DEX: 'dexterity', STA: 'stamina',
  INT: 'intelligence', SPI: 'spirit', CHA: 'charisma', COM: 'composure',
}
const MODIFIERS = [-2, -1, 0, 1, 2] as const

const VERDICT_STYLE: Record<string, string> = {
  critical: 'text-yellow-400 border-yellow-800',
  success:  'text-green-400  border-green-800',
  failure:  'text-zinc-400   border-zinc-700',
  botch:    'text-red-400    border-red-900',
}

export const DicePanel: React.FC = () => {
  const { currentSessionId } = useSessionStore()
  const { history: storeHistory, addRoll } = useDiceStore()
  const [attr, setAttr] = useState<string>('DEX')
  const [mod, setMod] = useState(0)
  const [threshold, setThreshold] = useState(8)
  const [reason, setReason] = useState('')
  const [pool, setPool] = useState<number | ''>('')
  const [rolling, setRolling] = useState(false)

  // 初始化时从服务端加载骰子历史（补充 store 中尚无的历史记录）
  const loadServerHistory = useCallback(async () => {
    if (!currentSessionId) return
    try {
      const data = await api.getDiceHistory(currentSessionId, 20)
      if (Array.isArray(data)) {
        ;(data as DiceRollResult[]).forEach((r) => {
          addRoll({
            roll_id: r.roll_id ?? `hist-${Date.now()}`,
            pool: r.pool ?? 0,
            successes: r.successes ?? 0,
            outcome: (r.verdict as 'success' | 'failure' | 'critical') ?? 'failure',
            attribute: r.attribute ?? '',
            skill: r.skill,
            modifier: r.modifier,
            detail: r.rolls ?? [],
            created_at: Date.now(),
          })
        })
      }
    } catch { /* ignore */ }
  }, [currentSessionId, addRoll])

  useEffect(() => {
    loadServerHistory()
  }, [loadServerHistory])

  const roll = async () => {
    if (rolling) return
    setRolling(true)
    try {
      const req =
        pool !== ''
          ? { pool: Number(pool), modifier: mod, threshold, reason, session_id: currentSessionId ?? undefined }
          : { attribute: ATTR_MAP[attr], modifier: mod, threshold, reason, session_id: currentSessionId ?? undefined }
      const result = await api.rollDice(req)
      addRoll({
        roll_id: result.roll_id ?? `manual-${Date.now()}`,
        pool: result.pool ?? 0,
        successes: result.successes ?? 0,
        outcome: (result.verdict as 'success' | 'failure' | 'critical') ?? 'failure',
        attribute: result.attribute ?? '',
        skill: result.skill,
        modifier: result.modifier,
        detail: result.rolls ?? [],
        created_at: Date.now(),
      })
    } catch {
      // ignore
    } finally {
      setRolling(false)
    }
  }

  return (
    <div className="flex flex-col gap-3 p-3 text-xs">
      <div className="text-zinc-400 font-semibold text-xs uppercase tracking-wider">骰子</div>

      {/* 控制区 */}
      <div className="space-y-2">
        {/* 属性选择 */}
        <div className="flex flex-wrap gap-1">
          {ATTRS.map((a) => (
            <button
              key={a}
              onClick={() => { setAttr(a); setPool('') }}
              className={`px-1.5 py-0.5 rounded text-xs transition-colors ${
                attr === a && pool === '' ? 'bg-indigo-600 text-white' : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
              }`}
            >
              {a}
            </button>
          ))}
        </div>
        {/* 直接骰池 */}
        <div className="flex items-center gap-1">
          <span className="text-zinc-500 text-xs w-10">骰池:</span>
          <input
            type="number"
            min={0} max={20}
            value={pool}
            onChange={(e) => setPool(e.target.value === '' ? '' : Number(e.target.value))}
            placeholder="auto"
            className="w-14 bg-zinc-800 border border-zinc-700 rounded px-1.5 py-0.5 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500"
          />
        </div>
        {/* 修正值 */}
        <div className="flex items-center gap-1">
          <span className="text-zinc-500 text-xs w-10">修正:</span>
          {MODIFIERS.map((m) => (
            <button
              key={m}
              onClick={() => setMod(m)}
              className={`w-7 py-0.5 rounded text-xs transition-colors ${
                mod === m ? 'bg-indigo-600 text-white' : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
              }`}
            >
              {m >= 0 ? `+${m}` : m}
            </button>
          ))}
        </div>
        {/* 成功阈值（threshold） */}
        <div className="flex items-center gap-1">
          <span className="text-zinc-500 text-xs w-10">阈值:</span>
          <input
            type="number"
            min={6} max={10}
            value={threshold}
            onChange={(e) => setThreshold(Math.min(10, Math.max(6, Number(e.target.value))))}
            className="w-14 bg-zinc-800 border border-zinc-700 rounded px-1.5 py-0.5 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500"
          />
          <span className="text-zinc-600 text-[10px]">(6~10, 默认8)</span>
        </div>
        {/* 理由 */}
        <input
          type="text"
          placeholder="判定原因（可选）"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500 placeholder-zinc-600"
        />
        <button
          onClick={roll}
          disabled={rolling}
          className="w-full py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white rounded text-xs font-medium transition-colors"
        >
          {rolling ? '投掷中...' : '投掷'}
        </button>
      </div>

      {/* 历史（服务端持久化） */}
      <div className="space-y-2 mt-1">
        <div className="flex items-center justify-between">
          <span className="text-zinc-600 text-xs">历史记录</span>
          <button
            onClick={loadServerHistory}
            className="text-zinc-600 hover:text-zinc-400 text-[10px] transition-colors"
          >
            ↻ 刷新
          </button>
        </div>
        {storeHistory.slice(0, 8).map((r, i) => (
          <DiceHistoryItem key={r.roll_id ?? i} result={{
            roll_id: r.roll_id,
            pool: r.pool,
            threshold: 8,
            rolls: r.detail,
            successes: r.successes,
            ones: 0,
            net: r.successes,
            result: r.outcome,
            botch: r.outcome === 'failure' && r.successes === 0,
            verdict: r.outcome as DiceRollResult['verdict'],
            narrative_hint: '',
            attribute: r.attribute,
            skill: r.skill,
            reason: '',
            pool_formula: `${r.pool}d10`,
            timestamp: new Date(r.created_at).toISOString(),
            modifier: r.modifier,
          }} />
        ))}
        {storeHistory.length === 0 && (
          <div className="text-zinc-700 text-[10px] text-center py-2">暂无骰子记录</div>
        )}
      </div>
    </div>
  )
}

const DiceHistoryItem: React.FC<{ result: DiceRollResult }> = ({ result: r }) => {
  const style = VERDICT_STYLE[r.verdict] ?? VERDICT_STYLE.failure
  return (
    <div className={`border rounded p-2 space-y-1 ${style}`}>
      <div className="flex justify-between items-center">
        <span className="font-mono">{r.pool_formula || `${r.pool}d`}</span>
        <span className="font-semibold">{r.result}</span>
      </div>
      <div className="flex flex-wrap gap-1">
        {r.rolls.map((v, i) => (
          <span
            key={i}
            className={`w-5 h-5 rounded flex items-center justify-center text-xs font-bold
              ${v >= r.threshold ? 'bg-green-900 text-green-300' : ''}
              ${v === 1 ? 'bg-red-900 text-red-300' : ''}
              ${v < r.threshold && v !== 1 ? 'bg-zinc-800 text-zinc-500' : ''}
            `}
          >
            {v}
          </span>
        ))}
      </div>
      <div className="text-zinc-500 text-xs">净 {r.net} | {r.ones}抵消</div>
    </div>
  )
}
