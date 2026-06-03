import React, { useState } from 'react'
import { useCharacterStore } from '../../stores/character'

const ATTRS = [
  { key: 'strength',     label: 'STR' },
  { key: 'dexterity',    label: 'DEX' },
  { key: 'stamina',      label: 'STA' },
  { key: 'intelligence', label: 'INT' },
  { key: 'spirit',       label: 'SPI' },
  { key: 'charisma',     label: 'CHA' },
  { key: 'composure',    label: 'COM' },
]

const PARTS = [
  { key: 'head',      label: '头部' },
  { key: 'torso',     label: '躯干' },
  { key: 'left_arm',  label: '左臂' },
  { key: 'right_arm', label: '右臂' },
  { key: 'left_leg',  label: '左腿' },
  { key: 'right_leg', label: '右腿' },
]

const PART_STATUS_COLOR: Record<string, string> = {
  intact:   'bg-green-700',
  light:    'bg-yellow-600',
  heavy:    'bg-orange-600',
  crippled: 'bg-red-700',
  lost:     'bg-zinc-800',
}

function partStatus(hp: number, maxHp: number): string {
  if (hp <= 0) return 'lost'
  const pct = hp / maxHp
  if (pct > 0.75) return 'intact'
  if (pct > 0.5) return 'light'
  if (pct > 0.25) return 'heavy'
  return 'crippled'
}

export const CharacterPanel: React.FC = () => {
  const { character, loading } = useCharacterStore()
  const [collapsed, setCollapsed] = useState(false)

  if (loading) {
    return (
      <div className="text-xs px-3 py-4 space-y-2 animate-pulse">
        <div className="h-3 bg-zinc-800 rounded w-24" />
        <div className="h-3 bg-zinc-800 rounded w-16" />
        <div className="h-3 bg-zinc-800 rounded w-20" />
      </div>
    )
  }

  if (!character) {
    return (
      <div className="text-xs text-zinc-600 px-3 py-6 text-center leading-relaxed">
        暂无角色卡<br />
        <span className="text-zinc-700">发送首条消息后自动加载</span>
      </div>
    )
  }

  const identity = (character.identity as Record<string, unknown>) ?? character
  const name = (identity.name as string) ?? ''
  const attrs = (character.attributes as Record<string, Record<string, number>>) ?? {}
  const bodyParts = (character.body_parts as Record<string, Record<string, number>>) ?? {}
  const psych = (
    (character.psychology as Record<string, unknown>)?.state as Record<string, number>
  ) ?? {}
  const skills = (character.skills as Record<string, unknown>) ?? {}
  const inventory = (character.inventory as Array<Record<string, unknown>>) ?? []
  const meta = (character.meta as Record<string, unknown>) ?? {}

  return (
    <div className="text-xs">
      {/* 标题行 */}
      <button
        className="w-full flex items-center justify-between text-zinc-400 font-semibold text-xs uppercase tracking-wider px-3 py-2 hover:text-zinc-200"
        onClick={() => setCollapsed(!collapsed)}
      >
        <span>{name || '角色'}</span>
        <span>{collapsed ? '▸' : '▾'}</span>
      </button>

      {!collapsed && (
        <div className="px-3 pb-3 space-y-3">
          {/* 属性列表 */}
          <div className="space-y-1">
            {ATTRS.map(({ key, label }) => {
              const a = attrs[key] ?? { base: 1, equip: 0, status: 0, temp: 0 }
              const eff = (a.base ?? 1) + (a.equip ?? 0) + (a.status ?? 0) + (a.temp ?? 0)
              return (
                <div key={key} className="flex items-center gap-1.5">
                  <span className="w-7 text-zinc-500">{label}</span>
                  <div className="flex gap-0.5">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <span
                        key={i}
                        className={`w-2 h-2 rounded-sm ${i < eff ? 'bg-indigo-500' : 'bg-zinc-700'}`}
                      />
                    ))}
                  </div>
                  <span className="text-zinc-400">{eff}d</span>
                </div>
              )
            })}
          </div>

          {/* 部位HP */}
          {Object.keys(bodyParts).length > 0 && (
            <div>
              <div className="text-zinc-600 mb-1">身体部位</div>
              <div className="grid grid-cols-3 gap-1">
                {PARTS.map(({ key, label }) => {
                  const bp = bodyParts[key]
                  if (!bp) return null
                  const s = partStatus(bp.hp ?? bp.max_hp, bp.max_hp)
                  return (
                    <div key={key} className="flex items-center gap-1">
                      <span className={`w-1.5 h-1.5 rounded-full ${PART_STATUS_COLOR[s]}`} />
                      <span className="text-zinc-500">{label}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* 心理状态 */}
          {(psych.stress !== undefined || psych.morale !== undefined) && (
            <div className="space-y-1">
              <div className="text-zinc-600">心理状态</div>
              {[
                { key: 'stress', label: '压力', color: 'bg-red-600' },
                { key: 'morale', label: '士气', color: 'bg-blue-600' },
              ].map(({ key, label, color }) => {
                const val = (psych[key as keyof typeof psych] as number) ?? 0
                return (
                  <div key={key} className="flex items-center gap-1.5">
                    <span className="w-7 text-zinc-500">{label}</span>
                    <div className="flex-1 bg-zinc-800 rounded h-1.5">
                      <div
                        className={`h-1.5 rounded ${color}`}
                        style={{ width: `${Math.min(100, val)}%` }}
                      />
                    </div>
                    <span className="text-zinc-500 w-8 text-right">{val}%</span>
                  </div>
                )
              })}
            </div>
          )}

          {/* 技能 */}
          {Object.keys(skills).length > 0 && (
            <div>
              <div className="text-zinc-600 mb-1">技能</div>
              <div className="flex flex-wrap gap-1">
                {Object.entries(skills).slice(0, 10).map(([sk, val]) => (
                  <span
                    key={sk}
                    className="bg-zinc-800 px-1.5 py-0.5 rounded text-[9px] text-zinc-400"
                    title={`${sk}: ${String(val)}`}
                  >
                    {sk}{typeof val === 'number' ? ` ${val}` : ''}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* 物品栏（只展示前 5 项，超出折叠）*/}
          {inventory.length > 0 && (
            <div>
              <div className="text-zinc-600 mb-1">物品 ({inventory.length})</div>
              <div className="space-y-0.5">
                {inventory.slice(0, 5).map((item, i) => {
                  const itemName = (item.name as string) ?? (item.key as string) ?? `物品${i + 1}`
                  const count = (item.count as number) ?? 1
                  return (
                    <div key={i} className="flex items-center gap-1.5">
                      <span className="text-zinc-600">·</span>
                      <span className="text-zinc-400 truncate flex-1">{itemName}</span>
                      {count > 1 && <span className="text-zinc-600 flex-shrink-0">×{count}</span>}
                    </div>
                  )
                })}
                {inventory.length > 5 && (
                  <div className="text-zinc-700 text-[9px]">…还有 {inventory.length - 5} 项</div>
                )}
              </div>
            </div>
          )}

          {/* meta 额外字段（如 HP、MP 等自定义数值） */}
          {Object.keys(meta).length > 0 && (
            <div className="border-t border-zinc-800 pt-2 space-y-0.5">
              {Object.entries(meta).slice(0, 6).map(([k, v]) => (
                <div key={k} className="flex items-center gap-1.5">
                  <span className="text-zinc-600 truncate flex-1">{k}</span>
                  <span className="text-zinc-400 flex-shrink-0">{String(v)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
