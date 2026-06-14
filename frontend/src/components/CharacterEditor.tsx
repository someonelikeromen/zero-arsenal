/**
 * CharacterEditor — 角色 v4 结构化编辑器（Phase 2B）。
 * 复用于创建向导 Step 4 预览编辑 + 人物模板列表的「编辑」入口（Phase 2C）。
 *
 * 设计原则：优化 ≠ 简化。字段保持完整（含 psyche_model 五要素），
 * 通过 tooltip + 分组 + 专家 JSON 模式提供引导，而非削减字段。
 */
import { useState } from 'react'

type Dict = Record<string, unknown>

const ATTR_LABELS: Record<string, string> = {
  strength: '力量', dexterity: '敏捷', intelligence: '智力',
  will: '意志', empathy: '共情', stamina: '体质', spirit: '精神',
  charisma: '魅力', composure: '沉着',
}

const OCEAN_LABELS: Array<[string, string]> = [
  ['openness', '开放性'],
  ['conscientiousness', '尽责性'],
  ['extraversion', '外向性'],
  ['agreeableness', '宜人性'],
  ['neuroticism', '神经质'],
]

const BODY_PART_LABELS: Array<[string, string]> = [
  ['head', '头部'],
  ['chest', '躯干'],
  ['arms', '手臂'],
  ['legs', '腿部'],
]

const EMOTION_STATES = [
  'calm', 'anxious', 'angry', 'joyful', 'fearful',
  'grieving', 'determined', 'numb', 'elated', 'despair',
]

const PSYCHE_TOOLTIPS: Record<string, string> = {
  core_values: '核心价值观（≥2 条）—— 驱动角色一切行为的内核，来源于 05-character-consistency 规则',
  knows: '角色「知道」的事项 —— 用于约束叙事，防止全知视角',
  blind_spots: '角色「不知道」的盲区 —— NPC/主角不应表现出对盲区信息的了解',
  capability_cap: '能力上限 —— 战斗/技术/社交/特殊感知各维度的天花板，防止战力膨胀',
  behavior_patterns: '典型行为模式 —— 1-2 句概括角色的惯常反应方式',
  emotional_triggers: '情绪触发点 —— 什么情况下角色会脱离常规、进入爆发/亢奋/极度理智态',
}

function InfoLabel({ text, tip }: { text: string; tip?: string }) {
  return (
    <label className="text-xs text-zinc-400 flex items-center gap-1 mb-1">
      {text}
      {tip && <span className="text-zinc-600 cursor-help" title={tip}>ⓘ</span>}
    </label>
  )
}

/** 通用 chip 列表编辑（字符串数组） */
function ChipListEditor({ items, onChange, placeholder }: {
  items: string[]; onChange: (next: string[]) => void; placeholder: string
}) {
  const [draft, setDraft] = useState('')
  const add = () => {
    const v = draft.trim()
    if (!v) return
    onChange([...items, v])
    setDraft('')
  }
  return (
    <div>
      <div className="flex flex-wrap gap-1 mb-1">
        {items.map((it, i) => (
          <span key={i} className="inline-flex items-center gap-1 bg-zinc-700 text-zinc-200 text-xs px-2 py-0.5 rounded">
            {it}
            <button onClick={() => onChange(items.filter((_, idx) => idx !== i))}
              className="text-zinc-400 hover:text-red-400">×</button>
          </span>
        ))}
        {items.length === 0 && <span className="text-xs text-zinc-600">（空）</span>}
      </div>
      <div className="flex gap-1">
        <input value={draft} onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
          className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none"
          placeholder={placeholder} />
        <button onClick={add} className="text-xs bg-zinc-700 hover:bg-zinc-600 px-2 rounded">+</button>
      </div>
    </div>
  )
}

