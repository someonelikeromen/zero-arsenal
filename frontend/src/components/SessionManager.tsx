/**
 * SessionManager — 会话存档管理
 * 列表 + 搜索/筛选 + 重命名/删除/导出
 */
import React, { useEffect, useState } from 'react'
import { api, Session } from '../lib/api'
import { notify } from '../stores/ui'
import { requestConfirm } from '../stores/confirm'

interface Props {
  onOpenSession: (id: string) => void
}

export const SessionManager: React.FC<Props> = ({ onOpenSession }) => {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterPlugin, setFilterPlugin] = useState('')
  const [availablePlugins, setAvailablePlugins] = useState<{ key: string; name: string }[]>([])
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const res = await api.listSessions()
      setSessions(res.items || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    api.listWorldPlugins().then(r => setAvailablePlugins(r.plugins)).catch(() => {})
  }, [])

  const filtered = sessions.filter(s => {
    if (!s.session_id) return false
    const matchSearch = !search || (s.title ?? '').toLowerCase().includes(search.toLowerCase())
    const matchPlugin = !filterPlugin || s.plugin_key === filterPlugin
    return matchSearch && matchPlugin
  })

  const handleDelete = async (id: string, title: string) => {
    const ok = await requestConfirm({
      title: '删除会话',
      message: `确认删除会话「${title}」？此操作不可撤销。`,
      confirmText: '删除',
      danger: true,
    })
    if (!ok) return
    try {
      await api.deleteSession(id)
      notify.success(`已删除会话「${title}」`)
      load()
    } catch (e) {
      notify.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const handleStartRename = (s: Session) => {
    setRenamingId(s.session_id)
    setRenameValue(s.title)
  }

  const handleRename = async (id: string) => {
    if (!renameValue.trim()) return
    try {
      await api.patch(`/sessions/${id}`, { title: renameValue.trim() })
      setRenamingId(null)
      notify.success('已重命名会话')
      load()
    } catch (e) {
      notify.error(`重命名失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const handleExport = async (s: Session) => {
    const sessionId = s.session_id
    const exportData: Record<string, unknown> = { session: s }

    // 补充导出 messages / parts / character
    try {
      const [messagesRes, partsRes, charRes] = await Promise.allSettled([
        api.getMessages(sessionId),
        api.getParts(sessionId),
        api.getCharacter(sessionId),
      ])
      if (messagesRes.status === 'fulfilled') exportData.messages = messagesRes.value
      if (partsRes.status === 'fulfilled') exportData.parts = partsRes.value
      if (charRes.status === 'fulfilled') exportData.character = charRes.value
    } catch {
      // 若 API 不可用，仍导出会话基本信息
    }

    const data = JSON.stringify(exportData, null, 2)
    const blob = new Blob([data], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `session_${(sessionId ?? 'unknown').slice(0, 8)}.json`
    a.click()
    URL.revokeObjectURL(url)
    notify.success('会话已导出为 JSON')
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text).catch(() => {})
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">存档管理</h2>
        <span className="text-xs text-zinc-500">{filtered.length} / {sessions.length} 条</span>
      </div>

      {/* 搜索栏 */}
      <div className="flex gap-2 mb-4">
        <input value={search} onChange={e => setSearch(e.target.value)}
          className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
          placeholder="搜索会话标题..." />
        <select value={filterPlugin} onChange={e => setFilterPlugin(e.target.value)}
          className="bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none">
          <option value="">全部插件</option>
          {availablePlugins.map(p => (
            <option key={p.key} value={p.key}>{p.name || p.key}</option>
          ))}
        </select>
        <button onClick={load} className="bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 rounded px-3 py-2 text-sm text-zinc-400">
          ↺
        </button>
      </div>

      {loading ? (
        <div className="flex-1 flex items-center justify-center text-zinc-500 text-sm">加载中...</div>
      ) : filtered.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-zinc-500 text-sm">
          {sessions.length === 0 ? '暂无会话存档' : '没有匹配的会话'}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto space-y-2 pr-1">
          {filtered.map(s => (
            <div key={s.session_id}
              className="bg-zinc-800 border border-zinc-700 rounded-lg px-4 py-3 group hover:border-zinc-600 transition-colors">
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  {renamingId === s.session_id ? (
                    <div className="flex gap-2 mb-1">
                      <input value={renameValue} onChange={e => setRenameValue(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') handleRename(s.session_id); if (e.key === 'Escape') setRenamingId(null) }}
                        className="flex-1 bg-zinc-700 rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
                        autoFocus />
                      <button onClick={() => handleRename(s.session_id)} className="text-xs text-indigo-400 hover:text-indigo-300 px-2">✓</button>
                      <button onClick={() => setRenamingId(null)} className="text-xs text-zinc-500 hover:text-zinc-300 px-1">✕</button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium text-sm">{s.title}</span>
                      <button onClick={() => handleStartRename(s)} className="text-xs text-zinc-600 hover:text-zinc-400 opacity-0 group-hover:opacity-100">✏</button>
                    </div>
                  )}
                  <div className="flex items-center gap-3 text-xs text-zinc-500">
                    <span className="bg-zinc-700 text-zinc-400 px-1.5 py-0.5 rounded">{s.plugin_key}</span>
                    <span>{s.agent_profile}</span>
                    <span>{new Date(s.created_at).toLocaleString()}</span>
                  </div>
                  <div className="mt-1">
                    <button onClick={() => copyToClipboard(s.session_id)}
                      className="text-xs text-zinc-600 hover:text-zinc-400 font-mono truncate max-w-xs">
                      {s.session_id?.slice(0, 12)}...
                    </button>
                  </div>
                </div>
                <div className="flex flex-col gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button onClick={() => onOpenSession(s.session_id)}
                    className="text-xs bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1 rounded">
                    打开
                  </button>
                  <button onClick={() => handleExport(s)}
                    className="text-xs border border-zinc-600 hover:border-zinc-400 text-zinc-400 hover:text-zinc-200 px-3 py-1 rounded">
                    导出
                  </button>
                  <button onClick={() => handleDelete(s.session_id, s.title)}
                    className="text-xs text-red-500 hover:text-red-400 px-3 py-1 rounded border border-red-900 hover:border-red-700">
                    删除
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
