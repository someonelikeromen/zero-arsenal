/**
 * ExtensionsPanel — 已加载插件 + 引擎规则总览
 * Plugin = 行为包（修改角色卡 schema、注入提示词、注册生命周期钩子）
 * World  = 内容容器（世界设定、NPC、背景资料），在「世界」Tab 管理
 */
import { useEffect, useState, useCallback } from 'react'
import { api } from '../lib/api'
import { notify } from '../stores/ui'

interface Extension {
  key: string
  name: string
  description?: string
  agent_profile?: string
}

interface EngineRule {
  rule_id: string
  title?: string
  description?: string
  trigger?: string
  applicable_agents?: string[]
  priority?: number
  enabled?: boolean
}

export default function ExtensionsPanel() {
  const [extensions, setExtensions] = useState<Extension[]>([])
  const [rules, setRules] = useState<EngineRule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toggling, setToggling] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [extRes, ruleRes] = await Promise.all([
        api.listExtensions().catch(() => ({ extensions: [], count: 0 })),
        api.listEngineRules().catch(() => ({ rules: [], count: 0 })),
      ])
      setExtensions(extRes.extensions ?? [])
      setRules(ruleRes.rules ?? [])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const toggleRule = async (rule: EngineRule) => {
    const next = !(rule.enabled ?? true)
    setToggling(rule.rule_id)
    try {
      await api.activateRule(rule.rule_id, next)
      setRules(prev => prev.map(r => r.rule_id === rule.rule_id ? { ...r, enabled: next } : r))
      notify.success(`规则「${rule.title ?? rule.rule_id}」已${next ? '启用' : '停用'}`)
    } catch (e) {
      notify.error(`切换失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setToggling(null)
    }
  }

  if (loading) return <div className="text-zinc-500 text-sm py-8 text-center">加载扩展中…</div>
  if (error) return <div className="text-red-400 text-sm py-8 text-center">加载失败：{error}</div>

  return (
    <div className="max-w-3xl mx-auto space-y-8 pt-2">
      {/* 插件 */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-lg font-bold">插件</h2>
            <p className="text-xs text-zinc-500">行为包 — 修改角色卡 schema / 注入提示词 / 生命周期钩子。新增见 docs/CONTRIBUTING.md</p>
          </div>
          <button onClick={load} className="text-xs text-zinc-400 hover:text-zinc-200 px-2 py-1 rounded border border-zinc-700">
            刷新
          </button>
        </div>
        {extensions.length === 0 ? (
          <div className="border border-dashed border-zinc-700 rounded p-6 text-center text-sm text-zinc-500">
            未发现已加载扩展
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {extensions.map(ext => (
              <div key={ext.key} className="bg-zinc-900 border border-zinc-800 rounded-lg p-3.5">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-sm">{ext.name}</span>
                  <span className="text-[10px] bg-zinc-700 text-zinc-400 px-1.5 rounded">{ext.key}</span>
                </div>
                <p className="text-xs text-zinc-500 line-clamp-3">{ext.description || '（无描述）'}</p>
                {ext.agent_profile && (
                  <div className="mt-2 text-[10px] text-zinc-600">权限模式：{ext.agent_profile}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 引擎规则开关 */}
      <section>
        <h2 className="text-lg font-bold mb-1">引擎规则</h2>
        <p className="text-xs text-zinc-500 mb-3">扩展注册的规则，可运行时启用/停用</p>
        {rules.length === 0 ? (
          <div className="border border-dashed border-zinc-700 rounded p-6 text-center text-sm text-zinc-500">
            暂无可管理的规则
          </div>
        ) : (
          <div className="space-y-2">
            {rules.map(rule => {
              const on = rule.enabled ?? true
              return (
                <div key={rule.rule_id} className="flex items-center justify-between bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-3">
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">{rule.title ?? rule.rule_id}</div>
                    <div className="text-xs text-zinc-500 truncate">
                      {rule.rule_id}
                      {rule.applicable_agents && rule.applicable_agents.length > 0 && ` · ${rule.applicable_agents.join('/')}`}
                    </div>
                  </div>
                  <button
                    onClick={() => toggleRule(rule)}
                    disabled={toggling === rule.rule_id}
                    className={`shrink-0 ml-3 relative w-11 h-6 rounded-full transition-colors ${on ? 'bg-indigo-600' : 'bg-zinc-700'} disabled:opacity-50`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${on ? 'translate-x-5' : ''}`} />
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}
