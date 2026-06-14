/**
 * AssetLibrary — 全局资产库
 * 两个子 Tab：NPC 模板 + 物品模板
 */
import React, { useEffect, useState } from 'react'
import { api, NpcTemplate, ItemTemplate } from '../lib/api'
import { useSessionStore } from '../stores/session'
import { notify } from '../stores/ui'
import { requestConfirm } from '../stores/confirm'

type AssetTab = 'npcs' | 'items'

const ITEM_TYPES = ['equipment', 'consumable', 'artifact', 'material', 'misc']

function usePluginList() {
  const [plugins, setPlugins] = useState<{ key: string; name: string }[]>([])
  useEffect(() => {
    api.listWorldPlugins().then(r => setPlugins(r.plugins)).catch(() => {})
  }, [])
  return plugins
}

// ── NPC 表单 ──────────────────────────────────────────────────────────────────
function NpcForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState('')
  const [key, setKey] = useState('')
  const [plugin, setPlugin] = useState('crossover')
  const availablePlugins = usePluginList()
  const [profile, setProfile] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const save = async () => {
    if (!name) { setError('名称必填'); return }
    setSaving(true)
    try {
      let profileJson: Record<string, unknown> = {}
      if (profile) {
        try { profileJson = JSON.parse(profile) } catch { profileJson = { description: profile } }
      }
      await api.createNpcTemplate({ name, key: key || undefined, plugin_key: plugin, profile_json: profileJson })
      onSaved()
      onClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-md">
        <div className="flex items-center justify-between p-4 border-b border-zinc-800">
          <h3 className="font-semibold text-sm">新建 NPC 模板</h3>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">×</button>
        </div>
        <div className="p-4 space-y-3">
          {error && <div className="text-xs text-red-400 bg-red-900/20 border border-red-800 rounded p-2">{error}</div>}
          <input value={name} onChange={e => setName(e.target.value)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
            placeholder="NPC 名称（必填）" />
          <div className="flex gap-2">
            <input value={key} onChange={e => setKey(e.target.value)}
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none"
              placeholder="唯一键（可选，自动生成）" />
            <select value={plugin} onChange={e => setPlugin(e.target.value)}
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none">
              {availablePlugins.map(p => <option key={p.key} value={p.key}>{p.name || p.key}</option>)}
            </select>
          </div>
          <textarea value={profile} onChange={e => setProfile(e.target.value)} rows={4}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none resize-none"
            placeholder="NPC 档案（JSON 或文字描述）" />
          <div className="flex gap-2">
            <button onClick={onClose} className="flex-1 py-2 rounded text-sm text-zinc-400 hover:text-zinc-200 border border-zinc-700">取消</button>
            <button onClick={save} disabled={saving}
              className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 text-white py-2 rounded text-sm">
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── 物品表单 ──────────────────────────────────────────────────────────────────
function ItemForm({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState('')
  const [itemType, setItemType] = useState('equipment')
  const [plugin, setPlugin] = useState('crossover')
  const availablePlugins = usePluginList()
  const [desc, setDesc] = useState('')
  const [effects, setEffects] = useState('')
  const [tier, setTier] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const save = async () => {
    if (!name) { setError('名称必填'); return }
    setSaving(true)
    try {
      const dataJson: Record<string, unknown> = { description: desc }
      if (effects) dataJson.effects = effects
      if (tier) dataJson.tier = tier
      await api.createItemTemplate({ name, item_type: itemType, plugin_key: plugin, data_json: dataJson })
      onSaved()
      onClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-md">
        <div className="flex items-center justify-between p-4 border-b border-zinc-800">
          <h3 className="font-semibold text-sm">新建物品模板</h3>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">×</button>
        </div>
        <div className="p-4 space-y-3">
          {error && <div className="text-xs text-red-400 bg-red-900/20 border border-red-800 rounded p-2">{error}</div>}
          <input value={name} onChange={e => setName(e.target.value)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
            placeholder="物品名称（必填）" />
          <div className="flex gap-2">
            <select value={itemType} onChange={e => setItemType(e.target.value)}
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none">
              {ITEM_TYPES.map(t => <option key={t}>{t}</option>)}
            </select>
            <select value={plugin} onChange={e => setPlugin(e.target.value)}
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none">
              {availablePlugins.map(p => <option key={p.key} value={p.key}>{p.name || p.key}</option>)}
            </select>
          </div>
          <input value={tier} onChange={e => setTier(e.target.value)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none"
            placeholder="等级/品质（可选，如：3★M）" />
          <textarea value={desc} onChange={e => setDesc(e.target.value)} rows={2}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none resize-none"
            placeholder="物品描述" />
          <textarea value={effects} onChange={e => setEffects(e.target.value)} rows={2}
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none resize-none"
            placeholder="效果说明（可选）" />
          <div className="flex gap-2">
            <button onClick={onClose} className="flex-1 py-2 rounded text-sm text-zinc-400 hover:text-zinc-200 border border-zinc-700">取消</button>
            <button onClick={save} disabled={saving}
              className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 text-white py-2 rounded text-sm">
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── NPC 列表 ──────────────────────────────────────────────────────────────────
function NpcList() {
  const [npcs, setNpcs] = useState<NpcTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [importingId, setImportingId] = useState<string | null>(null)
  const currentSessionId = useSessionStore(s => s.currentSessionId)

  const load = async () => {
    setLoading(true)
    try { setNpcs((await api.listNpcTemplates()).npcs) } finally { setLoading(false) }
  }

  const handleImport = async (e: React.MouseEvent, npcId: string, npcName: string) => {
    e.stopPropagation()
    if (!currentSessionId) { notify.warning('请先打开一个会话再导入 NPC'); return }
    setImportingId(npcId)
    try {
      await api.importNpcToSession(npcId, currentSessionId)
      notify.success(`已导入 NPC「${npcName}」到当前会话`)
    } catch (err) {
      notify.error(`导入失败：${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setImportingId(null)
    }
  }

  useEffect(() => { load() }, [])

  if (loading) return <div className="text-center text-zinc-500 text-sm py-8">加载中...</div>

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button onClick={() => setShowForm(true)}
          className="bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded text-sm">
          + 新建 NPC
        </button>
      </div>
      {npcs.length === 0 ? (
        <p className="text-center text-zinc-500 text-sm py-8">暂无 NPC 模板</p>
      ) : (
        <div className="space-y-2">
          {npcs.map(npc => (
            <div key={npc.id} className="bg-zinc-800 border border-zinc-700 rounded-lg overflow-hidden">
              <div className="flex items-center gap-3 px-4 py-3 cursor-pointer"
                onClick={() => setExpandedId(expandedId === npc.id ? null : npc.id)}>
                <div className="w-7 h-7 bg-emerald-600/20 rounded-full flex items-center justify-center text-xs">
                  {npc.name.slice(0, 1)}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{npc.name}</span>
                    <span className="text-xs bg-zinc-700 text-zinc-400 px-1.5 rounded">{npc.key}</span>
                    <span className="text-xs text-zinc-600">{npc.plugin_key}</span>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button onClick={e => handleImport(e, npc.id, npc.name)} disabled={importingId === npc.id}
                    className="text-xs bg-emerald-700 hover:bg-emerald-600 disabled:bg-zinc-700 text-white px-2 py-0.5 rounded"
                    title="导入到当前会话">
                    {importingId === npc.id ? '导入中...' : '导入会话'}
                  </button>
                  <button onClick={async e => {
                      e.stopPropagation()
                      const ok = await requestConfirm({ title: '删除 NPC 模板', message: `确认删除「${npc.name}」？`, confirmText: '删除', danger: true })
                      if (!ok) return
                      try { await api.deleteNpcTemplate(npc.id); notify.success('已删除 NPC 模板'); load() }
                      catch (err) { notify.error(`删除失败：${err instanceof Error ? err.message : String(err)}`) }
                    }}
                    className="text-xs text-red-500 hover:text-red-400">删除</button>
                  <span className="text-zinc-600">{expandedId === npc.id ? '▲' : '▼'}</span>
                </div>
              </div>
              {expandedId === npc.id && (
                <div className="border-t border-zinc-700 px-4 py-3">
                  <pre className="text-xs text-zinc-400 whitespace-pre-wrap break-words font-mono bg-zinc-900 rounded p-2 max-h-32 overflow-y-auto">
                    {JSON.stringify(npc.profile_json, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {showForm && <NpcForm onClose={() => setShowForm(false)} onSaved={load} />}
    </div>
  )
}

// ── 物品列表 ──────────────────────────────────────────────────────────────────
function ItemList() {
  const [items, setItems] = useState<ItemTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [filterType, setFilterType] = useState('')
  const [grantingId, setGrantingId] = useState<string | null>(null)
  const currentSessionId = useSessionStore(s => s.currentSessionId)

  const load = async () => {
    setLoading(true)
    try { setItems((await api.listItemTemplates(filterType || undefined)).items) } finally { setLoading(false) }
  }

  const handleGrant = async (itemId: string, itemName: string) => {
    if (!currentSessionId) { notify.warning('请先打开一个会话再发放物品'); return }
    setGrantingId(itemId)
    try {
      await api.grantItemToSession(itemId, currentSessionId)
      notify.success(`已发放物品「${itemName}」到当前会话`)
    } catch (err) {
      notify.error(`发放失败：${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setGrantingId(null)
    }
  }

  useEffect(() => { load() }, [filterType])

  const TYPE_COLORS: Record<string, string> = {
    equipment: 'bg-blue-900 text-blue-300',
    consumable: 'bg-green-900 text-green-300',
    artifact: 'bg-yellow-900 text-yellow-300',
    material: 'bg-orange-900 text-orange-300',
    misc: 'bg-zinc-700 text-zinc-300',
  }

  if (loading) return <div className="text-center text-zinc-500 text-sm py-8">加载中...</div>

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex gap-1">
          <button onClick={() => setFilterType('')}
            className={`text-xs px-2 py-1 rounded ${!filterType ? 'bg-indigo-600 text-white' : 'bg-zinc-800 text-zinc-400 hover:text-zinc-200'}`}>
            全部
          </button>
          {ITEM_TYPES.map(t => (
            <button key={t} onClick={() => setFilterType(t)}
              className={`text-xs px-2 py-1 rounded ${filterType === t ? 'bg-indigo-600 text-white' : 'bg-zinc-800 text-zinc-400 hover:text-zinc-200'}`}>
              {t}
            </button>
          ))}
        </div>
        <button onClick={() => setShowForm(true)}
          className="bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded text-sm">
          + 新建物品
        </button>
      </div>

      {items.length === 0 ? (
        <p className="text-center text-zinc-500 text-sm py-8">暂无物品模板</p>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          {items.map(item => (
            <div key={item.id} className="bg-zinc-800 border border-zinc-700 rounded-lg p-3 group">
              <div className="flex items-start justify-between gap-1">
                <div>
                  <div className="text-sm font-medium">{item.name}</div>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${TYPE_COLORS[item.item_type] || TYPE_COLORS.misc}`}>
                    {item.item_type}
                  </span>
                </div>
                <div className="flex items-center gap-1">
                  <button onClick={() => handleGrant(item.id, item.name)} disabled={grantingId === item.id}
                    className="text-xs bg-emerald-700 hover:bg-emerald-600 disabled:bg-zinc-700 text-white px-1.5 py-0.5 rounded opacity-0 group-hover:opacity-100"
                    title="发放到当前会话">
                    {grantingId === item.id ? '...' : '发放'}
                  </button>
                  <button onClick={async () => {
                      const ok = await requestConfirm({ title: '删除物品模板', message: `确认删除「${item.name}」？`, confirmText: '删除', danger: true })
                      if (!ok) return
                      try { await api.deleteItemTemplate(item.id); notify.success('已删除物品模板'); load() }
                      catch (err) { notify.error(`删除失败：${err instanceof Error ? err.message : String(err)}`) }
                    }}
                    className="text-xs text-red-500 hover:text-red-400 opacity-0 group-hover:opacity-100">
                    ×
                  </button>
                </div>
              </div>
              {!!item.data_json?.description && (
                <p className="text-xs text-zinc-400 mt-1.5 line-clamp-2">
                  {String(item.data_json.description)}
                </p>
              )}
              {!!item.data_json?.tier && (
                <p className="text-xs text-zinc-500 mt-1">{String(item.data_json.tier)}</p>
              )}
            </div>
          ))}
        </div>
      )}
      {showForm && <ItemForm onClose={() => setShowForm(false)} onSaved={load} />}
    </div>
  )
}

// ── 主组件 ────────────────────────────────────────────────────────────────────
export const AssetLibrary: React.FC = () => {
  const [tab, setTab] = useState<AssetTab>('npcs')

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-4 mb-4">
        <h2 className="text-lg font-semibold">资产库</h2>
        <div className="flex gap-1">
          <button onClick={() => setTab('npcs')}
            className={`px-4 py-1.5 text-sm rounded transition-colors ${tab === 'npcs' ? 'bg-indigo-600 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}>
            NPC 模板
          </button>
          <button onClick={() => setTab('items')}
            className={`px-4 py-1.5 text-sm rounded transition-colors ${tab === 'items' ? 'bg-indigo-600 text-white' : 'text-zinc-400 hover:text-zinc-200'}`}>
            物品模板
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {tab === 'npcs' ? <NpcList /> : <ItemList />}
      </div>
    </div>
  )
}
