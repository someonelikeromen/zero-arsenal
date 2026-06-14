import React, { useState, useCallback, useRef } from 'react'
import { api, apiFetch } from '../../lib/api'
import { notify } from '../../stores/ui'
import { requestConfirm } from '../../stores/confirm'

interface Props {
  sessionId: string
}

const NODE_TYPES = [
  { value: 'event',   label: '事件' },
  { value: 'setting', label: '设定' },
  { value: 'npc',     label: 'NPC关系' },
] as const

type NodeType = typeof NODE_TYPES[number]['value']

interface MemoryEntry {
  id: string
  content: string
  tier: 'core' | 'semantic' | 'episodic'
  source_agent: string
  cognitive_partition: string
  created_at: number
}

const TIER_COLORS: Record<string, string> = {
  core:     'bg-amber-900/50 text-amber-300 border-amber-700/50',
  semantic: 'bg-blue-900/50 text-blue-300 border-blue-700/50',
  episodic: 'bg-zinc-800 text-zinc-500 border-zinc-700/50',
}

const TIER_LABELS: Record<string, string> = {
  core:     '核心',
  semantic: '语义',
  episodic: '情节',
}

export const MemoryPanel: React.FC<Props> = ({ sessionId }) => {
  const [collapsed, setCollapsed] = useState(false)

  // 搜索
  const [query, setQuery]           = useState('')
  const [results, setResults]       = useState<string[]>([])
  const [entries, setEntries]       = useState<MemoryEntry[]>([])
  const [fullMode, setFullMode]     = useState<boolean | null>(null)
  const [searching, setSearching]   = useState(false)
  const [searchError, setSearchError] = useState('')
  const [showEntries, setShowEntries] = useState(false)

  // 写入
  const [writeContent, setWriteContent] = useState('')
  const [nodeType, setNodeType]         = useState<NodeType>('event')
  const [writing, setWriting]           = useState(false)
  const [writeError, setWriteError]     = useState('')
  const [writeOk, setWriteOk]           = useState(false)

  // 浏览全部 + 整合 + 回滚
  const [browseEntries, setBrowseEntries] = useState<MemoryEntry[] | null>(null)
  const [browseTier, setBrowseTier]   = useState<string>('')
  const [browsing, setBrowsing]       = useState(false)
  const [consolidating, setConsolidating] = useState(false)

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const loadBrowse = useCallback(async (tier: string) => {
    setBrowsing(true)
    try {
      const data = await api.browseMemory(sessionId, tier || undefined, 50)
      setBrowseEntries((data.entries ?? []) as MemoryEntry[])
    } catch (e) {
      notify.error(`加载记忆失败：${(e as Error).message}`)
      setBrowseEntries([])
    } finally {
      setBrowsing(false)
    }
  }, [sessionId])

  const handleConsolidate = async () => {
    if (consolidating) return
    const ok = await requestConfirm({
      title: '整合记忆',
      message: '将情节记忆压缩固化为语义记忆。该过程不可逆，确定继续？',
      confirmText: '整合',
    })
    if (!ok) return
    setConsolidating(true)
    try {
      await api.consolidateMemory(sessionId)
      notify.success('记忆整合完成')
      if (browseEntries !== null) loadBrowse(browseTier)
    } catch (e) {
      notify.error(`整合失败：${(e as Error).message}`)
    } finally {
      setConsolidating(false)
    }
  }

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([])
      setFullMode(null)
      setSearchError('')
      return
    }
    setSearching(true)
    setSearchError('')
    try {
      const data = await apiFetch<{ results: string; full_mode: boolean; entries?: MemoryEntry[] }>(
        `/sessions/${encodeURIComponent(sessionId)}/memory?q=${encodeURIComponent(q)}&top_k=8`
      )
      setFullMode(data.full_mode)
      const blocks = (data.results ?? '').split('---').map((s: string) => s.trim()).filter(Boolean)
      setResults(blocks)
      setEntries(data.entries ?? [])
    } catch (e) {
      setSearchError((e as Error).message)
      setResults([])
    } finally {
      setSearching(false)
    }
  }, [sessionId])

  const handleQueryChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    setQuery(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => doSearch(val), 400)
  }

  const handleWrite = async () => {
    if (!writeContent.trim() || writing) return
    setWriting(true)
    setWriteError('')
    setWriteOk(false)
    try {
      await apiFetch(`/sessions/${encodeURIComponent(sessionId)}/memory`, {
        method: 'POST',
        body: JSON.stringify({ content: writeContent.trim(), node_type: nodeType, metadata: {} }),
      })
      setWriteContent('')
      setWriteOk(true)
      setTimeout(() => setWriteOk(false), 2000)
    } catch (e) {
      setWriteError((e as Error).message)
    } finally {
      setWriting(false)
    }
  }

  return (
    <div className="text-xs border-t border-zinc-800">
      {/* 标题行 */}
      <button
        className="w-full flex items-center justify-between text-zinc-400 font-semibold text-xs uppercase tracking-wider px-3 py-2 hover:text-zinc-200"
        onClick={() => setCollapsed(!collapsed)}
      >
        <span className="flex items-center gap-2">
          记忆
          {fullMode !== null && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded font-normal normal-case tracking-normal ${
              fullMode ? 'bg-blue-900 text-blue-300' : 'bg-zinc-800 text-zinc-400'
            }`}>
              {fullMode ? '全量模式' : '精简模式'}
            </span>
          )}
        </span>
        <span>{collapsed ? '▸' : '▾'}</span>
      </button>

      {!collapsed && (
        <div className="px-3 pb-3 space-y-3">
          {/* 搜索框 */}
          <div className="space-y-1">
            <input
              type="text"
              placeholder="搜索记忆..."
              value={query}
              onChange={handleQueryChange}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500 placeholder-zinc-600"
            />
            {searching && (
              <div className="text-zinc-500 text-xs">加载中...</div>
            )}
            {searchError && (
              <div className="text-red-400 text-xs">错误：{searchError}</div>
            )}
          </div>

          {/* 搜索结果 */}
          {results.length > 0 && (
            <div className="space-y-1">
              {/* 切换视图：混合文本 vs 结构化条目 */}
              {entries.length > 0 && (
                <div className="flex items-center gap-2 mb-1">
                  <button
                    onClick={() => setShowEntries(false)}
                    className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${
                      !showEntries ? 'bg-indigo-700 text-white' : 'bg-zinc-800 text-zinc-500 hover:text-zinc-300'
                    }`}
                  >
                    合并视图
                  </button>
                  <button
                    onClick={() => setShowEntries(true)}
                    className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${
                      showEntries ? 'bg-indigo-700 text-white' : 'bg-zinc-800 text-zinc-500 hover:text-zinc-300'
                    }`}
                  >
                    条目视图 ({entries.length})
                  </button>
                </div>
              )}

              {!showEntries ? (
                <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                  {results.map((block, i) => (
                    <div
                      key={i}
                      className="bg-zinc-800/60 border border-zinc-700/50 rounded px-2 py-1.5 text-zinc-300 leading-relaxed whitespace-pre-wrap"
                    >
                      {block}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-1 max-h-52 overflow-y-auto pr-1">
                  {entries.map((entry) => (
                    <div
                      key={entry.id}
                      className={`border rounded px-2 py-1.5 ${TIER_COLORS[entry.tier] ?? TIER_COLORS.episodic}`}
                    >
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className={`text-[9px] px-1 py-0.5 rounded font-medium ${TIER_COLORS[entry.tier]}`}>
                          {TIER_LABELS[entry.tier] ?? entry.tier}
                        </span>
                        <span className="text-[9px] text-zinc-600">{entry.source_agent}</span>
                      </div>
                      <p className="leading-relaxed line-clamp-3 text-[10px]">{entry.content}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          {!searching && query.trim() && results.length === 0 && !searchError && (
            <div className="text-zinc-600 text-xs">无匹配结果</div>
          )}

          {/* 全部记忆管理工具条 */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <button
              onClick={() => {
                if (browseEntries === null) loadBrowse(browseTier)
                else setBrowseEntries(null)
              }}
              className={`text-[10px] px-1.5 py-0.5 rounded ${
                browseEntries !== null ? 'bg-indigo-700 text-white' : 'bg-zinc-800 text-zinc-400 hover:text-zinc-200'
              }`}
            >
              {browseEntries !== null ? '收起全部' : '浏览全部'}
            </button>
            <button
              onClick={handleConsolidate}
              disabled={consolidating}
              className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-800 text-amber-400 hover:bg-zinc-700 disabled:opacity-40"
              title="将情节记忆压缩为语义记忆"
            >
              {consolidating ? '整合中…' : '🗜 整合记忆'}
            </button>
          </div>

          {browseEntries !== null && (
            <div className="space-y-1">
              {/* tier 过滤 */}
              <div className="flex gap-1">
                {['', 'core', 'semantic', 'episodic'].map(t => (
                  <button
                    key={t || 'all'}
                    onClick={() => { setBrowseTier(t); loadBrowse(t) }}
                    className={`text-[9px] px-1.5 py-0.5 rounded ${
                      browseTier === t ? 'bg-indigo-700 text-white' : 'bg-zinc-800 text-zinc-500 hover:text-zinc-300'
                    }`}
                  >
                    {t ? TIER_LABELS[t] : '全部'}
                  </button>
                ))}
              </div>
              {browsing ? (
                <div className="text-zinc-500 text-xs">加载中...</div>
              ) : browseEntries.length === 0 ? (
                <div className="text-zinc-600 text-xs">暂无记忆条目</div>
              ) : (
                <div className="space-y-1 max-h-52 overflow-y-auto pr-1">
                  {browseEntries.map(entry => (
                    <div key={entry.id} className={`border rounded px-2 py-1.5 ${TIER_COLORS[entry.tier] ?? TIER_COLORS.episodic}`}>
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span className={`text-[9px] px-1 py-0.5 rounded font-medium ${TIER_COLORS[entry.tier]}`}>
                          {TIER_LABELS[entry.tier] ?? entry.tier}
                        </span>
                        <span className="text-[9px] text-zinc-600">{entry.source_agent}</span>
                      </div>
                      <p className="leading-relaxed line-clamp-3 text-[10px]">{entry.content}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 分隔线 */}
          <div className="border-t border-zinc-800" />

          {/* 写入区域 */}
          <div className="space-y-2">
            <div className="text-zinc-600 text-xs">写入记忆</div>
            <textarea
              rows={3}
              placeholder="输入记忆内容..."
              value={writeContent}
              onChange={(e) => setWriteContent(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500 placeholder-zinc-600 resize-none"
            />
            <div className="flex items-center gap-2">
              <div className="flex gap-1">
                {NODE_TYPES.map(({ value, label }) => (
                  <button
                    key={value}
                    onClick={() => setNodeType(value)}
                    className={`px-1.5 py-0.5 rounded text-xs transition-colors ${
                      nodeType === value
                        ? 'bg-indigo-600 text-white'
                        : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <button
                onClick={handleWrite}
                disabled={!writeContent.trim() || writing}
                className="ml-auto px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white rounded text-xs font-medium transition-colors"
              >
                {writing ? '写入中...' : '写入'}
              </button>
            </div>
            {writeOk && (
              <div className="text-green-400 text-xs">写入成功</div>
            )}
            {writeError && (
              <div className="text-red-400 text-xs">写入失败：{writeError}</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
