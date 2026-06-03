/**
 * CombatPanel — 战斗引擎面板
 * 部位 HP 条 + 施加伤害/治疗（POST /engine/combat）。
 * 角色卡 attributes.hp.parts 结构与后端 CombatEngine 对齐。
 */
import React, { useState, useCallback } from 'react'
import { api } from '../../lib/api'
import { notify } from '../../stores/ui'
import { useCharacterStore } from '../../stores/character'

interface Props {
  sessionId: string
}

const PARTS: { key: string; label: string }[] = [
  { key: 'head', label: '头部' },
  { key: 'torso', label: '躯干' },
  { key: 'left_arm', label: '左臂' },
  { key: 'right_arm', label: '右臂' },
  { key: 'left_leg', label: '左腿' },
  { key: 'right_leg', label: '右腿' },
]

const STATUS_LABELS: Record<string, string> = {
  bleeding: '出血', fractured: '骨折', stunned: '眩晕',
  paralyzed: '麻痹', burned: '灼烧', poisoned: '中毒',
}

type PartsState = Record<string, { current: number; max: number; status_effects?: string[] }>

export const CombatPanel: React.FC<Props> = ({ sessionId }) => {
  const character = useCharacterStore(s => s.character)
  const loadCharacter = useCharacterStore(s => s.loadCharacter)

  const initParts = (character as { attributes?: { hp?: { parts?: PartsState } } } | null)
    ?.attributes?.hp?.parts ?? {}
  const [parts, setParts] = useState<PartsState>(initParts)
  const [action, setAction] = useState<'damage' | 'heal'>('damage')
  const [amount, setAmount] = useState(20)
  const [part, setPart] = useState('torso')
  const [damageType, setDamageType] = useState('physical')
  const [crit, setCrit] = useState(false)
  const [busy, setBusy] = useState(false)
  const [lastHint, setLastHint] = useState('')

  const apply = useCallback(async () => {
    setBusy(true)
    try {
      const res = await api.combatAction({
        session_id: sessionId,
        action,
        amount,
        part,
        damage_type: damageType,
        is_critical: action === 'damage' ? (crit || null) : undefined,
      })
      setParts(res.parts)
      const hint = (res.result.narrative_hint as string) ?? ''
      setLastHint(hint)
      notify.success(`${action === 'heal' ? '治疗' : '伤害'}已结算 ${hint}`)
      loadCharacter(sessionId)
    } catch (e) {
      notify.error(`战斗结算失败：${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }, [sessionId, action, amount, part, damageType, crit, loadCharacter])

  return (
    <div className="flex flex-col text-xs bg-zinc-900 rounded-lg border border-zinc-800">
      <div className="px-3 py-2 border-b border-zinc-800 text-zinc-400 font-semibold uppercase tracking-wider">
        ⚔ 战斗引擎
      </div>

      {/* 部位 HP 条 */}
      <div className="px-3 py-2 space-y-1.5">
        {PARTS.map(({ key, label }) => {
          const node = parts[key]
          const cur = node?.current ?? null
          const max = node?.max ?? 100
          const ratio = cur != null ? Math.max(0, cur / max) : 1
          const color = ratio > 0.5 ? 'bg-emerald-600' : ratio > 0.25 ? 'bg-amber-500' : 'bg-red-600'
          const effects = node?.status_effects ?? []
          return (
            <div key={key}>
              <div className="flex items-center justify-between text-[10px] mb-0.5">
                <span className="text-zinc-400">{label}</span>
                <span className="text-zinc-500">{cur != null ? `${cur}/${max}` : '—'}</span>
              </div>
              <div className="h-1.5 bg-zinc-800 rounded overflow-hidden">
                <div className={`h-full ${color}`} style={{ width: `${ratio * 100}%` }} />
              </div>
              {effects.length > 0 && (
                <div className="flex gap-1 mt-0.5 flex-wrap">
                  {effects.map((ef, i) => (
                    <span key={i} className="text-[9px] bg-red-900/40 text-red-400 px-1 rounded">
                      {STATUS_LABELS[ef] ?? ef}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* 控制区 */}
      <div className="px-3 py-2 border-t border-zinc-800 space-y-2">
        <div className="flex gap-1">
          {(['damage', 'heal'] as const).map(a => (
            <button key={a} onClick={() => setAction(a)}
              className={`flex-1 text-[10px] py-1 rounded ${action === a ? 'bg-indigo-700 text-white' : 'bg-zinc-800 text-zinc-400'}`}>
              {a === 'damage' ? '造成伤害' : '治疗'}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className="block">
            <span className="text-[10px] text-zinc-500">部位</span>
            <select value={part} onChange={e => setPart(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-1.5 py-1 text-xs text-zinc-200">
              {PARTS.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-[10px] text-zinc-500">数值</span>
            <input type="number" value={amount} min={0}
              onChange={e => setAmount(Number(e.target.value))}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-1.5 py-1 text-xs text-zinc-200" />
          </label>
        </div>
        {action === 'damage' && (
          <div className="flex items-center gap-2">
            <select value={damageType} onChange={e => setDamageType(e.target.value)}
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-1.5 py-1 text-xs text-zinc-200">
              <option value="physical">物理</option>
              <option value="qi">气功</option>
              <option value="magic">魔法</option>
              <option value="tech">科技</option>
            </select>
            <label className="flex items-center gap-1 text-[10px] text-zinc-400">
              <input type="checkbox" checked={crit} onChange={e => setCrit(e.target.checked)} />
              暴击
            </label>
          </div>
        )}
        <button onClick={apply} disabled={busy}
          className="w-full py-1.5 rounded bg-indigo-700 hover:bg-indigo-600 text-white text-xs disabled:opacity-50">
          {busy ? '结算中...' : '结算'}
        </button>
        {lastHint && <div className="text-[10px] text-zinc-500">{lastHint}</div>}
      </div>
    </div>
  )
}

export default CombatPanel
