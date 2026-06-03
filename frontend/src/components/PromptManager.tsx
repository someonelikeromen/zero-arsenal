/**
 * PromptManager — 全局 Agent 提示词模板管理
 * 左侧分类，右侧编辑。支持启用/禁用、排序提示、重置默认。
 */
import React, { useEffect, useState } from 'react'
import { api, PromptTemplate } from '../lib/api'
import { notify } from '../stores/ui'
import { requestConfirm } from '../stores/confirm'

const AGENTS = [
  { id: 'dm', label: 'DM 裁判', icon: '⚖️' },
  { id: 'narrator', label: '叙述者', icon: '📖' },
  { id: 'npc', label: 'NPC', icon: '🎭' },
  { id: 'world', label: '世界观', icon: '🌍' },
  { id: 'style', label: '写作风格', icon: '✍️' },
  { id: 'rules', label: '规则系统', icon: '🎲' },
]

const PLACEHOLDERS = ['{{world_plugin}}', '{{character_name}}', '{{session_id}}', '{{chapter_index}}']

interface PromptCardProps {
  prompt: PromptTemplate
  onUpdate: (pid: string, update: Partial<PromptTemplate>) => void
  onDelete: (pid: string) => void
}

function PromptCard({ prompt, onUpdate, onDelete }: PromptCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [label, setLabel] = useState(prompt.label)
  const [content, setContent] = useState(prompt.content)

  const save = () => {
    onUpdate(prompt.id, { label, content })
    setEditing(false)
  }

  return (
    <div className={`border rounded-lg overflow-hidden transition-colors ${prompt.enabled ? 'border-zinc-700 bg-zinc-800' : 'border-zinc-800 bg-zinc-900 opacity-60'}`}>
      <div className="flex items-center gap-2 px-3 py-2.5">
        {/* 启用开关 */}
        <button onClick={() => onUpdate(prompt.id, { enabled: prompt.enabled ? 0 : 1 })}
          className={`w-8 h-4 rounded-full transition-colors shrink-0 ${prompt.enabled ? 'bg-indigo-600' : 'bg-zinc-700'}`}>
          <span className={`block w-3 h-3 rounded-full bg-white transition-transform mx-0.5 ${prompt.enabled ? 'translate-x-4' : 'translate-x-0'}`} />
        </button>

        <div className="flex-1 min-w-0 cursor-pointer" onClick={() => setExpanded(!expanded)}>
          {editing ? (
            <input value={label} onChange={e => setLabel(e.target.value)}
              onClick={e => e.stopPropagation()}
              className="bg-zinc-700 rounded px-2 py-0.5 text-sm w-full focus:outline-none" />
          ) : (
            <span className="text-sm font-medium">{prompt.label}</span>
          )}
        </div>

        <div className="flex gap-1 shrink-0">
          {editing ? (
            <>
              <button onClick={save} className="text-xs text-indigo-400 hover:text-indigo-300 px-2 py-1">保存</button>
              <button onClick={() => { setEditing(false); setLabel(prompt.label); setContent(prompt.content) }}
                className="text-xs text-zinc-500 hover:text-zinc-300 px-1">✕</button>
            </>
          ) : (
            <>
              <button onClick={() => { setEditing(true); setExpanded(true) }}
                className="text-xs text-zinc-500 hover:text-zinc-300 px-1">编辑</button>
              <button onClick={() => onDelete(prompt.id)}
                className="text-xs text-red-500 hover:text-red-400 px-1">删除</button>
            </>
          )}
          <button onClick={() => setExpanded(!expanded)} className="text-zinc-600 text-xs px-1">
            {expanded ? '▲' : '▼'}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-zinc-700 px-3 py-2.5 space-y-2">
          {editing ? (
            <>
              <div className="flex flex-wrap gap-1 mb-1">
                {PLACEHOLDERS.map(p => (
                  <button key={p} onClick={() => setContent(prev => prev + p)}
                    className="text-xs bg-zinc-700 hover:bg-zinc-600 text-zinc-300 px-1.5 py-0.5 rounded font-mono">
                    {p}
                  </button>
                ))}
              </div>
              <textarea value={content} onChange={e => setContent(e.target.value)} rows={6}
                className="w-full bg-zinc-700 rounded px-2 py-1.5 text-sm focus:outline-none resize-y font-mono leading-relaxed" />
            </>
          ) : (
            <pre className="text-xs text-zinc-400 whitespace-pre-wrap break-words leading-relaxed">
              {prompt.content || <span className="text-zinc-600 italic">（空内容）</span>}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

export const PromptManager: React.FC = () => {
  const [prompts, setPrompts] = useState<PromptTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [activeAgent, setActiveAgent] = useState('dm')
  const [resetting, setResetting] = useState(false)
  const [showNewForm, setShowNewForm] = useState(false)
  const [newLabel, setNewLabel] = useState('')
  const [newContent, setNewContent] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const res = await api.listPrompts()
      setPrompts(res.prompts)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const agentPrompts = prompts.filter(p => p.agent === activeAgent)

  const handleUpdate = async (pid: string, update: Partial<PromptTemplate>) => {
    await api.updatePrompt(pid, update as Parameters<typeof api.updatePrompt>[1])
    load()
  }

  const handleDelete = async (pid: string) => {
    const ok = await requestConfirm({
      title: '删除提示词',
      message: '确认删除该提示词条目？',
      confirmText: '删除',
      danger: true,
    })
    if (!ok) return
    try {
      await api.deletePrompt(pid)
      notify.success('已删除提示词条目')
      load()
    } catch (e) {
      notify.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const handleReset = async () => {
    const ok = await requestConfirm({
      title: '重置提示词',
      message: '确认重置所有提示词为内置默认值？这将删除所有自定义修改。',
      confirmText: '重置',
      danger: true,
    })
    if (!ok) return
    setResetting(true)
    try {
      await api.resetPrompts()
      notify.success('已重置为默认提示词')
      load()
    } catch (e) {
      notify.error(`重置失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setResetting(false)
    }
  }

  const handleAdd = async () => {
    if (!newLabel) return
    await api.createPrompt({ agent: activeAgent, label: newLabel, content: newContent })
    setNewLabel('')
    setNewContent('')
    setShowNewForm(false)
    load()
  }

  const agentInfo = AGENTS.find(a => a.id === activeAgent)
  const enabledCount = agentPrompts.filter(p => p.enabled).length

  return (
    <div className="h-full flex">
      {/* 左侧 Agent 分类 */}
      <div className="w-40 shrink-0 border-r border-zinc-800 pr-3 mr-4">
        <p className="text-xs text-zinc-600 mb-2 uppercase tracking-wider">Agent</p>
        <div className="space-y-0.5">
          {AGENTS.map(a => {
            const count = prompts.filter(p => p.agent === a.id).length
            const enabledCnt = prompts.filter(p => p.agent === a.id && p.enabled).length
            return (
              <button key={a.id} onClick={() => setActiveAgent(a.id)}
                className={`w-full text-left px-3 py-2 rounded text-sm flex items-center gap-2 transition-colors ${activeAgent === a.id ? 'bg-indigo-600/20 text-indigo-300 border-l-2 border-indigo-500' : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800'}`}>
                <span>{a.icon}</span>
                <span className="flex-1 truncate">{a.label}</span>
                <span className="text-xs text-zinc-600 shrink-0">{enabledCnt}/{count}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* 右侧内容 */}
      <div className="flex-1 min-w-0 flex flex-col">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="font-medium">{agentInfo?.icon} {agentInfo?.label}</h3>
            <p className="text-xs text-zinc-500">{enabledCount}/{agentPrompts.length} 条已启用</p>
          </div>
          <div className="flex gap-2">
            <button onClick={() => setShowNewForm(!showNewForm)}
              className="text-xs bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded">
              + 添加
            </button>
            <button onClick={handleReset} disabled={resetting}
              className="text-xs border border-zinc-700 hover:border-zinc-500 text-zinc-400 hover:text-zinc-200 px-3 py-1.5 rounded">
              {resetting ? '重置中...' : '重置默认'}
            </button>
          </div>
        </div>

        {showNewForm && (
          <div className="bg-zinc-800 border border-zinc-700 rounded-lg p-3 mb-3 space-y-2">
            <input value={newLabel} onChange={e => setNewLabel(e.target.value)}
              className="w-full bg-zinc-700 rounded px-2 py-1.5 text-sm focus:outline-none"
              placeholder="提示词标题" />
            <textarea value={newContent} onChange={e => setNewContent(e.target.value)} rows={4}
              className="w-full bg-zinc-700 rounded px-2 py-1.5 text-sm focus:outline-none resize-none font-mono"
              placeholder="提示词内容..." />
            <div className="flex gap-1">
              {PLACEHOLDERS.map(p => (
                <button key={p} onClick={() => setNewContent(prev => prev + p)}
                  className="text-xs bg-zinc-600 hover:bg-zinc-500 text-zinc-300 px-1.5 py-0.5 rounded font-mono">
                  {p}
                </button>
              ))}
            </div>
            <div className="flex gap-2">
              <button onClick={handleAdd} disabled={!newLabel}
                className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 text-white py-1.5 rounded text-sm">
                添加
              </button>
              <button onClick={() => setShowNewForm(false)} className="px-3 text-sm text-zinc-500 hover:text-zinc-300">
                取消
              </button>
            </div>
          </div>
        )}

        {loading ? (
          <div className="text-center text-zinc-500 text-sm py-8">加载中...</div>
        ) : agentPrompts.length === 0 ? (
          <div className="text-center text-zinc-500 text-sm py-8">暂无提示词条目</div>
        ) : (
          <div className="flex-1 overflow-y-auto space-y-2 pr-1">
            {agentPrompts.map(p => (
              <PromptCard key={p.id} prompt={p} onUpdate={handleUpdate} onDelete={handleDelete} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
