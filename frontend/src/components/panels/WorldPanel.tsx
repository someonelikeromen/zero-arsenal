/**
 * WorldPanel — 世界档案 + NPC 档案面板（设计文档 12 §4.5）
 * 接入 useWorldStore（差距023修复）
 */
import React, { useEffect, useState, useCallback, useMemo } from 'react'
import { useWorldStore } from '../../stores/world'
import { useStoryStore } from '../../stores/story'
import { api } from '../../lib/api'
import { notify } from '../../stores/ui'
import { requestConfirm } from '../../stores/confirm'

interface NpcProfile {
  id: string
  key: string
  name: string
  world_key?: string
  profile: Record<string, unknown>
}

interface WorldPanelProps {
  sessionId: string
  worldPlugin?: string
}

const ARCHIVE_ICONS: Record<string, string> = {
  lore: '📖',
  npc: '👤',
  rule: '⚖️',
  setting: '🌍',
  opening_scene: '🎬',
}

type Tab = 'archives' | 'npcs'

export const WorldPanel: React.FC<WorldPanelProps> = ({ sessionId, worldPlugin = 'crossover' }) => {
  const { archives, isLoading, error, loadArchives, setWorldPlugin } = useWorldStore()
  const [tab, setTab]               = useState<Tab>('archives')
  const [npcs, setNpcs]             = useState<NpcProfile[]>([])
  const [npcsLoading, setNpcsLoading] = useState(false)
  const [activeType, setActiveType] = useState<string>('all')
  const [expandedNpc, setExpandedNpc] = useState<string | null>(null)
  const [editingNpc, setEditingNpc] = useState<NpcProfile | null>(null)
  const [creatingNpc, setCreatingNpc] = useState(false)

  // 同步 worldPlugin 到 store
  useEffect(() => {
    setWorldPlugin(worldPlugin)
  }, [worldPlugin, setWorldPlugin])

  // 加载世界档案
  useEffect(() => {
    if (!sessionId || tab !== 'archives') return
    loadArchives(sessionId)
  }, [sessionId, tab, loadArchives])

  const loadNpcs = useCallback(() => {
    if (!sessionId) return
    setNpcsLoading(true)
    api.listSessionNpcs(sessionId)
      .then(d => setNpcs(d.npcs ?? []))
      .catch(e => notify.error(`加载 NPC 失败：${String(e)}`))
      .finally(() => setNpcsLoading(false))
  }, [sessionId])

  // 加载 NPC 档案
  useEffect(() => {
    if (tab !== 'npcs') return
    loadNpcs()
  }, [tab, loadNpcs])

  const handleDeleteNpc = useCallback(async (npc: NpcProfile) => {
    const ok = await requestConfirm({
      title: '删除 NPC', message: `确定删除「${npc.name}」？此操作不可撤销。`, danger: true,
    })
    if (!ok) return
    try {
      await api.deleteSessionNpc(sessionId, npc.key)
      notify.success(`已删除 NPC：${npc.name}`)
      loadNpcs()
    } catch (e) {
      notify.error(`删除失败：${String(e)}`)
    }
  }, [sessionId, loadNpcs])

  const archiveTypes = ['all', 'lore', 'npc', 'rule', 'setting', 'opening_scene']
  const filteredArchives = activeType === 'all'
    ? archives
    : archives.filter(a => a.archive_type === activeType)

  // Lorebook 命中检测：最近叙事文本中是否出现某档案的触发关键词
  const parts = useStoryStore(s => s.parts)
  const recentNarrative = useMemo(() => {
    const texts = parts
      .filter(p => p.type === 'narrative')
      .slice(-4)
      .map(p => (p.content?.text as string) ?? p.streamBuffer ?? '')
    return texts.join('\n').toLowerCase()
  }, [parts])

  const hitArchiveIds = useMemo(() => {
    const hits = new Set<string>()
    if (!recentNarrative) return hits
    for (const a of archives) {
      const kw = (a.trigger_keywords ?? '').split(/[,，、]/).map(s => s.trim()).filter(Boolean)
      if (kw.some(k => recentNarrative.includes(k.toLowerCase()))) hits.add(a.id)
    }
    return hits
  }, [archives, recentNarrative])

  return (
    <div className="world-panel flex flex-col bg-zinc-900 rounded-lg border border-zinc-800">
      {/* Tab 栏 */}
      <div className="flex items-center gap-1 px-3 pt-2 border-b border-zinc-800">
        {(['archives', 'npcs'] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 text-xs font-medium rounded-t transition-colors -mb-px border-b-2 ${
              tab === t
                ? 'text-zinc-200 border-indigo-500'
                : 'text-zinc-600 border-transparent hover:text-zinc-400'
            }`}
          >
            {t === 'archives' ? `🌍 世界档案 (${archives.length})` : `👥 NPC (${npcs.length})`}
          </button>
        ))}
      </div>

      {/* 世界插件标签 */}
      <div className="text-[10px] text-zinc-700 px-3 pt-1">插件：{worldPlugin}</div>

      {(isLoading || npcsLoading) && <div className="text-xs text-zinc-600 px-3 py-2">加载中...</div>}
      {error && <div className="text-xs text-red-500 px-3 py-1">{error}</div>}

      {/* ── 世界档案 Tab ── */}
      {tab === 'archives' && !isLoading && (
        <div className="flex flex-col gap-1 px-2 pb-2 pt-1">
          {/* 类型过滤 */}
          <div className="flex gap-1 flex-wrap">
            {archiveTypes.map(t => (
              <button
                key={t}
                onClick={() => setActiveType(t)}
                className={`text-[10px] px-1.5 py-0.5 rounded ${
                  activeType === t
                    ? 'bg-indigo-700 text-white'
                    : 'bg-zinc-800 text-zinc-500 hover:text-zinc-300'
                }`}
              >
                {t === 'all' ? '全部' : `${ARCHIVE_ICONS[t]} ${t}`}
              </button>
            ))}
          </div>

          {/* 档案列表 */}
          <div className="flex flex-col gap-1 max-h-56 overflow-y-auto mt-1">
            {filteredArchives.length === 0 && (
              <div className="text-xs text-zinc-700 px-1 py-2 text-center">暂无档案</div>
            )}
            {filteredArchives.map(a => {
              const hit = hitArchiveIds.has(a.id)
              return (
              <div key={a.id} className={`rounded px-2 py-1.5 ${hit ? 'bg-amber-950/40 border border-amber-700/60' : 'bg-zinc-800'}`}>
                <div className="flex items-center gap-1.5">
                  <span className="text-xs">{ARCHIVE_ICONS[a.archive_type] ?? '📄'}</span>
                  <span className="text-xs text-zinc-300 font-medium truncate">{a.title}</span>
                  {hit && (
                    <span className="text-[10px] text-amber-400 shrink-0" title="本段叙事命中此条目的触发关键词">🔑</span>
                  )}
                  {!hit && a.trigger_keywords && (
                    <span className="text-[10px] text-zinc-600 shrink-0" title={`触发关键词：${a.trigger_keywords}`}>🔑</span>
                  )}
                  <span className="ml-auto text-[9px] text-zinc-600">{a.archive_type}</span>
                </div>
                <p className="text-[10px] text-zinc-500 mt-0.5 line-clamp-2">{a.content}</p>
              </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── NPC Tab ── */}
      {tab === 'npcs' && !npcsLoading && (
        <div className="flex flex-col gap-1 px-2 pb-2 pt-1 max-h-72 overflow-y-auto">
          <button
            onClick={() => setCreatingNpc(true)}
            className="text-[11px] px-2 py-1 mb-1 rounded bg-indigo-700 hover:bg-indigo-600 text-white self-start"
          >
            + 新增 NPC
          </button>
          {npcs.length === 0 && (
            <div className="text-xs text-zinc-700 px-1 py-2 text-center">暂无 NPC</div>
          )}
          {npcs.map(npc => {
            const profile = npc.profile ?? {}
            const isExpanded = expandedNpc === npc.id
            const traits = Array.isArray(profile.traits) ? profile.traits as string[] : []
            const keywords = Array.isArray(profile.trigger_keywords) ? profile.trigger_keywords as string[] : []
            return (
              <div key={npc.id} className="bg-zinc-800 rounded px-2 py-1.5">
                <div className="w-full flex items-center justify-between gap-1">
                  <button
                    className="flex items-center gap-1.5 min-w-0 flex-1"
                    onClick={() => setExpandedNpc(isExpanded ? null : npc.id)}
                  >
                    <span className="text-xs">👤</span>
                    <span className="text-xs text-zinc-300 font-medium truncate">{npc.name}</span>
                    {(profile.role as string | undefined) && (
                      <span className="text-[9px] text-zinc-600 truncate">{String(profile.role)}</span>
                    )}
                  </button>
                  <button
                    onClick={() => setEditingNpc(npc)}
                    className="text-[10px] text-zinc-500 hover:text-indigo-400 flex-shrink-0"
                    title="编辑"
                  >✎</button>
                  <button
                    onClick={() => handleDeleteNpc(npc)}
                    className="text-[10px] text-zinc-500 hover:text-red-400 flex-shrink-0"
                    title="删除"
                  >🗑</button>
                  <button
                    onClick={() => setExpandedNpc(isExpanded ? null : npc.id)}
                    className="text-zinc-600 text-xs flex-shrink-0"
                  >{isExpanded ? '▾' : '▸'}</button>
                </div>

                {isExpanded && (
                  <div className="mt-1.5 space-y-1 text-[10px] text-zinc-500">
                    {(profile.faction as string | undefined) && (
                      <div>势力：{String(profile.faction)}</div>
                    )}
                    {traits.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {traits.slice(0, 5).map((t, i) => (
                          <span key={i} className="bg-zinc-700 px-1 py-0.5 rounded text-zinc-400">{t}</span>
                        ))}
                      </div>
                    )}
                    {keywords.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {keywords.map((k, i) => (
                          <span key={i} className="bg-amber-900/40 text-amber-400 px-1 py-0.5 rounded">🔑 {k}</span>
                        ))}
                      </div>
                    )}
                    {(profile.backstory as string | undefined) && (
                      <p className="leading-relaxed line-clamp-3 text-zinc-600">{String(profile.backstory)}</p>
                    )}
                    {(profile.hp as number | undefined) !== undefined && (
                      <div>HP：{String(profile.hp)} / {String(profile.max_hp ?? profile.hp)}</div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {(creatingNpc || editingNpc) && (
        <NpcEditModal
          sessionId={sessionId}
          npc={editingNpc}
          onClose={() => { setCreatingNpc(false); setEditingNpc(null) }}
          onSaved={() => { setCreatingNpc(false); setEditingNpc(null); loadNpcs() }}
        />
      )}
    </div>
  )
}

// ── NPC 新增/编辑弹窗 ─────────────────────────────────────────────────────────

const NpcEditModal: React.FC<{
  sessionId: string
  npc: NpcProfile | null
  onClose: () => void
  onSaved: () => void
}> = ({ sessionId, npc, onClose, onSaved }) => {
  const p = npc?.profile ?? {}
  const [name, setName] = useState(npc?.name ?? '')
  const [role, setRole] = useState(String(p.role ?? 'minor'))
  const [faction, setFaction] = useState(String(p.faction ?? ''))
  const [traits, setTraits] = useState(Array.isArray(p.traits) ? (p.traits as string[]).join('、') : '')
  const [keywords, setKeywords] = useState(
    Array.isArray(p.trigger_keywords) ? (p.trigger_keywords as string[]).join('、') : ''
  )
  const [backstory, setBackstory] = useState(String(p.backstory ?? ''))
  const [saving, setSaving] = useState(false)

  const splitList = (s: string) =>
    s.split(/[、,，\n]/).map(x => x.trim()).filter(Boolean)

  const handleSave = async () => {
    if (!name.trim()) { notify.warning('请填写 NPC 名称'); return }
    setSaving(true)
    const profile = {
      ...p,
      role, faction,
      traits: splitList(traits),
      trigger_keywords: splitList(keywords),
      backstory,
    }
    try {
      if (npc) {
        await api.updateSessionNpc(sessionId, npc.key, { name, profile })
        notify.success(`已更新 NPC：${name}`)
      } else {
        await api.createSessionNpc(sessionId, { name, profile })
        notify.success(`已新增 NPC：${name}`)
      }
      onSaved()
    } catch (e) {
      notify.error(`保存失败：${String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="bg-zinc-900 border border-zinc-700 rounded-lg w-full max-w-md p-4 space-y-3 max-h-[85vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <h3 className="text-sm font-bold text-zinc-200">{npc ? '编辑 NPC' : '新增 NPC'}</h3>
        <Field label="名称">
          <input value={name} onChange={e => setName(e.target.value)} className={INPUT_CLS} placeholder="如：白银武" />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="角色定位">
            <select value={role} onChange={e => setRole(e.target.value)} className={INPUT_CLS}>
              <option value="major">主要</option>
              <option value="minor">次要</option>
              <option value="ally">盟友</option>
              <option value="rival">对手</option>
              <option value="enemy">敌对</option>
            </select>
          </Field>
          <Field label="势力">
            <input value={faction} onChange={e => setFaction(e.target.value)} className={INPUT_CLS} placeholder="可空" />
          </Field>
        </div>
        <Field label="性格特质（顿号/逗号分隔）">
          <input value={traits} onChange={e => setTraits(e.target.value)} className={INPUT_CLS} placeholder="冷静、严谨、护短" />
        </Field>
        <Field label="🔑 触发关键词（Lorebook，命中即注入该 NPC 上下文）">
          <input value={keywords} onChange={e => setKeywords(e.target.value)} className={INPUT_CLS} placeholder="武、教官、试验机" />
        </Field>
        <Field label="背景简介">
          <textarea value={backstory} onChange={e => setBackstory(e.target.value)} rows={3} className={INPUT_CLS} />
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-3 py-1.5 text-xs rounded bg-zinc-800 text-zinc-300 hover:bg-zinc-700">取消</button>
          <button onClick={handleSave} disabled={saving}
            className="px-3 py-1.5 text-xs rounded bg-indigo-700 hover:bg-indigo-600 text-white disabled:opacity-50">
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

const INPUT_CLS = 'w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500'

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <label className="block">
    <span className="text-[10px] text-zinc-500 block mb-0.5">{label}</span>
    {children}
  </label>
)

export default WorldPanel
