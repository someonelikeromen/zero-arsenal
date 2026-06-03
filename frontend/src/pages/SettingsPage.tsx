import React, { useState, useEffect } from 'react'
import { api } from '../lib/api'
import { notify, useUIStore } from '../stores/ui'

interface Props {
  onBack?: () => void
  embedded?: boolean  // true = 不显示顶栏和 min-h-screen，嵌入到 HomePage
}

// ── 数据类型 ──────────────────────────────────────────────────────────────────

interface AgentProfile {
  name: string
  model?: string
  temperature?: number
  description?: string
  [key: string]: unknown
}

interface Extension {
  key: string
  name?: string
  description?: string
  active?: boolean
  [key: string]: unknown
}

interface Tool {
  name: string
  tags?: string[]
  description?: string
  [key: string]: unknown
}

interface Skill {
  name: string
  description?: string
  [key: string]: unknown
}

// ── 标签颜色 ──────────────────────────────────────────────────────────────────

const TAG_COLOR: Record<string, string> = {
  read:      'bg-blue-900 text-blue-300',
  write:     'bg-orange-900 text-orange-300',
  dice:      'bg-purple-900 text-purple-300',
  memory:    'bg-green-900 text-green-300',
  character: 'bg-cyan-900 text-cyan-300',
}

function TagBadge({ tag }: { tag: string }) {
  const cls = TAG_COLOR[tag.toLowerCase()] ?? 'bg-zinc-700 text-zinc-300'
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${cls}`}>{tag}</span>
  )
}

// ── 通用加载/错误 helpers ──────────────────────────────────────────────────────

function LoadingRow() {
  return <div className="text-zinc-500 text-sm py-4 text-center">加载中...</div>
}

function ErrorRow({ msg }: { msg: string }) {
  return <div className="text-red-400 text-sm py-4 text-center">加载失败：{msg}</div>
}

// ── Tab 1: 模型配置（从 llm-routes 读取真实 agent 配置）────────────────────────

function AgentsTab() {
  const [routes, setRoutes] = useState<Record<string, AgentProfile>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')

  useEffect(() => {
    fetch('/api/config/llm-routes')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data) => {
        setRoutes((data.routes as Record<string, AgentProfile>) ?? {})
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingRow />
  if (error)   return <ErrorRow msg={error} />

  const agents = Object.entries(routes)
  if (!agents.length) return <div className="text-zinc-600 text-sm py-4 text-center">暂无数据</div>

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-zinc-700">
            <th className="text-left text-zinc-500 font-medium py-2 pr-4 w-36">Agent 名称</th>
            <th className="text-left text-zinc-500 font-medium py-2 pr-4 w-24">Provider</th>
            <th className="text-left text-zinc-500 font-medium py-2 pr-4">Model</th>
            <th className="text-left text-zinc-500 font-medium py-2 pr-4 w-20">Temp</th>
            <th className="text-left text-zinc-500 font-medium py-2">描述</th>
          </tr>
        </thead>
        <tbody>
          {agents.map(([name, p]) => (
            <tr key={name} className="border-b border-zinc-800 hover:bg-zinc-800/40 transition-colors">
              <td className="py-2 pr-4 text-zinc-200 font-medium font-mono">{name}</td>
              <td className="py-2 pr-4 text-zinc-400">{(p.provider as string) ?? 'deepseek'}</td>
              <td className="py-2 pr-4 text-indigo-300 font-mono">{p.model ?? '—'}</td>
              <td className="py-2 pr-4 text-zinc-400">
                {p.temperature !== undefined ? Number(p.temperature).toFixed(2) : '—'}
              </td>
              <td className="py-2 text-zinc-500 leading-relaxed">{p.description ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Tab 2: 扩展管理 ───────────────────────────────────────────────────────────

function ExtensionsTab() {
  const [exts, setExts] = useState<Extension[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')

  useEffect(() => {
    // 使用 api.listWorldPlugins 连接 /config/world-plugins 端点
    api.listWorldPlugins()
      .then((data) => {
        const list = Array.isArray(data) ? data : ((data as { plugins?: Extension[] }).plugins ?? [])
        setExts(list as Extension[])
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingRow />
  if (error)   return <ErrorRow msg={error} />
  if (!exts.length) return <div className="text-zinc-600 text-sm py-4 text-center">暂无扩展</div>

  return (
    <div className="space-y-2">
      {exts.map((ext, i) => (
        <div
          key={i}
          className="flex items-start gap-3 bg-zinc-800/50 border border-zinc-700/50 rounded-lg px-4 py-3"
        >
          <span
            className={`mt-0.5 w-2 h-2 rounded-full flex-shrink-0 ${
              ext.active !== false ? 'bg-green-500' : 'bg-zinc-600'
            }`}
          />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-zinc-200 text-sm font-medium">{ext.name ?? ext.key}</span>
              <span className="text-zinc-600 text-xs font-mono">{ext.key}</span>
            </div>
            {ext.description && (
              <div className="text-zinc-500 text-xs mt-0.5 leading-relaxed">{ext.description}</div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Tab 3: 工具注册 ───────────────────────────────────────────────────────────

function ToolsTab() {
  const [tools, setTools] = useState<Tool[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')

  useEffect(() => {
    fetch('/api/tools')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data) => {
        const list = Array.isArray(data) ? data : (data.tools ?? [])
        setTools(list)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingRow />
  if (error)   return <ErrorRow msg={error} />
  if (!tools.length) return <div className="text-zinc-600 text-sm py-4 text-center">暂无工具</div>

  return (
    <div className="space-y-2">
      {tools.map((tool, i) => {
        const tags: string[] = Array.isArray(tool.tags) ? tool.tags : []
        return (
          <div
            key={i}
            className="bg-zinc-800/50 border border-zinc-700/50 rounded-lg px-4 py-3 space-y-1.5"
          >
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-zinc-200 text-sm font-medium">{tool.name}</span>
              {tags.map((tag) => (
                <TagBadge key={tag} tag={tag} />
              ))}
            </div>
            {tool.description && (
              <div className="text-zinc-500 text-xs leading-relaxed">{tool.description}</div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Tab 4: 技能库 ─────────────────────────────────────────────────────────────

function SkillsTab() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')

  useEffect(() => {
    fetch('/api/engine/skills')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data) => {
        const list = Array.isArray(data) ? data : (data.skills ?? [])
        setSkills(list)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingRow />
  if (error)   return <ErrorRow msg={error} />
  if (!skills.length) return <div className="text-zinc-600 text-sm py-4 text-center">暂无技能</div>

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
      {skills.map((sk, i) => {
        const preview = sk.description
          ? sk.description.slice(0, 50) + (sk.description.length > 50 ? '…' : '')
          : ''
        return (
          <div
            key={i}
            className="bg-zinc-800/50 border border-zinc-700/50 rounded-lg px-3 py-2.5 space-y-0.5"
          >
            <div className="text-zinc-200 text-xs font-medium">{sk.name}</div>
            {preview && (
              <div className="text-zinc-600 text-xs leading-relaxed">{preview}</div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── LLM 路由编辑 Tab ──────────────────────────────────────────────────────────

interface LLMRoute {
  provider: string
  model: string
  temperature?: number
  max_tokens?: number
}

function LlmRoutesTab() {
  const [routes, setRoutes] = useState<Record<string, LLMRoute>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<string | null>(null)
  const [editAgent, setEditAgent] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<LLMRoute>({ provider: 'deepseek', model: 'deepseek-chat' })

  useEffect(() => {
    fetch('/api/config/llm-routes')
      .then(r => r.json())
      .then(d => setRoutes(d.routes ?? {}))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const startEdit = (agent: string) => {
    setEditAgent(agent)
    setEditForm(routes[agent] ?? { provider: 'deepseek', model: 'deepseek-chat' })
  }

  const save = async () => {
    if (!editAgent) return
    setSaving(editAgent)
    try {
      const resp = await fetch('/api/config/llm-routes', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent: editAgent, ...editForm }),
      })
      if (resp.ok) {
        setRoutes(prev => ({ ...prev, [editAgent]: { ...editForm } }))
        setEditAgent(null)
      }
    } finally {
      setSaving(null)
    }
  }

  const COMMON_AGENTS = ['narrator', 'narrator_plan', 'dm', 'rules', 'style', 'npc', 'world', 'chronicler']
  const allAgents = Array.from(new Set([...COMMON_AGENTS, ...Object.keys(routes)]))

  if (loading) return <LoadingRow />

  return (
    <div className="space-y-2">
      <p className="text-xs text-zinc-500 mb-3">
        修改后立即生效，无需重启服务器。空 agent 使用默认配置（deepseek-chat）。
      </p>
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-zinc-700">
            <th className="text-left text-zinc-500 py-2 pr-4 w-32">Agent</th>
            <th className="text-left text-zinc-500 py-2 pr-4">Provider</th>
            <th className="text-left text-zinc-500 py-2 pr-4">Model</th>
            <th className="text-left text-zinc-500 py-2 pr-4 w-20">Temp</th>
            <th className="py-2 w-16"></th>
          </tr>
        </thead>
        <tbody>
          {allAgents.map(agent => {
            const r = routes[agent]
            const isEditing = editAgent === agent
            return (
              <tr key={agent} className="border-b border-zinc-800">
                <td className="py-2 pr-4 text-zinc-200 font-medium font-mono">{agent}</td>
                {isEditing ? (
                  <>
                    <td className="py-1 pr-2">
                      <input
                        className="bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-xs w-full focus:outline-none focus:border-indigo-500"
                        value={editForm.provider}
                        placeholder="deepseek"
                        onChange={e => setEditForm(f => ({ ...f, provider: e.target.value }))}
                      />
                    </td>
                    <td className="py-1 pr-2">
                      <input
                        className="bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-xs w-full focus:outline-none focus:border-indigo-500"
                        value={editForm.model}
                        placeholder="deepseek-chat"
                        onChange={e => setEditForm(f => ({ ...f, model: e.target.value }))}
                      />
                    </td>
                    <td className="py-1 pr-2">
                      <div className="flex gap-1">
                        <input
                          type="number" step="0.05" min="0" max="2"
                          className="bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-xs w-16 focus:outline-none focus:border-indigo-500"
                          value={editForm.temperature ?? ''}
                          placeholder="0.7"
                          onChange={e => setEditForm(f => ({ ...f, temperature: parseFloat(e.target.value) || undefined }))}
                          title="Temperature"
                        />
                        <input
                          type="number" step="256" min="256" max="8192"
                          className="bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-xs w-16 focus:outline-none focus:border-indigo-500"
                          value={editForm.max_tokens ?? ''}
                          placeholder="2048"
                          onChange={e => setEditForm(f => ({ ...f, max_tokens: parseInt(e.target.value) || undefined }))}
                          title="Max Tokens"
                        />
                      </div>
                    </td>
                    <td className="py-1 flex gap-1">
                      <button
                        onClick={save}
                        disabled={saving === agent}
                        className="px-2 py-1 bg-indigo-600 text-white rounded text-xs hover:bg-indigo-500 disabled:opacity-50"
                      >
                        {saving === agent ? '...' : '保存'}
                      </button>
                      <button onClick={() => setEditAgent(null)} className="px-2 py-1 bg-zinc-700 text-zinc-300 rounded text-xs hover:bg-zinc-600">
                        取消
                      </button>
                    </td>
                  </>
                ) : (
                  <>
                    <td className="py-2 pr-4 text-zinc-400">{r?.provider ?? <span className="text-zinc-600">default</span>}</td>
                    <td className="py-2 pr-4 text-indigo-300 font-mono">{r?.model ?? <span className="text-zinc-600">deepseek-chat</span>}</td>
                    <td className="py-2 pr-4 text-zinc-400">
                      <span title="temperature">{r?.temperature?.toFixed(2) ?? '—'}</span>
                      {r?.max_tokens && <span className="text-zinc-600 ml-1 text-[10px]">/{r.max_tokens}t</span>}
                    </td>
                    <td className="py-2">
                      <button
                        onClick={() => startEdit(agent)}
                        className="px-2 py-1 bg-zinc-700 text-zinc-300 rounded text-xs hover:bg-zinc-600"
                      >
                        编辑
                      </button>
                    </td>
                  </>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}


// ── API Key 管理 Tab ──────────────────────────────────────────────────────────

interface KeyStatus { configured: boolean; preview: string }
const PROVIDERS = ['deepseek', 'openai', 'anthropic', 'cohere', 'groq'] as const

function ApiKeysTab() {
  const [keys, setKeys]           = useState<Record<string, KeyStatus>>({})
  const [loading, setLoading]     = useState(true)
  const [editProvider, setEditProvider] = useState<string | null>(null)
  const [editKey, setEditKey]     = useState('')
  const [saving, setSaving]       = useState<string | null>(null)
  const [msg, setMsg]             = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    fetch('/api/config/api-keys')
      .then(r => r.json())
      .then(d => setKeys(d.keys ?? {}))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const save = async (provider: string) => {
    if (!editKey.trim()) return
    setSaving(provider)
    setMsg(null)
    try {
      const res = await fetch('/api/config/api-keys', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, api_key: editKey.trim() }),
      })
      const data = await res.json() as { ok?: boolean; warning?: string }
      if (data.ok) {
        setKeys(prev => ({ ...prev, [provider]: { configured: true, preview: editKey.slice(0, 8) + '...' } }))
        setEditProvider(null)
        setEditKey('')
        setMsg({ ok: true, text: data.warning ? `已保存（警告：${data.warning}）` : '✓ 已保存并立即生效' })
      }
    } catch (e) {
      setMsg({ ok: false, text: `保存失败：${(e as Error).message}` })
    } finally {
      setSaving(null)
    }
  }

  if (loading) return <LoadingRow />

  return (
    <div className="space-y-3">
      <p className="text-xs text-zinc-500">
        配置 LLM 服务商 API Key。Key 保存至 <code className="text-zinc-400">.env</code> 文件并立即生效，无需重启。
      </p>
      {msg && (
        <div className={`text-xs px-3 py-2 rounded ${msg.ok ? 'bg-green-900/40 text-green-300' : 'bg-red-900/40 text-red-300'}`}>
          {msg.text}
        </div>
      )}
      <div className="space-y-2">
        {PROVIDERS.map(provider => {
          const status = keys[provider]
          const isEditing = editProvider === provider
          return (
            <div key={provider} className="flex items-center gap-3 bg-zinc-800/50 border border-zinc-700/50 rounded-lg px-4 py-2.5">
              <div className="flex items-center gap-2 w-28 flex-shrink-0">
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${status?.configured ? 'bg-green-500' : 'bg-zinc-600'}`} />
                <span className="text-zinc-200 text-sm font-medium">{provider}</span>
              </div>
              {isEditing ? (
                <>
                  <input
                    type="password"
                    autoFocus
                    value={editKey}
                    onChange={e => setEditKey(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') save(provider); if (e.key === 'Escape') { setEditProvider(null); setEditKey('') } }}
                    placeholder="粘贴 API Key..."
                    className="flex-1 bg-zinc-900 border border-zinc-600 rounded px-2 py-1 text-xs focus:outline-none focus:border-indigo-500 font-mono"
                  />
                  <button
                    onClick={() => save(provider)}
                    disabled={saving === provider || !editKey.trim()}
                    className="px-3 py-1 bg-indigo-600 text-white text-xs rounded hover:bg-indigo-500 disabled:opacity-50"
                  >
                    {saving === provider ? '...' : '保存'}
                  </button>
                  <button
                    onClick={() => { setEditProvider(null); setEditKey('') }}
                    className="px-3 py-1 bg-zinc-700 text-zinc-300 text-xs rounded hover:bg-zinc-600"
                  >
                    取消
                  </button>
                </>
              ) : (
                <>
                  <span className="flex-1 text-xs font-mono text-zinc-500">
                    {status?.configured ? status.preview : '(未配置)'}
                  </span>
                  <button
                    onClick={() => { setEditProvider(provider); setEditKey('') }}
                    className="px-3 py-1 bg-zinc-700 text-zinc-300 text-xs rounded hover:bg-zinc-600"
                  >
                    {status?.configured ? '更新' : '配置'}
                  </button>
                </>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}


// ── Tab: 记忆子系统健康状态 ───────────────────────────────────────────────────

function MemoryHealthTab() {
  const [data, setData] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refresh = () => {
    setLoading(true)
    setError('')
    api.getMemoryHealth()
      .then((res) => setData(res.memory ?? {}))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { refresh() }, [])

  if (loading) return <LoadingRow />
  if (error) return <ErrorRow msg={error} />

  const mode = (data?.mode as string) ?? 'unknown'
  const isFullMode = data?.is_full_mode === true

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${isFullMode ? 'bg-green-500' : 'bg-yellow-500'}`} />
          <span className="text-sm font-medium text-zinc-200">
            记忆模式：{isFullMode ? '完整模式' : '降级模式'}
          </span>
          <span className="text-xs text-zinc-500 font-mono">{mode}</span>
        </div>
        <button onClick={refresh}
          className="text-xs text-zinc-500 hover:text-zinc-300 px-2 py-1 rounded hover:bg-zinc-800">
          刷新
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {['engine', 'consolidator', 'extractor', 'retriever', 'rollback', 'embedding_client'].map((comp) => {
          const val = data?.[comp] as string | undefined
          const ok = val === 'available'
          return (
            <div key={comp} className="flex items-center gap-2 bg-zinc-800/50 border border-zinc-700/50 rounded px-3 py-2">
              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${ok ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="text-xs text-zinc-300 font-mono flex-1">{comp}</span>
              <span className={`text-xs ${ok ? 'text-green-400' : 'text-red-400'}`}>
                {ok ? '可用' : val?.replace('unavailable: ', '') ?? '未知'}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}


// ── Tab: 外观 / 主题 ──────────────────────────────────────────────────────────

function AppearanceTab() {
  const theme = useUIStore(s => s.theme)
  const setTheme = useUIStore(s => s.setTheme)

  const OPTIONS: { id: 'light' | 'dark' | 'system'; label: string; desc: string; preview: string }[] = [
    { id: 'dark', label: '暗色', desc: '默认深色主题，适合长时间阅读', preview: 'bg-zinc-900 border-zinc-700' },
    { id: 'light', label: '亮色', desc: '浅色主题（部分组件仍以深色为主）', preview: 'bg-zinc-100 border-zinc-300' },
    { id: 'system', label: '跟随系统', desc: '根据操作系统的明暗偏好自动切换', preview: 'bg-gradient-to-br from-zinc-900 to-zinc-100 border-zinc-500' },
  ]

  return (
    <div className="space-y-3">
      <p className="text-xs text-zinc-500">选择界面主题。设置会立即生效并持久化保存。</p>
      <div className="grid grid-cols-3 gap-3">
        {OPTIONS.map(opt => (
          <button
            key={opt.id}
            onClick={() => setTheme(opt.id)}
            className={`text-left rounded-lg border p-3 transition-colors ${
              theme === opt.id ? 'border-indigo-500 bg-indigo-900/20' : 'border-zinc-700 bg-zinc-800/40 hover:border-zinc-600'
            }`}
          >
            <div className={`h-16 rounded border mb-2 ${opt.preview}`} />
            <div className="text-sm font-medium text-zinc-200 flex items-center gap-1">
              {opt.label}
              {theme === opt.id && <span className="text-indigo-400 text-xs">✓</span>}
            </div>
            <div className="text-[10px] text-zinc-500 mt-0.5 leading-relaxed">{opt.desc}</div>
          </button>
        ))}
      </div>
    </div>
  )
}


// ── Tab: 规则管理（激活/停用） ─────────────────────────────────────────────────

interface EngineRule {
  id: string
  name?: string
  description?: string
  enabled?: boolean
  active?: boolean
}

function RulesTab() {
  const [rules, setRules] = useState<EngineRule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [toggling, setToggling] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    api.listEngineRules()
      .then(d => setRules(d.rules ?? []))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const toggle = async (rule: EngineRule) => {
    const next = !(rule.enabled ?? rule.active ?? true)
    setToggling(rule.id)
    try {
      await api.activateRule(rule.id, next)
      setRules(prev => prev.map(r => r.id === rule.id ? { ...r, enabled: next, active: next } : r))
      notify.success(`规则「${rule.name ?? rule.id}」已${next ? '启用' : '停用'}`)
    } catch (e) {
      notify.error(`切换失败：${(e as Error).message}`)
    } finally {
      setToggling(null)
    }
  }

  if (loading) return <LoadingRow />
  if (error) return <ErrorRow msg={error} />
  if (!rules.length) return <div className="text-zinc-600 text-sm py-4 text-center">暂无可管理的规则</div>

  return (
    <div className="space-y-2">
      <p className="text-xs text-zinc-500 mb-2">运行时激活/停用扩展规则，立即生效。</p>
      {rules.map(rule => {
        const on = rule.enabled ?? rule.active ?? true
        return (
          <div key={rule.id} className="flex items-start gap-3 bg-zinc-800/50 border border-zinc-700/50 rounded-lg px-4 py-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-zinc-200 text-sm font-medium">{rule.name ?? rule.id}</span>
                <span className="text-zinc-600 text-xs font-mono">{rule.id}</span>
              </div>
              {rule.description && (
                <div className="text-zinc-500 text-xs mt-0.5 leading-relaxed">{rule.description}</div>
              )}
            </div>
            <button
              onClick={() => toggle(rule)}
              disabled={toggling === rule.id}
              className={`relative w-10 h-5 rounded-full transition-colors flex-shrink-0 ${on ? 'bg-indigo-600' : 'bg-zinc-700'} disabled:opacity-50`}
              title={on ? '点击停用' : '点击启用'}
            >
              <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-all ${on ? 'left-5' : 'left-0.5'}`} />
            </button>
          </div>
        )
      })}
    </div>
  )
}