export function CharacterEditor({ data, onChange }: { data: Dict; onChange: (d: Dict) => void }) {
  const [expert, setExpert] = useState(false)
  const [jsonDraft, setJsonDraft] = useState('')
  const [jsonError, setJsonError] = useState('')

  // 浅层 setter：返回新对象，触发上层重渲染
  const set = (key: string, val: unknown) => onChange({ ...data, [key]: val })

  const psyche = (data.psyche_model as Dict) || {}
  const setPsyche = (key: string, val: unknown) =>
    set('psyche_model', { ...psyche, [key]: val })
  const knowledge = (psyche.knowledge_scope as Dict) || {}
  const setKnowledge = (key: string, val: unknown) =>
    setPsyche('knowledge_scope', { ...knowledge, [key]: val })
  const cap = (psyche.capability_cap as Dict) || {}
  const setCap = (key: string, val: unknown) =>
    setPsyche('capability_cap', { ...cap, [key]: val })

  const attrs = (data.attributes as Record<string, unknown>) || {}
  // 只取数值类型属性，过滤掉 schema/values 等元数据字段
  const numericAttrs = Object.fromEntries(
    Object.entries(attrs).filter(([, v]) => typeof v === 'number')
  ) as Record<string, number>
  const setAttr = (k: string, delta: number) => {
    const next = Math.max(1, Math.min(10, (numericAttrs[k] ?? 1) + delta))
    set('attributes', { ...attrs, [k]: next, values: { ...((attrs.values as Record<string, number>) || {}), [k]: next } })
  }

  const skills = (data.skills as Record<string, number>) || {}
  const inventory = (data.inventory as Array<{ name: string; quantity?: number }>) || []

  // ── v4 结构字段（identity / psychology(OCEAN) / economy / energy_pools / body_parts / loadout / achievements）──
  const identity = (data.identity as Dict) || {}
  const setIdentity = (k: string, v: unknown) => set('identity', { ...identity, [k]: v })

  const psychology = (data.psychology as Dict) || {}
  const ocean = (psychology.ocean as Record<string, number>) || {}
  const setPsychology = (k: string, v: unknown) => set('psychology', { ...psychology, [k]: v })
  const setOcean = (k: string, v: number) =>
    set('psychology', { ...psychology, ocean: { ...ocean, [k]: v } })

  const economy = (data.economy as Dict) || {}
  const setEconomy = (k: string, v: unknown) => set('economy', { ...economy, [k]: v })

  type EnergyPool = { name?: string; current?: number; max?: number; type?: string; regen_per_turn?: number }
  const energyPools = (data.energy_pools as EnergyPool[]) || []
  const setPools = (next: EnergyPool[]) => set('energy_pools', next)

  const physState = (data.physical_state as Dict) || {}
  const bodyParts = (physState.body_parts as Record<string, { hp_ratio?: number }>) || {}
  const setBodyPart = (part: string, ratio: number) =>
    set('physical_state', {
      ...physState,
      body_parts: { ...bodyParts, [part]: { ...(bodyParts[part] || {}), hp_ratio: ratio } },
    })

  const loadout = (data.loadout as Dict) || {}
  const equipped = (loadout.equipped as Array<{ name?: string }>) || []

  type Achievement = { id?: string; name?: string; description?: string }
  const achievements = (data.achievements as Achievement[]) || []
  const setAchievements = (next: Achievement[]) => set('achievements', next)

  const [newSkill, setNewSkill] = useState('')
  const [newItem, setNewItem] = useState('')
  const [newPool, setNewPool] = useState('')
  const [newAch, setNewAch] = useState('')

  // 专家模式：直接编辑完整 JSON
  const enterExpert = () => {
    setJsonDraft(JSON.stringify(data, null, 2))
    setJsonError('')
    setExpert(true)
  }
  const applyExpert = () => {
    try {
      const parsed = JSON.parse(jsonDraft)
      onChange(parsed)
      setExpert(false)
      setJsonError('')
    } catch (e) {
      setJsonError(`JSON 解析失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  if (expert) {
    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-zinc-300">专家模式（完整 data_json）</span>
          <button onClick={() => setExpert(false)} className="text-xs text-zinc-400 hover:text-zinc-200">← 返回结构化编辑</button>
        </div>
        <textarea value={jsonDraft} onChange={e => setJsonDraft(e.target.value)} rows={16}
          className="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-2 text-xs font-mono resize-none focus:outline-none" />
        {jsonError && <p className="text-xs text-red-400">{jsonError}</p>}
        <button onClick={applyExpert} className="w-full bg-indigo-600 hover:bg-indigo-500 text-white py-1.5 rounded text-sm">应用 JSON</button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <input value={(data.name as string) || ''} onChange={e => set('name', e.target.value)}
          className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-sm font-medium focus:outline-none"
          placeholder="角色名" />
        <button onClick={enterExpert} className="text-xs text-indigo-400 hover:text-indigo-300">专家模式 ⚙</button>
      </div>

      {/* 属性 ± 微调 */}
      <div>
        <InfoLabel text="属性（1-10）" tip="点 ± 微调，范围限制在 1-10" />
        <div className="grid grid-cols-5 gap-1">
          {Object.entries(numericAttrs).map(([k, v]) => (
            <div key={k} className="bg-zinc-800 rounded p-1.5 text-center">
              <div className="flex items-center justify-center gap-1">
                <button onClick={() => setAttr(k, -1)} className="text-zinc-500 hover:text-zinc-200 text-xs">−</button>
                <span className="text-base font-bold text-indigo-300 w-5">{v}</span>
                <button onClick={() => setAttr(k, +1)} className="text-zinc-500 hover:text-zinc-200 text-xs">+</button>
              </div>
              <div className="text-[10px] text-zinc-500">{ATTR_LABELS[k] || k.slice(0, 3)}</div>
            </div>
          ))}
        </div>
      </div>

      {/* psyche_model 结构化编辑 */}
      <div className="space-y-3 border border-zinc-800 rounded p-3">
        <span className="text-xs font-medium text-zinc-300">心理模型 psyche_model</span>
        <div>
          <InfoLabel text="核心价值观 core_values" tip={PSYCHE_TOOLTIPS.core_values} />
          <ChipListEditor items={(psyche.core_values as string[]) || []}
            onChange={v => setPsyche('core_values', v)} placeholder="新增价值观，回车确认" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <InfoLabel text="已知 knows" tip={PSYCHE_TOOLTIPS.knows} />
            <ChipListEditor items={(knowledge.knows as string[]) || []}
              onChange={v => setKnowledge('knows', v)} placeholder="已知事项" />
          </div>
          <div>
            <InfoLabel text="盲区 blind_spots" tip={PSYCHE_TOOLTIPS.blind_spots} />
            <ChipListEditor items={(knowledge.blind_spots as string[]) || []}
              onChange={v => setKnowledge('blind_spots', v)} placeholder="不知道的事" />
          </div>
        </div>
        <div>
          <InfoLabel text="能力上限 capability_cap" tip={PSYCHE_TOOLTIPS.capability_cap} />
          <div className="grid grid-cols-2 gap-2">
            {(['combat', 'tech', 'social', 'special_sense'] as const).map(key => (
              <input key={key} value={(cap[key] as string) || ''} onChange={e => setCap(key, e.target.value)}
                className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none"
                placeholder={key} />
            ))}
          </div>
        </div>
        <div>
          <InfoLabel text="行为模式 behavior_patterns" tip={PSYCHE_TOOLTIPS.behavior_patterns} />
          <textarea value={(psyche.behavior_patterns as string) || ''} onChange={e => setPsyche('behavior_patterns', e.target.value)} rows={2}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs resize-none focus:outline-none"
            placeholder="1-2 句典型行为模式" />
        </div>
        <div>
          <InfoLabel text="情绪触发点 emotional_triggers" tip={PSYCHE_TOOLTIPS.emotional_triggers} />
          <textarea value={(psyche.emotional_triggers as string) || ''} onChange={e => setPsyche('emotional_triggers', e.target.value)} rows={2}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs resize-none focus:outline-none"
            placeholder="什么情况下脱离常规反应" />
        </div>
      </div>

      {/* identity 身份信息（v4） */}
      <div className="space-y-2 border border-zinc-800 rounded p-3">
        <span className="text-xs font-medium text-zinc-300">身份 identity</span>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <InfoLabel text="性别 gender" />
            <select value={(identity.gender as string) || 'unknown'} onChange={e => setIdentity('gender', e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none">
              {['male', 'female', 'other', 'unknown'].map(g => <option key={g} value={g}>{g}</option>)}
            </select>
          </div>
          <div>
            <InfoLabel text="年龄 age" />
            <input value={(identity.age as string | number) ?? ''} onChange={e => setIdentity('age', e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none"
              placeholder="如：约17岁" />
          </div>
        </div>
        <div>
          <InfoLabel text="别名 aliases" />
          <ChipListEditor items={(identity.aliases as string[]) || []}
            onChange={v => setIdentity('aliases', v)} placeholder="新增别名，回车确认" />
        </div>
      </div>

      {/* psychology OCEAN 五维 + 状态（v4） */}
      <div className="space-y-2 border border-zinc-800 rounded p-3">
        <span className="text-xs font-medium text-zinc-300">五大人格 psychology.ocean（0-100）</span>
        <div className="space-y-1.5">
          {OCEAN_LABELS.map(([key, label]) => (
            <div key={key} className="flex items-center gap-2">
              <span className="text-[11px] text-zinc-400 w-14 shrink-0">{label}</span>
              <input type="range" min={0} max={100} value={ocean[key] ?? 50}
                onChange={e => setOcean(key, Number(e.target.value))}
                className="flex-1 accent-indigo-500" />
              <span className="text-xs text-indigo-300 w-8 text-right">{ocean[key] ?? 50}</span>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2 pt-1">
          <div>
            <InfoLabel text="情绪状态 emotion_state" />
            <select value={(psychology.emotion_state as string) || 'calm'} onChange={e => setPsychology('emotion_state', e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none">
              {EMOTION_STATES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <InfoLabel text="压力 stress（0-100）" />
            <input type="number" min={0} max={100} value={(psychology.stress as number) ?? 0}
              onChange={e => setPsychology('stress', Number(e.target.value))}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none" />
          </div>
        </div>
      </div>

      {/* 身体部位 HP（v4 四部位 hp_ratio） */}
      <div className="space-y-2 border border-zinc-800 rounded p-3">
        <span className="text-xs font-medium text-zinc-300">身体部位 HP（hp_ratio 0-1）</span>
        <div className="grid grid-cols-2 gap-2">
          {BODY_PART_LABELS.map(([key, label]) => {
            const ratio = bodyParts[key]?.hp_ratio ?? 1
            return (
              <div key={key} className="flex items-center gap-2">
                <span className="text-[11px] text-zinc-400 w-10 shrink-0">{label}</span>
                <input type="range" min={0} max={100} value={Math.round(ratio * 100)}
                  onChange={e => setBodyPart(key, Number(e.target.value) / 100)}
                  className="flex-1 accent-rose-500" />
                <span className="text-xs text-rose-300 w-9 text-right">{Math.round(ratio * 100)}%</span>
              </div>
            )
          })}
        </div>
      </div>

      {/* economy 经济（points/badges/tier） */}
      <div className="space-y-2 border border-zinc-800 rounded p-3">
        <span className="text-xs font-medium text-zinc-300">经济 economy</span>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <InfoLabel text="点数 points" />
            <input type="number" min={0} value={(economy.points as number) ?? 0}
              onChange={e => setEconomy('points', Number(e.target.value))}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none" />
          </div>
          <div>
            <InfoLabel text="徽章 badges" />
            <input type="number" min={0} value={(economy.badges as number) ?? 0}
              onChange={e => setEconomy('badges', Number(e.target.value))}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none" />
          </div>
          <div>
            <InfoLabel text="星级 tier（0-10）" />
            <input type="number" min={0} max={10} value={(economy.tier as number) ?? 0}
              onChange={e => setEconomy('tier', Number(e.target.value))}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none" />
          </div>
          <div>
            <InfoLabel text="子段位 tier_sub" />
            <select value={(economy.tier_sub as string) || ''} onChange={e => setEconomy('tier_sub', e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none">
              {['', 'L', 'M', 'U'].map(s => <option key={s} value={s}>{s || '—'}</option>)}
            </select>
          </div>
        </div>
      </div>

      {/* energy_pools 能量池（v4） */}
      <div className="space-y-2 border border-zinc-800 rounded p-3">
        <span className="text-xs font-medium text-zinc-300">能量池 energy_pools</span>
        <div className="space-y-1.5">
          {energyPools.map((p, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <input value={p.name || ''} onChange={e => setPools(energyPools.map((x, idx) => idx === i ? { ...x, name: e.target.value } : x))}
                className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none" placeholder="名称" />
              <input type="number" value={p.current ?? 0} onChange={e => setPools(energyPools.map((x, idx) => idx === i ? { ...x, current: Number(e.target.value) } : x))}
                className="w-16 bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none" placeholder="当前" />
              <span className="text-zinc-500 text-xs">/</span>
              <input type="number" value={p.max ?? 0} onChange={e => setPools(energyPools.map((x, idx) => idx === i ? { ...x, max: Number(e.target.value) } : x))}
                className="w-16 bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none" placeholder="上限" />
              <button onClick={() => setPools(energyPools.filter((_, idx) => idx !== i))}
                className="text-zinc-400 hover:text-red-400 text-xs">×</button>
            </div>
          ))}
          {energyPools.length === 0 && <span className="text-xs text-zinc-600">（空）</span>}
        </div>
        <div className="flex gap-1">
          <input value={newPool} onChange={e => setNewPool(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && newPool.trim()) { e.preventDefault(); setPools([...energyPools, { name: newPool.trim(), current: 100, max: 100, type: 'custom', regen_per_turn: 0 }]); setNewPool('') } }}
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none"
            placeholder="新增能量池（如：内力/法力），回车确认" />
          <button onClick={() => { if (newPool.trim()) { setPools([...energyPools, { name: newPool.trim(), current: 100, max: 100, type: 'custom', regen_per_turn: 0 }]); setNewPool('') } }}
            className="text-xs bg-zinc-700 hover:bg-zinc-600 px-2 rounded">+</button>
        </div>
      </div>

      {/* loadout 装备配置（v4，已装备列表只读统计 + 删除） */}
      <div className="space-y-2 border border-zinc-800 rounded p-3">
        <span className="text-xs font-medium text-zinc-300">装备配置 loadout.equipped（{equipped.length}）</span>
        <div className="flex flex-wrap gap-1">
          {equipped.map((it, i) => (
            <span key={i} className="inline-flex items-center gap-1 bg-zinc-800 text-zinc-300 text-xs px-2 py-0.5 rounded">
              {it.name || '未命名装备'}
              <button onClick={() => set('loadout', { ...loadout, equipped: equipped.filter((_, idx) => idx !== i) })}
                className="text-zinc-400 hover:text-red-400">×</button>
            </span>
          ))}
          {equipped.length === 0 && <span className="text-xs text-zinc-600">（空，可在道具栏管理普通物品）</span>}
        </div>
      </div>

      {/* achievements 成就（v4） */}
      <div className="space-y-2 border border-zinc-800 rounded p-3">
        <span className="text-xs font-medium text-zinc-300">成就 achievements</span>
        <div className="flex flex-wrap gap-1 mb-1">
          {achievements.map((a, i) => (
            <span key={i} className="inline-flex items-center gap-1 bg-zinc-800 text-amber-300 text-xs px-2 py-0.5 rounded">
              {a.name || '未命名成就'}
              <button onClick={() => setAchievements(achievements.filter((_, idx) => idx !== i))}
                className="text-zinc-400 hover:text-red-400">×</button>
            </span>
          ))}
          {achievements.length === 0 && <span className="text-xs text-zinc-600">（空）</span>}
        </div>
        <div className="flex gap-1">
          <input value={newAch} onChange={e => setNewAch(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && newAch.trim()) { e.preventDefault(); setAchievements([...achievements, { name: newAch.trim() }]); setNewAch('') } }}
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none"
            placeholder="新增成就，回车确认" />
          <button onClick={() => { if (newAch.trim()) { setAchievements([...achievements, { name: newAch.trim() }]); setNewAch('') } }}
            className="text-xs bg-zinc-700 hover:bg-zinc-600 px-2 rounded">+</button>
        </div>
      </div>

      {/* 技能增删 */}
      <div>
        <InfoLabel text="技能" />
        <div className="flex flex-wrap gap-1 mb-1">
          {Object.entries(skills).map(([k, v]) => (
            <span key={k} className="inline-flex items-center gap-1 bg-zinc-800 text-zinc-300 text-xs px-2 py-0.5 rounded">
              {k}
              <button onClick={() => set('skills', { ...skills, [k]: Math.max(0, (v ?? 0) - 1) })}
                className="text-zinc-500 hover:text-zinc-200">−</button>
              <span className="text-indigo-300">{v}</span>
              <button onClick={() => set('skills', { ...skills, [k]: (v ?? 0) + 1 })}
                className="text-zinc-500 hover:text-zinc-200">+</button>
              <button onClick={() => { const next = { ...skills }; delete next[k]; set('skills', next) }}
                className="text-zinc-400 hover:text-red-400 ml-0.5">×</button>
            </span>
          ))}
          {Object.keys(skills).length === 0 && <span className="text-xs text-zinc-600">（空）</span>}
        </div>
        <div className="flex gap-1">
          <input value={newSkill} onChange={e => setNewSkill(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && newSkill.trim()) { e.preventDefault(); set('skills', { ...skills, [newSkill.trim()]: 1 }); setNewSkill('') } }}
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none"
            placeholder="新增技能，回车确认（初始值 1）" />
          <button onClick={() => { if (newSkill.trim()) { set('skills', { ...skills, [newSkill.trim()]: 1 }); setNewSkill('') } }}
            className="text-xs bg-zinc-700 hover:bg-zinc-600 px-2 rounded">+</button>
        </div>
      </div>

      {/* 物品增删 */}
      <div>
        <InfoLabel text="道具" />
        <div className="flex flex-wrap gap-1 mb-1">
          {inventory.map((it, i) => (
            <span key={i} className="inline-flex items-center gap-1 bg-zinc-800 text-zinc-300 text-xs px-2 py-0.5 rounded">
              {it.name}{it.quantity && it.quantity > 1 ? ` ×${it.quantity}` : ''}
              <button onClick={() => set('inventory', inventory.filter((_, idx) => idx !== i))}
                className="text-zinc-400 hover:text-red-400">×</button>
            </span>
          ))}
          {inventory.length === 0 && <span className="text-xs text-zinc-600">（空）</span>}
        </div>
        <div className="flex gap-1">
          <input value={newItem} onChange={e => setNewItem(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && newItem.trim()) { e.preventDefault(); set('inventory', [...inventory, { name: newItem.trim(), quantity: 1 }]); setNewItem('') } }}
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none"
            placeholder="新增道具，回车确认" />
          <button onClick={() => { if (newItem.trim()) { set('inventory', [...inventory, { name: newItem.trim(), quantity: 1 }]); setNewItem('') } }}
            className="text-xs bg-zinc-700 hover:bg-zinc-600 px-2 rounded">+</button>
        </div>
      </div>

      {/* first_message 开场独白 */}
      <div>
        <InfoLabel text="开场独白 first_message" tip="角色登场第一句话，用于会话开场叙事" />
        <textarea value={(data.first_message as string) || ''} onChange={e => set('first_message', e.target.value)} rows={2}
          className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs resize-none focus:outline-none"
          placeholder="如：「又是无聊的一天……」" />
      </div>
    </div>
  )
}
