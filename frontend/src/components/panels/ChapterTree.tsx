/**
 * ChapterTree — 章节树（支持多级分支可视化 + fork 创建）
 * 使用 useChapterStore 管理章节状态（差距021修复）
 */
import React, { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import { useChapterStore, type ChapterNode as Chapter } from '../../stores/chapter'
import { notify } from '../../stores/ui'
import { requestConfirm } from '../../stores/confirm'

interface Props {
  sessionId: string
  onSelectChapter?: (chapterId: string) => void
  onFork?: (branchSessionId: string, branchLabel: string) => void
  refreshKey?: number
}

/** 递归建树（按 parent_chapter_id 分组） */
function buildTree(chapters: Chapter[]): Map<string | null, Chapter[]> {
  const map = new Map<string | null, Chapter[]>()
  for (const ch of chapters) {
    const pid = (ch as Chapter).parent_chapter_id ?? null
    if (!map.has(pid)) map.set(pid, [])
    map.get(pid)!.push(ch)
  }
  return map
}

// ── 单个章节节点 ──────────────────────────────────────────────────────────────

const ChapterNode: React.FC<{
  chapter: Chapter
  index: number
  depth: number
  selected: boolean
  childMap: Map<string | null, Chapter[]>
  sessionId: string
  onSelect: (id: string) => void
  onReload: () => void
}> = ({ chapter, index, depth, selected, childMap, sessionId, onSelect, onReload }) => {
  const [expanded, setExpanded] = useState(true)
  const [reverting, setReverting] = useState(false)
  const children = childMap.get(chapter.id) ?? []
  const isBranch = !!chapter.branch_label
  const label = isBranch ? chapter.branch_label! : `第 ${chapter.chapter_index ?? index} 章`
  const summary = chapter.summary
    ? chapter.summary.slice(0, 28) + (chapter.summary.length > 28 ? '…' : '')
    : '（进行中）'

  const handleRevert = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!chapter.end_message_id) return
    const ok = await requestConfirm({
      title: '回溯章节',
      message: `确定回溯到「${label}」末尾？此操作将删除之后的叙事内容。`,
      confirmText: '回溯',
      danger: true,
    })
    if (!ok) return
    setReverting(true)
    try {
      await api.revertToMessage(sessionId, chapter.end_message_id)
      notify.success(`已回溯到「${label}」`)
      onReload()
    } catch (err) {
      notify.error(`回溯失败：${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setReverting(false)
    }
  }

  return (
    <div className="select-none">
      {/* 节点行 */}
      <div
        className={`w-full flex items-start gap-1.5 px-2 py-1 rounded transition-colors group cursor-pointer ${
          selected ? 'bg-zinc-700' : 'hover:bg-zinc-800/60'
        }`}
        style={{ paddingLeft: `${8 + depth * 14}px` }}
        onClick={() => onSelect(chapter.id)}
      >
        {/* 展开/折叠（有子节点时显示）*/}
        {children.length > 0 ? (
          <span
            className="text-zinc-600 hover:text-zinc-400 mt-0.5 flex-shrink-0 w-3 text-center"
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
          >
            {expanded ? '▾' : '▸'}
          </span>
        ) : (
          <span className="w-3 flex-shrink-0" />
        )}

        {/* 图标 */}
        <span className="flex-shrink-0 mt-0.5">
          {chapter.is_consolidated
            ? <span className="text-zinc-500">🔒</span>
            : isBranch
            ? <span className="text-indigo-500">⑂</span>
            : <span className="text-zinc-600">○</span>
          }
        </span>

        {/* 文本 */}
        <div className="min-w-0 flex-1">
          <div className={`text-xs font-medium ${selected ? 'text-zinc-200' : isBranch ? 'text-indigo-400' : 'text-zinc-400'}`}>
            {label}
          </div>
          {chapter.is_consolidated && (
            <div className="text-zinc-600 text-[10px] leading-tight mt-0.5 truncate">
              {summary}
            </div>
          )}
        </div>

        {/* 回溯按钮（已固化且有 end_message_id 时显示） */}
        {chapter.is_consolidated && chapter.end_message_id && (
          <button
            onClick={handleRevert}
            disabled={reverting}
            title="回溯到此章节末尾"
            className="opacity-0 group-hover:opacity-100 flex-shrink-0 mt-0.5 text-zinc-600
                       hover:text-amber-400 transition-all text-[11px] px-0.5 disabled:opacity-30"
          >
            {reverting ? '…' : '↩'}
          </button>
        )}
      </div>

      {/* 子节点 */}
      {expanded && children.length > 0 && (
        <div style={{ marginLeft: `${14 + depth * 14}px` }} className="border-l border-zinc-800 mt-0.5">
          {children.map((child, i) => (
            <ChapterNode
              key={child.id}
              chapter={child}
              index={i + 1}
              depth={depth + 1}
              selected={selected}
              childMap={childMap}
              sessionId={sessionId}
              onSelect={onSelect}
              onReload={onReload}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── 主组件 ────────────────────────────────────────────────────────────────────

export const ChapterTree: React.FC<Props> = ({ sessionId, onSelectChapter, onFork, refreshKey }) => {
  const { chapters, activeChapterId, loadChapters } = useChapterStore()
  const [selected, setSelected]       = useState<string | null>(activeChapterId)
  const [forking, setForking]         = useState(false)
  const [branchLabel, setBranchLabel] = useState('')
  const [showFork, setShowFork]       = useState(false)
  const [forkResult, setForkResult]   = useState<{ sessionId: string; label: string } | null>(null)
  const [consolidating, setConsolidating] = useState(false)

  const handleConsolidate = async () => {
    if (consolidating) return
    const ok = await requestConfirm({
      title: '整合当前章节',
      message: '将当前进行中的章节固化为正式章节并生成摘要。固化后内容会被压缩归档。确定继续？',
      confirmText: '整合',
    })
    if (!ok) return
    setConsolidating(true)
    try {
      const res = await api.consolidateChapter(sessionId)
      notify.success(`已整合章节${res.summary ? `：${res.summary.slice(0, 20)}` : ''}`)
      await loadChapters(sessionId)
    } catch (err) {
      notify.error(`整合失败：${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setConsolidating(false)
    }
  }

  useEffect(() => {
    loadChapters(sessionId)
    const t = setInterval(() => loadChapters(sessionId), 10000)
    return () => clearInterval(t)
  }, [sessionId, loadChapters, refreshKey])

  useEffect(() => {
    const h = () => loadChapters(sessionId)
    window.addEventListener('chapter.consolidated', h)
    return () => window.removeEventListener('chapter.consolidated', h)
  }, [sessionId, loadChapters])

  const handleFork = async () => {
    if (!branchLabel.trim() || forking) return
    setForking(true)
    const label = branchLabel.trim()
    try {
      const res = await api.forkSession(sessionId, label)
      const newId = res.new_session_id
      setBranchLabel('')
      setShowFork(false)
      await loadChapters(sessionId)
      if (newId) {
        setForkResult({ sessionId: newId, label })
        onFork?.(newId, label)
      }
    } catch { /* ignore */ }
    finally { setForking(false) }
  }

  const handleSelect = (id: string) => {
    setSelected(id)
    onSelectChapter?.(id)
  }

  // 构建树形结构（根节点 parent_chapter_id = null）
  const childMap = buildTree(chapters)
  const roots = childMap.get(null) ?? []

  return (
    <div className="flex flex-col h-full text-xs">
      {/* 标题栏 */}
      <div className="px-3 py-2 text-zinc-400 font-semibold text-xs uppercase tracking-wider flex items-center justify-between flex-shrink-0">
        <span>章节树</span>
        <div className="flex items-center gap-2">
          <button
            onClick={handleConsolidate}
            disabled={consolidating}
            className="text-zinc-600 hover:text-amber-400 text-sm disabled:opacity-40"
            title="整合当前章节"
          >
            {consolidating ? '…' : '📑'}
          </button>
          <button
            onClick={() => setShowFork(!showFork)}
            className="text-zinc-600 hover:text-zinc-400 text-sm"
            title="创建分支"
          >
            ⑂
          </button>
        </div>
      </div>

      {/* Fork 结果提示 */}
      {forkResult && (
        <div className="mx-3 mb-1 p-2 bg-indigo-900/40 border border-indigo-700 rounded text-xs flex-shrink-0">
          <div className="text-indigo-300 font-medium">分支已创建：{forkResult.label}</div>
          <button
            onClick={() => { onFork?.(forkResult.sessionId, forkResult.label); setForkResult(null) }}
            className="mt-1 text-indigo-400 hover:text-indigo-200 underline"
          >
            前往分支 →
          </button>
        </div>
      )}

      {/* Fork 输入 */}
      {showFork && (
        <div className="px-3 pb-2 flex gap-1 flex-shrink-0">
          <input
            type="text"
            placeholder="分支名称"
            value={branchLabel}
            onChange={(e) => setBranchLabel(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleFork()}
            className="flex-1 bg-zinc-800 border border-zinc-700 rounded px-2 py-0.5 text-xs
                       focus:outline-none focus:border-indigo-500 placeholder-zinc-600"
          />
          <button
            onClick={handleFork}
            disabled={forking}
            className="px-2 py-0.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-700 text-white rounded text-xs"
          >
            {forking ? '…' : '建'}
          </button>
        </div>
      )}

      {/* 树形节点列表 */}
      <div className="flex-1 overflow-y-auto pb-2">
        {roots.length === 0 ? (
          <div className="text-zinc-700 px-3 py-3 text-center">暂无章节</div>
        ) : (
          roots.map((root, i) => (
            <ChapterNode
              key={root.id}
              chapter={root}
              index={i + 1}
              depth={0}
              selected={selected === root.id}
              childMap={childMap}
              sessionId={sessionId}
              onSelect={handleSelect}
              onReload={() => loadChapters(sessionId)}
            />
          ))
        )}
      </div>

      {/* 图例 */}
      <div className="flex-shrink-0 px-3 py-1.5 border-t border-zinc-800 flex items-center gap-3 text-[10px] text-zinc-700">
        <span>🔒 已固化</span>
        <span className="text-indigo-600">⑂ 分支</span>
        <span>○ 进行中</span>
      </div>
    </div>
  )
}

export default ChapterTree
