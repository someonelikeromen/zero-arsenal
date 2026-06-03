/**
 * ScraperRulesPanel — 网页抓取站点规则管理面板
 * 让用户可视化地添加/编辑/删除/启用站点抓取规则
 */
import { useEffect, useState, useCallback } from 'react'
import { api, ScraperRule } from '../lib/api'
import { notify } from '../stores/ui'
import { requestConfirm } from '../stores/confirm'

const ENGINE_OPTIONS = ['httpx', 'playwright'] as const

const DEFAULT_RULE: ScraperRule = {
  domain: '',
  alias: '',
  engine: 'httpx',
  content_selectors: [],
  wait_ms: 2000,
  max_chars: 10000,
  enabled: true,
  notes: '',
}

export default function ScraperRulesPanel() {
  const [rules, setRules] = useState<ScraperRule[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const [editIdx, setEditIdx] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState<ScraperRule>(DEFAULT_RULE)
  const [showAdd, setShowAdd] = useState(false)
  const [newRule, setNewRule] = useState<ScraperRule>({ ...DEFAULT_RULE })

  const flash = (text: string, ok = true) => {
    setMsg({ text, ok })
    setTimeout(() => setMsg(null), 3000)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.listScraperRules()
      setRules(data.rules)
    } catch (e) {
      flash('加载规则失败', false)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const save = async (updated: ScraperRule[]) => {
    setSaving(true)
    try {
      await api.updateScraperRules(updated)
      setRules(updated)
      flash('已保存')
    } catch {
      flash('保存失败', false)
    } finally {
      setSaving(false)
    }
  }

  const toggleEnabled = async (idx: number) => {
    const updated = rules.map((r, i) => i === idx ? { ...r, enabled: !r.enabled } : r)
    await save(updated)
  }

  const deleteRule = async (idx: number) => {
    const ok = await requestConfirm({
      title: '删除站点规则',
      message: `删除站点规则「${rules[idx].alias || rules[idx].domain}」？`,
      confirmText: '删除',
      danger: true,
    })
    if (!ok) return
    try {
      await save(rules.filter((_, i) => i !== idx))
      notify.success('已删除站点规则')
    } catch (e) {
      notify.error(`删除失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const startEdit = (idx: number) => {
    setEditIdx(idx)
    setEditDraft({ ...rules[idx] })
  }

  const commitEdit = async () => {
    if (editIdx === null) return
    const updated = rules.map((r, i) => i === editIdx ? editDraft : r)
    await save(updated)
    setEditIdx(null)
  }

  const addRule = async () => {
    if (!newRule.domain.trim()) { flash('域名不能为空', false); return }
    const exists = rules.some(r => r.domain === newRule.domain.trim())
    if (exists) { flash('该域名规则已存在', false); return }
    await save([...rules, { ...newRule, domain: newRule.domain.trim() }])
    setShowAdd(false)
    setNewRule({ ...DEFAULT_RULE })
  }

  const reload = async () => {
    try {
      const r = await api.reloadScraperRules()
      flash(`热重载成功，共 ${r.total} 条规则，${r.enabled} 条启用`)
      await load()
    } catch {
      flash('热重载失败', false)
    }
  }

  const RuleForm = ({
    rule, onChange, onCancel, onSubmit, submitLabel,
  }: {
    rule: ScraperRule
    onChange: (r: ScraperRule) => void
    onCancel: () => void
    onSubmit: () => void
    submitLabel: string
  }) => (
    <div className="bg-zinc-800 border border-zinc-600 rounded-lg p-4 space-y-3 text-sm">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-zinc-400 mb-1">域名 *</label>
          <input
            className="w-full bg-zinc-700 border border-zinc-600 rounded px-2 py-1 text-white"
            placeholder="e.g. my-wiki.com"
            value={rule.domain}
            onChange={e => onChange({ ...rule, domain: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-zinc-400 mb-1">别名</label>
          <input
            className="w-full bg-zinc-700 border border-zinc-600 rounded px-2 py-1 text-white"
            placeholder="显示名称"
            value={rule.alias}
            onChange={e => onChange({ ...rule, alias: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-zinc-400 mb-1">引擎</label>
          <select
            className="w-full bg-zinc-700 border border-zinc-600 rounded px-2 py-1 text-white"
            value={rule.engine}
            onChange={e => onChange({ ...rule, engine: e.target.value as 'httpx' | 'playwright' })}
          >
            {ENGINE_OPTIONS.map(e => <option key={e} value={e}>{e}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-zinc-400 mb-1">等待 (ms, Playwright)</label>
          <input
            type="number"
            className="w-full bg-zinc-700 border border-zinc-600 rounded px-2 py-1 text-white"
            value={rule.wait_ms}
            onChange={e => onChange({ ...rule, wait_ms: Number(e.target.value) })}
          />
        </div>
        <div>
          <label className="block text-zinc-400 mb-1">最大字符数</label>
          <input
            type="number"
            className="w-full bg-zinc-700 border border-zinc-600 rounded px-2 py-1 text-white"
            value={rule.max_chars}
            onChange={e => onChange({ ...rule, max_chars: Number(e.target.value) })}
          />
        </div>
        <div className="flex items-center gap-2 pt-5">
          <input
            type="checkbox"
            checked={rule.enabled}
            onChange={e => onChange({ ...rule, enabled: e.target.checked })}
            className="w-4 h-4 accent-indigo-500"
          />
          <span className="text-zinc-300">启用</span>
        </div>
      </div>
      <div>
        <label className="block text-zinc-400 mb-1">CSS 选择器（每行一个，优先级从上到下）</label>
        <textarea
          className="w-full bg-zinc-700 border border-zinc-600 rounded px-2 py-1 text-white font-mono text-xs"
          rows={3}
          value={rule.content_selectors.join('\n')}
          onChange={e => onChange({ ...rule, content_selectors: e.target.value.split('\n').map(s => s.trim()).filter(Boolean) })}
          placeholder="#mw-content-text .mw-parser-output&#10;article&#10;main"
        />
      </div>
      <div>
        <label className="block text-zinc-400 mb-1">备注</label>
        <input
          className="w-full bg-zinc-700 border border-zinc-600 rounded px-2 py-1 text-white"
          value={rule.notes}
          onChange={e => onChange({ ...rule, notes: e.target.value })}
        />
      </div>
      <div className="flex gap-2 pt-1">
        <button
          onClick={onSubmit}
          className="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 rounded text-white"
        >
          {submitLabel}
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-1 bg-zinc-600 hover:bg-zinc-500 rounded text-white"
        >
          取消
        </button>
      </div>
    </div>
  )

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-white">网页抓取站点规则</h3>
          <p className="text-zinc-400 text-sm mt-0.5">
            配置各站点的抓取引擎、CSS 选择器，让 Agent 自动获取 Wiki / Fandom / Wikipedia 等来源的世界观资料。
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={reload}
            className="px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 rounded text-sm text-zinc-300"
            title="手动编辑 JSON 后热重载"
          >
            热重载
          </button>
          <button
            onClick={() => setShowAdd(true)}
            className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 rounded text-sm text-white"
          >
            + 添加站点
          </button>
        </div>
      </div>

      {/* Flash message */}
      {msg && (
        <div className={`px-3 py-2 rounded text-sm ${msg.ok ? 'bg-green-900/50 text-green-300' : 'bg-red-900/50 text-red-300'}`}>
          {msg.text}
        </div>
      )}

      {/* Add form */}
      {showAdd && (
        <RuleForm
          rule={newRule}
          onChange={setNewRule}
          onCancel={() => { setShowAdd(false); setNewRule({ ...DEFAULT_RULE }) }}
          onSubmit={addRule}
          submitLabel="添加"
        />
      )}

      {/* Rules list */}
      {loading ? (
        <div className="text-zinc-400 text-sm py-4">加载中…</div>
      ) : rules.length === 0 ? (
        <div className="text-zinc-500 text-sm py-4 text-center border border-dashed border-zinc-700 rounded-lg">
          暂无规则，点击「添加站点」配置第一条
        </div>
      ) : (
        <div className="space-y-2">
          {rules.map((rule, idx) => (
            <div key={rule.domain}>
              {editIdx === idx ? (
                <RuleForm
                  rule={editDraft}
                  onChange={setEditDraft}
                  onCancel={() => setEditIdx(null)}
                  onSubmit={commitEdit}
                  submitLabel="保存"
                />
              ) : (
                <div className={`flex items-center gap-3 px-4 py-3 rounded-lg border ${
                  rule.enabled
                    ? 'bg-zinc-800 border-zinc-700'
                    : 'bg-zinc-900 border-zinc-800 opacity-60'
                }`}>
                  {/* Toggle */}
                  <button
                    onClick={() => toggleEnabled(idx)}
                    className={`w-8 h-4 rounded-full transition-colors flex-shrink-0 ${
                      rule.enabled ? 'bg-indigo-600' : 'bg-zinc-600'
                    }`}
                    title={rule.enabled ? '点击禁用' : '点击启用'}
                  >
                    <div className={`w-3 h-3 bg-white rounded-full mx-0.5 transition-transform ${
                      rule.enabled ? 'translate-x-3.5' : 'translate-x-0'
                    }`} />
                  </button>

                  {/* Engine badge */}
                  <span className={`px-1.5 py-0.5 rounded text-xs font-mono flex-shrink-0 ${
                    rule.engine === 'playwright'
                      ? 'bg-orange-900/60 text-orange-300'
                      : 'bg-blue-900/60 text-blue-300'
                  }`}>
                    {rule.engine}
                  </span>

                  {/* Domain + alias */}
                  <div className="flex-1 min-w-0">
                    <span className="text-white font-medium">{rule.alias || rule.domain}</span>
                    {rule.alias && (
                      <span className="text-zinc-500 text-xs ml-2 font-mono">{rule.domain}</span>
                    )}
                    {rule.notes && (
                      <p className="text-zinc-500 text-xs mt-0.5 truncate">{rule.notes}</p>
                    )}
                  </div>

                  {/* Selectors count */}
                  {rule.content_selectors.length > 0 && (
                    <span className="text-zinc-500 text-xs flex-shrink-0">
                      {rule.content_selectors.length} 选择器
                    </span>
                  )}

                  {/* Actions */}
                  <div className="flex gap-1 flex-shrink-0">
                    <button
                      onClick={() => startEdit(idx)}
                      className="px-2 py-1 text-xs bg-zinc-700 hover:bg-zinc-600 rounded text-zinc-300"
                    >
                      编辑
                    </button>
                    <button
                      onClick={() => deleteRule(idx)}
                      className="px-2 py-1 text-xs bg-zinc-700 hover:bg-red-700 rounded text-zinc-300"
                    >
                      删除
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Usage hint */}
      <div className="mt-4 p-3 bg-zinc-900/50 rounded-lg border border-zinc-800 text-xs text-zinc-500 space-y-1">
        <p className="font-medium text-zinc-400">Agent 工具调用示例</p>
        <p>• <code className="text-indigo-400">fetch_web_lore</code> — 抓取单个 URL 并提炼为档案条目</p>
        <p>• <code className="text-indigo-400">batch_fetch_lore</code> — 并发批量抓取多个 URL</p>
        <p>• <code className="text-indigo-400">list_scraper_rules</code> — 列出可用站点</p>
        <p>• <code className="text-indigo-400">update_scraper_rule</code> — Agent 自主添加新站点规则</p>
        <p className="pt-1">规则文件路径：<code className="text-zinc-400">backend/data/sys_config/scraper_rules.json</code></p>
      </div>

      {saving && (
        <div className="fixed bottom-4 right-4 px-3 py-2 bg-zinc-800 rounded shadow text-sm text-zinc-300">
          保存中…
        </div>
      )}
    </div>
  )
}