// ── Tab: MCP 服务器 ───────────────────────────────────────────────────────────

interface McpServer {
  id: string
  command?: string
  args?: string[]
  enabled?: boolean
}

function McpTab() {
  const [servers, setServers] = useState<McpServer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    api.listMcpServers()
      .then(d => setServers(d.servers ?? []))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const connect = async (s: McpServer) => {
    setBusy(s.id)
    try {
      const res = await api.connectMcp({ server_id: s.id, command: s.command ?? '', args: s.args ?? [], enabled: true })
      notify.success(`已连接「${s.id}」，注册 ${res.registered} 个工具`)
    } catch (e) {
      notify.error(`连接失败：${(e as Error).message}`)
    } finally {
      setBusy(null)
    }
  }

  const disconnect = async (s: McpServer) => {
    setBusy(s.id)
    try {
      const res = await api.disconnectMcp(s.id)
      notify.success(`已断开「${s.id}」，移除 ${res.count} 个工具`)
    } catch (e) {
      notify.error(`断开失败：${(e as Error).message}`)
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <LoadingRow />
  if (error) return <ErrorRow msg={error} />

  return (
    <div className="space-y-2">
      <p className="text-xs text-zinc-500 mb-2">
        MCP 服务器在 <code className="text-zinc-400">config/mcp.json</code> 中配置。可在此连接/断开以动态注册工具。
      </p>
      {servers.length === 0 ? (
        <div className="text-zinc-600 text-sm py-4 text-center">暂无 MCP 服务器配置</div>
      ) : servers.map(s => (
        <div key={s.id} className="flex items-center gap-3 bg-zinc-800/50 border border-zinc-700/50 rounded-lg px-4 py-3">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${s.enabled !== false ? 'bg-green-500' : 'bg-zinc-600'}`} />
          <div className="min-w-0 flex-1">
            <div className="text-zinc-200 text-sm font-medium">{s.id}</div>
            <div className="text-zinc-600 text-xs font-mono truncate">{s.command} {(s.args ?? []).join(' ')}</div>
          </div>
          <button onClick={() => connect(s)} disabled={busy === s.id}
            className="px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 text-white text-xs rounded disabled:opacity-50">
            连接
          </button>
          <button onClick={() => disconnect(s)} disabled={busy === s.id}
            className="px-2.5 py-1 bg-zinc-700 hover:bg-zinc-600 text-zinc-300 text-xs rounded disabled:opacity-50">
            断开
          </button>
        </div>
      ))}
    </div>
  )
}


// ── 标签页定义 ────────────────────────────────────────────────────────────────

type SettingsGroup = 'basic' | 'advanced' | 'experimental'

const GROUP_META: { id: SettingsGroup; label: string; hint: string }[] = [
  { id: 'basic',        label: '基础设置',   hint: '日常使用所需的核心配置' },
  { id: 'advanced',     label: '高级设置',   hint: '路由 / 规则 / 工具 / 技能等进阶项' },
  { id: 'experimental', label: '实验性 ⚠️', hint: '不稳定或需谨慎使用的功能' },
]

const TABS = [
  { key: 'appearance', label: '外观',      group: 'basic',        component: AppearanceTab },
  { key: 'agents',     label: '模型配置',  group: 'basic',        component: AgentsTab },
  { key: 'apikeys',    label: 'API Keys',  group: 'basic',        component: ApiKeysTab },
  { key: 'llm',        label: 'LLM 路由',  group: 'advanced',     component: LlmRoutesTab },
  { key: 'extensions', label: '扩展管理',  group: 'advanced',     component: ExtensionsTab },
  { key: 'rules',      label: '规则管理',  group: 'advanced',     component: RulesTab },
  { key: 'tools',      label: '工具注册',  group: 'advanced',     component: ToolsTab },
  { key: 'skills',     label: '技能库',    group: 'advanced',     component: SkillsTab },
  { key: 'memory',     label: '记忆健康',  group: 'advanced',     component: MemoryHealthTab },
  { key: 'mcp',        label: 'MCP 工具',  group: 'experimental', component: McpTab },
] as const

type TabKey = typeof TABS[number]['key']

// ── 主页面 ────────────────────────────────────────────────────────────────────

export const SettingsPage: React.FC<Props> = ({ onBack, embedded = false }) => {
  const [activeTab, setActiveTab] = useState<TabKey>('agents')

  const ActiveComponent = TABS.find((t) => t.key === activeTab)!.component

  if (embedded) {
    return (
      <div className="h-full flex flex-col text-zinc-100">
        {/* 分层标签切换栏 */}
        <div className="pb-3 border-b border-zinc-800 flex-shrink-0 space-y-2">
          {GROUP_META.map(group => (
            <div key={group.id} className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-wide text-zinc-600 w-20 shrink-0" title={group.hint}>
                {group.label}
              </span>
              {TABS.filter(t => t.group === group.id).map(({ key, label }) => (
                <button
                  key={key}
                  onClick={() => setActiveTab(key)}
                  className={`px-3 py-1.5 text-xs font-medium rounded transition-colors ${
                    activeTab === key
                      ? 'bg-indigo-600 text-white'
                      : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          ))}
        </div>
        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto pt-4">
          <div className="max-w-4xl">
            <ActiveComponent />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col">
      {/* 顶栏 */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-zinc-800 flex-shrink-0">
        <button
          onClick={onBack}
          className="text-zinc-500 hover:text-zinc-300 text-sm transition-colors"
        >
          ← 返回
        </button>
        <span className="text-zinc-700">|</span>
        <span className="text-zinc-300 font-semibold text-sm">设置</span>
      </div>

      {/* 分层标签切换栏 */}
      <div className="px-6 pt-4 pb-2 border-b border-zinc-800 flex-shrink-0 space-y-2">
        {GROUP_META.map(group => (
          <div key={group.id} className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] uppercase tracking-wide text-zinc-600 w-24 shrink-0" title={group.hint}>
              {group.label}
            </span>
            {TABS.filter(t => t.group === group.id).map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`px-3 py-1.5 text-sm font-medium rounded transition-colors ${
                  activeTab === key
                    ? 'bg-indigo-600 text-white'
                    : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        ))}
      </div>

      {/* 内容区 */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-4xl">
          <ActiveComponent />
        </div>
      </div>
    </div>
  )
}
