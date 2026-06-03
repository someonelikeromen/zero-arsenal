/**
 * WorldManager — 全局世界模板管理
 * 三种创建方式：手动填写 / URL 抓取 / 文档解析
 * 提炼结果可逐条编辑、再次生成，最终确认写入
 */
import React, { useEffect, useState, useRef } from 'react'
import { api, World, WorldArchiveEntry } from '../lib/api'
import { notify } from '../stores/ui'
import { requestConfirm } from '../stores/confirm'

// ── 类型 ──────────────────────────────────────────────────────────────────────
interface LoreEntry { title: string; content: string; archive_type: string }

type CreationTab = 'manual' | 'url' | 'doc'

// ── 子组件：档案条目编辑器 ────────────────────────────────────────────────────
function ArchiveEntryEditor({
  entry, onSave, onDelete,
}: {
  entry: WorldArchiveEntry
  onSave: (id: string, update: Partial<WorldArchiveEntry>) => void
  onDelete: (id: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(entry.title)
  const [content, setContent] = useState(entry.content)
  const [type, setType] = useState(entry.archive_type)
  const [keywords, setKeywords] = useState(entry.trigger_keywords ?? '')

  const save = () => {
    onSave(entry.id, { title, content, archive_type: type, trigger_keywords: keywords })
    setEditing(false)
  }

  if (editing) {
    return (
      <div className="bg-zinc-800 rounded p-3 space-y-2">
        <input value={title} onChange={e => setTitle(e.target.value)}
          className="w-full bg-zinc-700 rounded px-2 py-1 text-sm" placeholder="标题" />
        <textarea value={content} onChange={e => setContent(e.target.value)} rows={3}
          className="w-full bg-zinc-700 rounded px-2 py-1 text-sm resize-none" placeholder="内容" />
        <div className="flex items-center gap-2">
          <select value={type} onChange={e => setType(e.target.value)}
            className="bg-zinc-700 rounded px-2 py-1 text-xs">
            {ARCHIVE_TYPES.map(t => <option key={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[10px] text-zinc-500 flex items-center gap-1 mb-0.5">
            🔑 触发关键词（逗号分隔，叙事命中时高亮提示）
          </label>
          <input value={keywords} onChange={e => setKeywords(e.target.value)}
            className="w-full bg-zinc-700 rounded px-2 py-1 text-xs" placeholder="如：主神空间, 强化点数, 轮回者" />
        </div>
        <div className="flex gap-2">
          <button onClick={save} className="text-xs bg-indigo-600 hover:bg-indigo-500 px-3 py-1 rounded">保存</button>
          <button onClick={() => setEditing(false)} className="text-xs text-zinc-400 hover:text-zinc-200">取消</button>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-zinc-800/50 rounded p-3 flex items-start gap-2 group">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs bg-zinc-700 text-zinc-300 px-1.5 py-0.5 rounded">{entry.archive_type}</span>
          <span className="text-sm font-medium truncate">{entry.title}</span>
          {entry.trigger_keywords && (
            <span className="text-[10px] text-amber-400 shrink-0" title={`触发关键词：${entry.trigger_keywords}`}>🔑</span>
          )}
        </div>
        <p className="text-xs text-zinc-400 line-clamp-2">{entry.content}</p>
      </div>
      <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
        <button onClick={() => setEditing(true)} className="text-xs text-zinc-400 hover:text-zinc-200 px-1">编辑</button>
        <button onClick={() => onDelete(entry.id)} className="text-xs text-red-500 hover:text-red-400 px-1">删除</button>
      </div>
    </div>
  )
}

const ARCHIVE_TYPES = ['lore', 'rule', 'setting', 'npc', 'opening_scene'] as const

// ── 子组件：提炼结果预览（SSE 生成后编辑确认）──────────────────────────────
function LorePreview({
  worldId, entries, onConfirmed, onRegenerate, generating,
}: {
  worldId: string
  entries: LoreEntry[]
  onConfirmed: () => void
  onRegenerate: () => void
  generating: boolean
}) {
  const [items, setItems] = useState<LoreEntry[]>(entries)
  const [saving, setSaving] = useState(false)
  const [filterType, setFilterType] = useState<string>('all')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [bulkType, setBulkType] = useState<string>('lore')

  useEffect(() => { setItems(entries); setSelected(new Set()); setExpanded(new Set()) }, [entries])

  const update = (i: number, field: keyof LoreEntry, val: string) => {
    setItems(prev => prev.map((e, idx) => idx === i ? { ...e, [field]: val } : e))
  }

  const remove = (i: number) => setItems(prev => prev.filter((_, idx) => idx !== i))

  const add = () => setItems(prev => [...prev, { title: '', content: '', archive_type: 'lore' }])

  const toggleSelect = (i: number) => setSelected(prev => {
    const next = new Set(prev)
    next.has(i) ? next.delete(i) : next.add(i)
    return next
  })

  const toggleExpand = (i: number) => setExpanded(prev => {
    const next = new Set(prev)
    next.has(i) ? next.delete(i) : next.add(i)
    return next
  })

  const applyBulkType = () => {
    if (selected.size === 0) { notify.warning('请先勾选要修改的条目'); return }
    setItems(prev => prev.map((e, idx) => selected.has(idx) ? { ...e, archive_type: bulkType } : e))
    notify.success(`已将 ${selected.size} 条改为 ${bulkType}`)
  }

  // 计数 + 过滤索引
  const typeCounts = items.reduce<Record<string, number>>((acc, e) => {
    acc[e.archive_type] = (acc[e.archive_type] ?? 0) + 1
    return acc
  }, {})
  const visibleIdx = items.map((_, i) => i).filter(i => filterType === 'all' || items[i].archive_type === filterType)

  const confirmEntries = async () => {
    if (!items.length) return
    setSaving(true)
    try {
      await api.confirmLore(worldId, items.filter(e => e.title || e.content))
      notify.success(`已写入 ${items.filter(e => e.title || e.content).length} 条档案`)
      onConfirmed()
    } catch (e) {
      notify.error(`写入失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-zinc-300">提炼结果（{items.length} 条）</span>
        <div className="flex gap-2">
          <button onClick={onRegenerate} disabled={generating}
            className="text-xs text-zinc-400 hover:text-zinc-200 disabled:opacity-50">
            {generating ? '生成中...' : '重新生成'}
          </button>
          <button onClick={add} className="text-xs text-zinc-400 hover:text-zinc-200">+ 添加</button>
        </div>
      </div>

      {/* archive_type 分 Tab 过滤 */}
      <div className="flex flex-wrap gap-1">
        <button onClick={() => setFilterType('all')}
          className={`px-2 py-0.5 text-xs rounded ${filterType === 'all' ? 'bg-indigo-600 text-white' : 'bg-zinc-800 text-zinc-400 hover:text-zinc-200'}`}>
          全部 {items.length}
        </button>
        {ARCHIVE_TYPES.map(t => (
          <button key={t} onClick={() => setFilterType(t)}
            className={`px-2 py-0.5 text-xs rounded ${filterType === t ? 'bg-indigo-600 text-white' : 'bg-zinc-800 text-zinc-400 hover:text-zinc-200'}`}>
            {t} {typeCounts[t] ?? 0}
          </button>
        ))}
      </div>

      {/* 批量改类型工具条 */}
      {selected.size > 0 && (
        <div className="flex items-center gap-2 bg-zinc-800/70 rounded px-2 py-1.5">
          <span className="text-xs text-zinc-400">已选 {selected.size} 条</span>
          <select value={bulkType} onChange={e => setBulkType(e.target.value)}
            className="bg-zinc-700 rounded px-2 py-0.5 text-xs">
            {ARCHIVE_TYPES.map(t => <option key={t}>{t}</option>)}
          </select>
          <button onClick={applyBulkType} className="text-xs bg-indigo-600 hover:bg-indigo-500 px-2 py-0.5 rounded">批量改类型</button>
          <button onClick={() => setSelected(new Set())} className="text-xs text-zinc-500 hover:text-zinc-300">清除选择</button>
        </div>
      )}

      <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
        {visibleIdx.map((i) => {
          const item = items[i]
          const isExpanded = expanded.has(i)
          const longContent = item.content.length > 200
          return (
            <div key={i} className="bg-zinc-800 rounded p-2 space-y-1.5">
              <div className="flex gap-2 items-center">
                <input type="checkbox" checked={selected.has(i)} onChange={() => toggleSelect(i)}
                  className="accent-indigo-500" />
                <input value={item.title} onChange={e => update(i, 'title', e.target.value)}
                  className="flex-1 bg-zinc-700 rounded px-2 py-1 text-xs" placeholder="标题" />
                <select value={item.archive_type} onChange={e => update(i, 'archive_type', e.target.value)}
                  className="bg-zinc-700 rounded px-2 py-1 text-xs">
                  {ARCHIVE_TYPES.map(t => <option key={t}>{t}</option>)}
                </select>
                <button onClick={() => remove(i)} className="text-red-500 text-xs px-1">×</button>
              </div>
              {longContent && !isExpanded ? (
                <div className="text-xs text-zinc-400 px-1">
                  <span className="line-clamp-2">{item.content}</span>
                  <button onClick={() => toggleExpand(i)} className="text-indigo-400 hover:text-indigo-300 mt-0.5">展开编辑 ▾</button>
                </div>
              ) : (
                <>
                  <textarea value={item.content} onChange={e => update(i, 'content', e.target.value)} rows={isExpanded ? 5 : 2}
                    className="w-full bg-zinc-700 rounded px-2 py-1 text-xs resize-none" placeholder="内容" />
                  {longContent && (
                    <button onClick={() => toggleExpand(i)} className="text-xs text-zinc-500 hover:text-zinc-300">收起 ▴</button>
                  )}
                </>
              )}
            </div>
          )
        })}
      </div>
      <button onClick={confirmEntries} disabled={saving || !items.length}
        className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 text-white py-2 rounded text-sm">
        {saving ? '写入中...' : '确认写入档案库'}
      </button>
    </div>
  )
}

// ── 子组件：世界创建/编辑 Modal ───────────────────────────────────────────────
function WorldModal({
  worldId, onClose, onSaved,
}: {
  worldId: string | null
  onClose: () => void
  onSaved: () => void
}) {
  const [tab, setTab] = useState<CreationTab>('manual')
  const [name, setName] = useState('')
  const [plugin, setPlugin] = useState('crossover')
  const [desc, setDesc] = useState('')
  const [url, setUrl] = useState('')
  const [docText, setDocText] = useState('')
  const [generating, setGenerating] = useState(false)
  const [loreEntries, setLoreEntries] = useState<LoreEntry[]>([])
  const [sseLog, setSseLog] = useState('')
  const [error, setError] = useState('')
  const [createdWorldId, setCreatedWorldId] = useState<string | null>(worldId)
  // 每条 URL 的抓取状态：pending / fetching / fetched / failed
  const [urlStatuses, setUrlStatuses] = useState<Record<string, { status: string; reason?: string }>>({})
  const abortRef = useRef<(() => void) | null>(null)

  const parseUrls = (raw: string): string[] =>
    raw.split('\n').map(s => s.trim()).filter(Boolean)

  const ensureWorldCreated = async (): Promise<string> => {
    if (createdWorldId) return createdWorldId
    const res = await api.createWorld({ name: name || '未命名世界', world_plugin: plugin, description: desc })
    setCreatedWorldId(res.world_id)
    return res.world_id
  }

  const runSSE = async (endpoint: string, body: unknown) => {
    setGenerating(true)
    setLoreEntries([])
    setSseLog('')
    setError('')
    try {
      await ensureWorldCreated()
      const resp = await fetch(`/api${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const reader = resp.body!.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let cancelled = false
      abortRef.current = () => { cancelled = true; reader.cancel() }
      while (!cancelled) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          try {
            const evt = JSON.parse(line.slice(5).trim())
            if (evt.type === 'url_status' && evt.url) {
              setUrlStatuses(prev => ({ ...prev, [evt.url]: { status: evt.status, reason: evt.reason } }))
              if (evt.status === 'fetching') setSseLog(`抓取中：${evt.url}`)
            }
            if (evt.type === 'fetching') setSseLog(`抓取中：${evt.url ?? ''}`)
            if (evt.type === 'fetched') setSseLog(`抓取完成（${evt.engine}，${evt.chars} 字），提炼中...`)
            if (evt.type === 'start') setSseLog('提炼中...')
            if (evt.type === 'done') {
              setLoreEntries(evt.entries || [])
              setSseLog(`提炼完成，共 ${(evt.entries || []).length} 条`)
            }
            if (evt.type === 'error') { setError(evt.message); notify.error(`提炼失败：${evt.message}`) }
          } catch { /* ignore */ }
        }
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '请求失败')
    } finally {
      setGenerating(false)
    }
  }

  const handleFetch = async () => {
    const urls = parseUrls(url)
    if (urls.length === 0) { notify.warning('请至少输入一个 URL'); return }
    let wid: string
    try { wid = await ensureWorldCreated() } catch { return }
    setUrlStatuses(Object.fromEntries(urls.map(u => [u, { status: 'pending' }])))
    runSSE(`/worlds/${wid}/fetch-lore`, { urls })
  }

  const handleRetryUrl = async (failedUrl: string) => {
    let wid: string
    try { wid = await ensureWorldCreated() } catch { return }
    setUrlStatuses(prev => ({ ...prev, [failedUrl]: { status: 'pending' } }))
    runSSE(`/worlds/${wid}/fetch-lore`, { urls: [failedUrl] })
  }
  const handleParse = async () => {
    try { await ensureWorldCreated() } catch { return }
    if (!createdWorldId) return
    runSSE(`/worlds/${createdWorldId}/parse-document`, { text: docText })
  }

  const handleSaveManual = async () => {
    try {
      await ensureWorldCreated()
      onSaved()
      onClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败')
    }
  }

  const TABS: { id: CreationTab; label: string }[] = [
    { id: 'manual', label: '手动填写' },
    { id: 'url', label: 'URL 抓取' },
    { id: 'doc', label: '文档解析' },
  ]

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-zinc-800">
          <h3 className="font-semibold">新建世界</h3>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">×</button>
        </div>
        <div className="p-4 space-y-4">
          {/* 基础信息 */}
          <div className="space-y-2">
            <input value={name} onChange={e => setName(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
              placeholder="世界名称（必填）" />
            <div className="flex gap-2">
              <select value={plugin} onChange={e => setPlugin(e.target.value)}
                className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none">
                {['crossover', 'wuxia', 'infinite_arsenal', 'muv_luv', 'gundam_seed'].map(p => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </div>
            <textarea value={desc} onChange={e => setDesc(e.target.value)} rows={2}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none resize-none"
              placeholder="世界描述（可选）" />
          </div>

          {/* 档案创建方式 */}
          <div>
            <div className="flex gap-1 mb-3">
              {TABS.map(t => (
                <button key={t.id} onClick={() => setTab(t.id)}
                  className={`px-3 py-1.5 text-xs rounded transition-colors ${tab === t.id
                    ? 'bg-indigo-600 text-white' : 'bg-zinc-800 text-zinc-400 hover:text-zinc-200'}`}>
                  {t.label}
                </button>
              ))}
            </div>

            {tab === 'manual' && (
              <div className="space-y-2">
                <p className="text-xs text-zinc-500">填写基础信息后保存世界，之后在档案标签页手动添加条目。</p>
                <button onClick={handleSaveManual}
                  className="w-full bg-indigo-600 hover:bg-indigo-500 text-white py-2 rounded text-sm">
                  创建世界
                </button>
              </div>
            )}

            {tab === 'url' && (
              <div className="space-y-3">
                <textarea value={url} onChange={e => setUrl(e.target.value)} rows={3}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-indigo-500 resize-none"
                  placeholder="每行一个 URL，可批量抓取（如 Wiki / 设定集页面）..." />
                <button onClick={handleFetch} disabled={!url.trim() || generating}
                  className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 text-white py-2 rounded text-sm">
                  {generating ? '抓取中...' : `抓取并提炼（${parseUrls(url).length} 个 URL）`}
                </button>

                {/* 每条 URL 独立状态 */}
                {Object.keys(urlStatuses).length > 0 && (
                  <div className="space-y-1">
                    {Object.entries(urlStatuses).map(([u, st]) => (
                      <div key={u} className="flex items-center gap-2 text-xs">
                        <span className={
                          st.status === 'fetched' ? 'text-emerald-400'
                          : st.status === 'failed' ? 'text-red-400'
                          : st.status === 'fetching' ? 'text-amber-400'
                          : 'text-zinc-500'
                        }>
                          {st.status === 'fetched' ? '✓' : st.status === 'failed' ? '✕' : st.status === 'fetching' ? '⟳' : '○'}
                        </span>
                        <span className="flex-1 truncate text-zinc-400" title={u}>{u}</span>
                        {st.status === 'failed' && (
                          <>
                            <span className="text-red-500/70 truncate max-w-[120px]" title={st.reason}>{st.reason}</span>
                            <button onClick={() => handleRetryUrl(u)} disabled={generating}
                              className="text-indigo-400 hover:text-indigo-300 disabled:opacity-50">重试</button>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {sseLog && <p className="text-xs text-zinc-400">{sseLog}</p>}
                {error && <p className="text-xs text-red-400">{error}</p>}
                {loreEntries.length > 0 && (
                  <LorePreview worldId={createdWorldId!} entries={loreEntries}
                    onConfirmed={() => { onSaved(); onClose() }}
                    onRegenerate={handleFetch} generating={generating} />
                )}
              </div>
            )}

            {tab === 'doc' && (
              <div className="space-y-3">
                <textarea value={docText} onChange={e => setDocText(e.target.value)} rows={6}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none resize-none"
                  placeholder="粘贴世界观文本、Wiki 片段、设定集内容..." />
                <button onClick={handleParse} disabled={!docText || generating}
                  className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 text-white py-2 rounded text-sm">
                  {generating ? '提炼中...' : '解析文档'}
                </button>
                {sseLog && <p className="text-xs text-zinc-400">{sseLog}</p>}
                {error && <p className="text-xs text-red-400">{error}</p>}
                {loreEntries.length > 0 && (
                  <LorePreview worldId={createdWorldId!} entries={loreEntries}
                    onConfirmed={() => { onSaved(); onClose() }}
                    onRegenerate={handleParse} generating={generating} />
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── 子组件：世界元数据行内编辑 ─────────────────────────────────────────────────
function WorldInlineEditor({
  world,
  onSave,
  onCancel,
}: {
  world: World
  onSave: (update: { name?: string; description?: string }) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(world.name)
  const [description, setDescription] = useState(world.description || '')

  return (
    <div className="flex flex-col gap-2 px-4 py-3 bg-zinc-750 border border-indigo-600 rounded-lg" onClick={e => e.stopPropagation()}>
      <input value={name} onChange={e => setName(e.target.value)}
        className="w-full bg-zinc-700 rounded px-2 py-1 text-sm" placeholder="世界名称" />
      <input value={description} onChange={e => setDescription(e.target.value)}
        className="w-full bg-zinc-700 rounded px-2 py-1 text-sm" placeholder="简介（可选）" />
      <div className="flex gap-2">
        <button onClick={() => onSave({ name, description })}
          className="text-xs bg-indigo-600 hover:bg-indigo-500 px-3 py-1 rounded">保存</button>
        <button onClick={onCancel} className="text-xs text-zinc-400 hover:text-zinc-200">取消</button>
      </div>
    </div>
  )
}

// ── 主组件 ────────────────────────────────────────────────────────────────────
export const WorldManager: React.FC = () => {
  const [worlds, setWorlds] = useState<World[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [archives, setArchives] = useState<Record<string, WorldArchiveEntry[]>>({})
  const [editingId, setEditingId] = useState<string | null>(null)
  const [archiveSearch, setArchiveSearch] = useState('')
  const [archiveTypeFilter, setArchiveTypeFilter] = useState('all')

  const load = async () => {
    setLoading(true)
    try {
      const res = await api.listWorlds()
      setWorlds(res.worlds)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const loadArchives = async (wid: string) => {
    const res = await api.listGlobalWorldArchives(wid)
    setArchives(prev => ({ ...prev, [wid]: res.archives }))
  }

  const toggleExpand = (wid: string) => {
    if (expandedId === wid) {
      setExpandedId(null)
    } else {
      setExpandedId(wid)
      loadArchives(wid)
    }
  }

  const handleDelete = async (wid: string) => {
    const ok = await requestConfirm({
      title: '删除世界',
      message: '确认删除该世界及其所有档案？此操作不可撤销。',
      confirmText: '删除',
      danger: true,
    })
    if (!ok) return
    try {
      await api.deleteWorld(wid)
      notify.success('已删除世界')
      load()
    } catch (e) {
      notify.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const handleEditSave = async (wid: string, update: { name?: string; description?: string }) => {
    try {
      await api.updateWorld(wid, update)
      setEditingId(null)
      notify.success('已更新世界信息')
      load()
    } catch (e) {
      notify.error(`更新失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const handleSaveArchive = async (wid: string, aid: string, update: Partial<WorldArchiveEntry>) => {
    try {
      await api.updateGlobalWorldArchive(wid, aid, update)
      notify.success('已保存档案条目')
      loadArchives(wid)
    } catch (e) {
      notify.error(`保存失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const handleDeleteArchive = async (wid: string, aid: string) => {
    try {
      await api.deleteGlobalWorldArchive(wid, aid)
      loadArchives(wid)
    } catch (e) {
      notify.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const handleAddArchive = async (wid: string) => {
    try {
      await api.createGlobalWorldArchive(wid, { title: '新条目', content: '', archive_type: 'lore' })
      loadArchives(wid)
    } catch (e) {
      notify.error(`添加失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-32 text-zinc-500 text-sm">加载中...</div>
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">世界库</h2>
        <button onClick={() => setShowModal(true)}
          className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-1.5 rounded text-sm">
          + 新建世界
        </button>
      </div>

      {worlds.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-zinc-500 gap-3">
          <p className="text-sm">暂无世界模板</p>
          <button onClick={() => setShowModal(true)} className="text-indigo-400 hover:text-indigo-300 text-sm">
            创建第一个世界 →
          </button>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto space-y-2 pr-1">
          {worlds.map(w => (
            <div key={w.id} className="bg-zinc-800 border border-zinc-700 rounded-lg overflow-hidden">
              {editingId === w.id ? (
                <WorldInlineEditor world={w}
                  onSave={update => handleEditSave(w.id, update)}
                  onCancel={() => setEditingId(null)} />
              ) : (
              <div className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-zinc-750"
                onClick={() => toggleExpand(w.id)}>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{w.name}</span>
                    <span className="text-xs bg-zinc-700 text-zinc-400 px-1.5 py-0.5 rounded">{w.world_plugin}</span>
                  </div>
                  {w.description && (
                    <p className="text-xs text-zinc-500 mt-0.5 truncate">{w.description}</p>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-xs text-zinc-600">
                    {new Date((w.updated_at || 0) * 1000).toLocaleDateString()}
                  </span>
                  <button onClick={e => { e.stopPropagation(); setEditingId(w.id) }}
                    className="text-xs text-zinc-400 hover:text-zinc-200 px-1">
                    编辑
                  </button>
                  <button onClick={e => { e.stopPropagation(); handleDelete(w.id) }}
                    className="text-xs text-red-500 hover:text-red-400 px-1">
                    删除
                  </button>
                  <span className="text-zinc-500 text-sm">{expandedId === w.id ? '▲' : '▼'}</span>
                </div>
              </div>
              )}

              {expandedId === w.id && (() => {
                const all = archives[w.id] || []
                const filtered = all.filter(e => {
                  const matchType = archiveTypeFilter === 'all' || e.archive_type === archiveTypeFilter
                  const q = archiveSearch.trim().toLowerCase()
                  const matchSearch = !q || e.title.toLowerCase().includes(q) || (e.content || '').toLowerCase().includes(q)
                  return matchType && matchSearch
                })
                return (
                <div className="border-t border-zinc-700 px-4 py-3 space-y-2">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-zinc-400">
                      档案条目 ({filtered.length}/{all.length})
                    </span>
                    <button onClick={() => handleAddArchive(w.id)}
                      className="text-xs text-indigo-400 hover:text-indigo-300">+ 添加</button>
                  </div>
                  {/* 搜索 + 类型过滤 */}
                  {all.length > 0 && (
                    <div className="flex gap-2 mb-2">
                      <input value={archiveSearch} onChange={e => setArchiveSearch(e.target.value)}
                        className="flex-1 bg-zinc-700 rounded px-2 py-1 text-xs focus:outline-none"
                        placeholder="搜索标题/内容..." />
                      <select value={archiveTypeFilter} onChange={e => setArchiveTypeFilter(e.target.value)}
                        className="bg-zinc-700 rounded px-2 py-1 text-xs">
                        <option value="all">全部类型</option>
                        {ARCHIVE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </div>
                  )}
                  {all.length === 0 ? (
                    <p className="text-xs text-zinc-600 text-center py-2">暂无档案</p>
                  ) : filtered.length === 0 ? (
                    <p className="text-xs text-zinc-600 text-center py-2">无匹配条目</p>
                  ) : (
                    filtered.map(entry => (
                      <ArchiveEntryEditor key={entry.id} entry={entry}
                        onSave={(aid, upd) => handleSaveArchive(w.id, aid, upd)}
                        onDelete={aid => handleDeleteArchive(w.id, aid)} />
                    ))
                  )}
                </div>
                )
              })()}
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <WorldModal worldId={null} onClose={() => setShowModal(false)} onSaved={load} />
      )}
    </div>
  )
}
