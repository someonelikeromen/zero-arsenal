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

  const attrs = (data.attributes as Record<string, number>) || {}
  const setAttr = (k: string, delta: number) => {
    const next = Math.max(1, Math.min(10, (attrs[k] ?? 1) + delta))
    set('attributes', { ...attrs, [k]: next })
  }

  const skills = (data.skills as Record<string, number>) || {}
  const inventory = (data.inventory as Array<{ name: string; quantity?: number }>) || []

  const [newSkill, setNewSkill] = useState('')
  const [newItem, setNewItem] = useState('')

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
          {Object.entries(attrs).map(([k, v]) => (
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
