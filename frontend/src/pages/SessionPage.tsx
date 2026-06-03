/**
 * SessionPage — 三栏主界面：章节树 | 故事流 | 右侧多功能面板
 * 响应式三断点（12-frontend-architecture.md §2.2）：
 *   < 768px   : 单栏 + 底部抽屉（左/右面板）
 *   768–1280px: 双栏（叙事 + 右栏），左栏进左抽屉
 *   > 1280px  : 三栏完整展示
 */
import React, { useEffect, useState, useCallback, useRef } from 'react'
import { useStoryStore } from '../stores/story'
import { useSessionStore } from '../stores/session'
import { useCharacterStore } from '../stores/character'
import { useUIStore, notify } from '../stores/ui'
import { requestConfirm } from '../stores/confirm'
import { useDiceStore } from '../stores/dice'
import { useWorldStore } from '../stores/world'
import { DicePanel } from '../components/panels/DicePanel'
import { CharacterPanel } from '../components/panels/CharacterPanel'
import { ChapterTree } from '../components/panels/ChapterTree'
import { MemoryPanel } from '../components/panels/MemoryPanel'
import { PermissionDialog } from '../components/PermissionDialog'
import { ModeSelector } from '../components/ModeSelector'
import { InputBar, type SystemState } from '../components/InputBar'
import { MessageThread } from '../components/MessageThread'
import { api } from '../lib/api'
import { createSSEHandler } from '../lib/bindSSEToStores'

// 延迟加载可选面板（减少初始包大小）
const WorldPanel = React.lazy(() => import('../components/panels/WorldPanel'))
const HistoryPanel = React.lazy(() => import('../components/panels/HistoryPanel'))
const InventoryPanel = React.lazy(() => import('../components/panels/InventoryPanel'))
const EconomyPanel = React.lazy(() => import('../components/panels/EconomyPanel'))
const CombatPanel = React.lazy(() => import('../components/panels/CombatPanel'))
const WritingStylePanel = React.lazy(() => import('../components/panels/WritingStylePanel'))

// ── 抽屉组件（移动端/平板） ────────────────────────────────────────────────────
interface DrawerProps {
  open: boolean
  onClose: () => void
  side: 'left' | 'right' | 'bottom'
  children: React.ReactNode
  title?: string
}

const Drawer: React.FC<DrawerProps> = ({ open, onClose, side, children, title }) => {
  if (!open) return null
  const posClass = side === 'left'
    ? 'left-0 top-0 h-full w-56 flex-col'
    : side === 'right'
    ? 'right-0 top-0 h-full w-64 flex-col'
    : 'bottom-0 left-0 w-full max-h-[60vh] flex-col'

  return (
    <div className="fixed inset-0 z-40 flex" onClick={onClose}>
      {/* 半透明遮罩 */}
      <div className="absolute inset-0 bg-black/50" />
      {/* 抽屉内容 */}
      <div
        className={`relative flex bg-zinc-900 border-zinc-700 shadow-xl overflow-hidden ${posClass} ${
          side === 'left' ? 'border-r' : side === 'right' ? 'border-l' : 'border-t rounded-t-xl'
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        {title && (
          <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800 flex-shrink-0">
            <span className="text-xs font-medium text-zinc-400">{title}</span>
            <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300 text-lg leading-none">×</button>
          </div>
        )}
        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  )
}

interface Props {
  sessionId: string
  onNavigateSession?: (newSessionId: string) => void
}

type RightTab = 'dice' | 'character' | 'world' | 'history' | 'memory' | 'economy' | 'combat' | 'writing'


// Agent 节点中文标签（管线可视化用）
const AGENT_LABELS: Record<string, string> = {
  rules: '规则', dm: '裁判', dice: '骰子', npc: 'NPC', world: '世界',
  narrator: '叙事', style: '文风', var: '结算', chronicler: '归档',
}

const RIGHT_TABS: { id: RightTab; label: string; icon: string }[] = [
  { id: 'dice',      label: '骰子',   icon: '🎲' },
  { id: 'character', label: '角色',   icon: '👤' },
  { id: 'world',     label: '世界',   icon: '🌍' },
  { id: 'memory',    label: '记忆',   icon: '🧠' },
  { id: 'economy',   label: '经济',   icon: '💰' },
  { id: 'combat',    label: '战斗',   icon: '⚔️' },
  { id: 'writing',   label: '文风',   icon: '✍️' },
  { id: 'history',   label: '历史',   icon: '📜' },
]

export const SessionPage: React.FC<Props> = ({ sessionId, onNavigateSession }) => {
  const { parts, addPart, appendDelta, finalizePart, updatePartContent, clearSession, setSessionId, loadFromCache, loadParts, loadMessages } = useStoryStore()
  const { mode, setMode, connectSSE, disconnectSSE, pendingAsks, addPendingAsk, removePendingAsk, selectSession } = useSessionStore()
  const { loadCharacter, character, applyPatch, inventory } = useCharacterStore()
  const { inputDisabled, setInputDisabled } = useUIStore()
  const { addRoll: addDiceRoll, loadHistory: loadDiceHistory } = useDiceStore()
  const worldArchives = useWorldStore(s => s.archives)
  const loadWorldArchives = useWorldStore(s => s.loadArchives)
  const [input, setInput] = useState('')
  const [activeAgent, setActiveAgent] = useState<string | null>(null)
  const [rightTab, setRightTab] = useState<RightTab>('dice')
  const [worldPlugin, setWorldPlugin] = useState('crossover')
  const [chapterRefreshKey, setChapterRefreshKey] = useState(0)
  // Phase 3C/6D：会话统计 + Agent 管线节点可视化
  const [stats, setStats] = useState<{ model?: string; turns?: number } | null>(null)
  const [pipeline, setPipeline] = useState<{ agent: string; status: 'running' | 'done' }[]>([])
  // Phase 7D：输入栏系统状态
  const [systemState, setSystemState] = useState<SystemState>('ready')

  const handleStop = useCallback(() => {
    api.cancelStream(sessionId).catch(() => {})
    setInputDisabled(false)
    setActiveAgent(null)
  }, [sessionId, setInputDisabled])

  // Swipe 备选：从指定叙事消息分支出平行走向（创建分支会话并跳转）
  const [branchCount, setBranchCount] = useState(0)
  const handleForkFromMessage = useCallback(async (messageId: string) => {
    const label = `走向-${new Date().toLocaleTimeString().slice(0, 5)}`
    try {
      const res = await api.forkSession(sessionId, label, messageId)
      const newId = (res as { new_session_id?: string }).new_session_id
      setBranchCount(c => c + 1)
      notify.success(`已分支出平行走向「${label}」`)
      if (newId && onNavigateSession) {
        const go = await requestConfirm({
          title: '前往新分支', message: '平行走向已创建，是否立即切换到该分支继续？', confirmText: '前往',
        })
        if (go) onNavigateSession(newId)
      }
    } catch (e) {
      notify.error(`分支失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }, [sessionId, onNavigateSession])

  const refreshStats = useCallback(() => {
    api.get(`/sessions/${sessionId}/stats`)
      .then(s => setStats(s as { model?: string; turns?: number }))
      .catch(() => {})
  }, [sessionId])

  // 由 agent.started/ended 事件驱动的管线节点累积（保留顺序，标记 running/done）
  const handleSetActiveAgent = useCallback((agent: string | null) => {
    setActiveAgent(agent)
    if (agent) {
      setPipeline(prev => {
        const done = prev.map(s => ({ ...s, status: 'done' as const }))
        if (done.some(s => s.agent === agent)) {
          return done.map(s => s.agent === agent ? { ...s, status: 'running' as const } : s)
        }
        return [...done, { agent, status: 'running' as const }]
      })
    } else {
      setPipeline(prev => prev.map(s => ({ ...s, status: 'done' as const })))
      refreshStats()
    }
  }, [refreshStats])

  // ── 响应式抽屉状态（12-frontend-architecture.md §2.2） ──────────────────
  const [leftDrawerOpen, setLeftDrawerOpen] = useState(false)
  const [rightDrawerOpen, setRightDrawerOpen] = useState(false)
  const closeLeft = useCallback(() => setLeftDrawerOpen(false), [])
  const closeRight = useCallback(() => setRightDrawerOpen(false), [])

  // 当前最新的行动选项（来自最近的 action_options Part）
  const latestOptions = React.useMemo(() => {
    const optParts = parts.filter((p) => p.type === 'action_options' && p.status === 'done')
    if (!optParts.length) return []
    const last = optParts[optParts.length - 1]
    const d = last.content as { options?: { label: string; text: string }[] }
    return d.options ?? []
  }, [parts])

  // 连接 SSE
  useEffect(() => {
    clearSession()
    setSessionId(sessionId)
    selectSession(sessionId)   // 设置 currentSessionId，供 DicePanel 等组件读取
    // 先从 IndexedDB 恢复缓存（即时显示），再从服务端拉最新历史覆盖
    loadFromCache(sessionId)
    loadParts(sessionId)
    loadMessages(sessionId)
    loadCharacter(sessionId)
    loadDiceHistory(sessionId)
    loadWorldArchives(sessionId)   // 供 InputBar # 触发的知识库下拉

    const onEvent = createSSEHandler({
      addPart, appendDelta, finalizePart,
      updatePartContent,
      applyPatch,
      addPendingAsk, removePendingAsk, setMode,
      addDiceRoll,
      setSending: setInputDisabled,
      setActiveAgent: handleSetActiveAgent, setChapterRefreshKey,
    })

    // 加载 session 基础信息（获取 worldPlugin）
    api.getSession(sessionId)
      .then(s => setWorldPlugin((s as { world_plugin: string }).world_plugin ?? 'crossover'))
      .catch(() => {})
    refreshStats()

    connectSSE(sessionId, onEvent)
    return () => disconnectSSE()
  }, [sessionId])

  // Phase 7D：检测 LLM 配置 / 世界 / 角色就绪状态
  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.getLlmRoutes().catch(() => ({ routes: {} as Record<string, unknown> })),
      api.getSession(sessionId).catch(() => ({} as Record<string, unknown>)),
    ]).then(([routes, sess]) => {
      if (cancelled) return
      const hasRoutes = routes && Object.keys((routes as { routes?: Record<string, unknown> }).routes ?? {}).length > 0
      const s = sess as { world_plugin?: string; character_id?: string }
      if (!hasRoutes) setSystemState('no_llm')
      else if (!s.world_plugin) setSystemState('no_world')
      else setSystemState('ready')
    })
    return () => { cancelled = true }
  }, [sessionId])

  // 开场叙事：会话无任何叙事内容时自动触发一次（Phase 7B）
  const openingTriedRef = useRef<string | null>(null)
  useEffect(() => {
    if (openingTriedRef.current === sessionId) return
    let cancelled = false
    const t = setTimeout(() => {
      if (cancelled) return
      const cur = useStoryStore.getState().parts
      if (cur.length === 0 && !useUIStore.getState().inputDisabled) {
        openingTriedRef.current = sessionId
        setInputDisabled(true)
        api.generateOpening(sessionId)
          .then(r => { if (r.status === 'skipped') setInputDisabled(false) })
          .catch(() => setInputDisabled(false))
      }
    }, 1200)  // 等待 loadParts/loadMessages 完成后再判定是否为空
    return () => { cancelled = true; clearTimeout(t) }
  }, [sessionId, setInputDisabled])

  /** OOC 指令处理（/ 开头，不经过 Agent 管线） */
  const handleOOC = async (cmd: string): Promise<boolean> => {
    const parts_cmd = cmd.slice(1).trim().split(/\s+/)
    const verb = parts_cmd[0]?.toLowerCase()
    const arg = parts_cmd.slice(1).join(' ')

    const _note = (text: string) => addPart({
      id: `ooc-${Date.now()}`,
      message_id: '',
      type: 'dm_note',
      content: { note: text, system: true },
      status: 'done',
      agent: 'system',
    })

    switch (verb) {
      case 'mode':
        if (['play','plan','review'].includes(arg)) {
          await api.patch(`/sessions/${sessionId}/mode`, { mode: arg }).catch(() => {})
          setMode(arg as 'play' | 'plan' | 'review')
          _note(`✓ 模式已切换为 ${arg}`)
          return true
        }
        _note('用法：/mode play|plan|review')
        return true

      case 'fork': {
        const label = arg || `分支 ${new Date().toLocaleTimeString()}`
        try {
          const res = await api.post(`/sessions/${sessionId}/fork`, { branch_label: label })
          const newId = (res as { session_id: string }).session_id
          _note(`✓ 已创建分支会话（${label}）`)
          if (newId && onNavigateSession) {
            setTimeout(() => onNavigateSession(newId), 1000)
          }
        } catch {
          _note('❌ 创建分支失败')
        }
        return true
      }

      case 'stats': {
        try {
          const stats = await api.get(`/sessions/${sessionId}/stats`) as {
            turns: number
            dice: { total: number; passed: number; pass_rate: number }
            memory: { total: number; by_tier: Record<string, number> }
            chapters: { total: number; consolidated: number }
            npcs: number
          }
          const tierStr = Object.entries(stats.memory.by_tier)
            .map(([t, n]) => `${t}:${n}`).join(' ')
          _note(
            `📊 会话统计\n` +
            `  轮次：${stats.turns}\n` +
            `  骰子：${stats.dice.total} 次（通过率 ${(stats.dice.pass_rate * 100).toFixed(0)}%）\n` +
            `  记忆：${stats.memory.total} 条 [${tierStr}]\n` +
            `  章节：${stats.chapters.total}（已固化 ${stats.chapters.consolidated}）\n` +
            `  NPC：${stats.npcs} 位`
          )
        } catch {
          _note('❌ 统计数据获取失败')
        }
        return true
      }

      case 'clear': {
        clearSession()
        _note('✓ 前端显示已清空（历史数据保留在数据库）')
        return true
      }

      case 'help':
        _note(
          '可用 OOC 指令：\n' +
          '  /mode play|plan|review  — 切换游戏模式\n' +
          '  /fork [标签]            — 创建分支会话\n' +
          '  /stats                  — 显示会话统计\n' +
          '  /clear                  — 清空当前显示\n' +
          '  /help                   — 显示本帮助'
        )
        return true
    }
    return false
  }

  const handleSend = async () => {
    const content = input.trim()
    if (!content || inputDisabled) return
    setInput('')

    // OOC 指令（以 / 开头）
    if (content.startsWith('/')) {
      await handleOOC(content)
      return
    }

    setInputDisabled(true)
    setPipeline([])
    try {
      await api.sendMessage(sessionId, content)
      // inputDisabled=true 保持到 session.idle / session.error SSE 到达时清除
      // 如果 10 秒内没有响应，自动超时解锁（防止后端无响应导致 UI 永久 loading）
      setTimeout(() => setInputDisabled(false), 10_000)
    } catch {
      setInputDisabled(false)
    }
  }

  // ── 右侧面板内容（抽屉/固定栏复用） ────────────────────────────────────────
  const RightPanelContent = (
    <div className="flex flex-col h-full">
      <div className="flex border-b border-zinc-800 flex-shrink-0">
        {RIGHT_TABS.map(tab => (
          <button
            key={tab.id}
            title={tab.label}
            onClick={() => setRightTab(tab.id)}
            className={`flex-1 py-1.5 text-xs transition-colors ${
              rightTab === tab.id
                ? 'text-indigo-400 border-b border-indigo-500'
                : 'text-zinc-600 hover:text-zinc-400'
            }`}
          >
            {tab.icon}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        <React.Suspense fallback={<div className="text-xs text-zinc-600 p-2">加载中...</div>}>
          {rightTab === 'dice' && <DicePanel />}
          {rightTab === 'character' && <CharacterPanel />}
          {rightTab === 'world' && (
            <WorldPanel sessionId={sessionId} worldPlugin={worldPlugin} />
          )}
          {rightTab === 'memory' && <MemoryPanel sessionId={sessionId} />}
          {rightTab === 'economy' && <EconomyPanel sessionId={sessionId} />}
          {rightTab === 'combat' && <CombatPanel sessionId={sessionId} />}
          {rightTab === 'writing' && <WritingStylePanel sessionId={sessionId} />}
          {rightTab === 'history' && <HistoryPanel sessionId={sessionId} />}
        </React.Suspense>
        {rightTab === 'character' && character && (
          <div className="mt-2">
            <React.Suspense fallback={null}>
              <InventoryPanel items={inventory as never} />
            </React.Suspense>
          </div>
        )}
      </div>
    </div>
  )

  // ── 左侧章节树内容（抽屉/固定栏复用） ──────────────────────────────────────
  const LeftPanelContent = (
    <>
      <div className="px-3 py-2 border-b border-zinc-800 text-xs text-zinc-500 truncate">
        {sessionId.slice(0, 8)}
      </div>
      <div className="flex-1 overflow-y-auto">
        <ChapterTree
          sessionId={sessionId}
          onFork={(newId) => onNavigateSession?.(newId)}
          refreshKey={chapterRefreshKey}
        />
      </div>
    </>
  )

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100 overflow-hidden">

      {/* ── 左栏：章节树（≥1280px 固定显示，<1280px 进抽屉） ── */}
      <div className="hidden xl:flex w-52 flex-shrink-0 border-r border-zinc-800 flex-col overflow-hidden">
        {LeftPanelContent}
      </div>

      {/* ── 中栏：故事流（始终显示） ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* 顶栏 */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800 flex-shrink-0">
          {/* 移动/平板：左栏抽屉触发按钮 */}
          <button
            className="xl:hidden text-zinc-500 hover:text-zinc-300 mr-1 text-base leading-none"
            title="章节树"
            onClick={() => setLeftDrawerOpen(true)}
          >
            ☰
          </button>
          <span className="font-bold text-zinc-200 text-sm">零度武库</span>
          {/* 模型名 + 轮次指示器 */}
          {stats && (
            <div className="hidden sm:flex items-center gap-2 text-xs text-zinc-500">
              {stats.model && (
                <span className="bg-zinc-800 px-1.5 py-0.5 rounded font-mono" title="当前叙事模型">{stats.model}</span>
              )}
              {typeof stats.turns === 'number' && <span title="玩家行动轮次">· {stats.turns} 轮</span>}
            </div>
          )}
          <div className="ml-auto flex items-center gap-2">
            <ModeSelector
              mode={mode}
              onChange={(m) => setMode(m)}
              disabled={inputDisabled}
            />
            {/* 移动端：右栏抽屉触发按钮（<1024px） */}
            <button
              className="lg:hidden text-zinc-500 hover:text-zinc-300 text-base leading-none"
              title="面板"
              onClick={() => setRightDrawerOpen(true)}
            >
              ⊞
            </button>
          </div>
        </div>

        {/* Agent 管线节点可视化（生成中显示 rules→DM→...→done） */}
        {pipeline.length > 0 && (inputDisabled || pipeline.some(s => s.status === 'running')) && (
          <div className="flex items-center gap-1 px-3 py-1.5 border-b border-zinc-800/60 bg-zinc-900/40 overflow-x-auto text-xs">
            <span className="text-zinc-600 shrink-0 mr-1">管线</span>
            {pipeline.map((s, i) => (
              <React.Fragment key={`${s.agent}-${i}`}>
                {i > 0 && <span className="text-zinc-700">›</span>}
                <span className={`px-1.5 py-0.5 rounded shrink-0 flex items-center gap-1 ${
                  s.status === 'running' ? 'bg-indigo-600/20 text-indigo-300' : 'text-zinc-500'
                }`}>
                  {s.status === 'running' && <span className="animate-pulse">●</span>}
                  {AGENT_LABELS[s.agent] ?? s.agent}
                </span>
              </React.Fragment>
            ))}
          </div>
        )}

        {/* 开场生成提示 */}
        {parts.length === 0 && inputDisabled && (
          <div className="flex items-center justify-center gap-2 px-3 py-2 text-xs text-indigo-300 bg-indigo-900/20 border-b border-indigo-800/40">
            <span className="animate-pulse">●</span> 正在生成开场叙事...
          </div>
        )}

        {/* 故事流 */}
        <MessageThread
          parts={parts}
          mode={mode}
          onSelectOption={(text) => setInput(text)}
          className="flex-1"
          sending={inputDisabled}
          branchCount={branchCount}
          onForkFromMessage={handleForkFromMessage}
        />

        {/* 输入区 */}
        <InputBar
          value={input}
          onChange={setInput}
          onSend={handleSend}
          onStop={handleStop}
          sending={inputDisabled}
          activeAgent={activeAgent}
          actionOptions={latestOptions}
          onSelectOption={(text) => setInput(text)}
          directSelectOption
          systemState={systemState}
          lorebook={worldArchives.map(a => ({
            id: a.id,
            title: a.title,
            content: typeof a.content === 'string' ? a.content.slice(0, 60) : '',
          }))}
        />
      </div>

      {/* ── 右栏：标签式多功能面板（≥1024px 固定，<1024px 进抽屉） ── */}
      <div className="hidden lg:flex w-64 flex-shrink-0 border-l border-zinc-800 flex-col overflow-hidden">
        {RightPanelContent}
      </div>

      {/* ── 移动端/平板：左侧抽屉（章节树） ── */}
      <Drawer open={leftDrawerOpen} onClose={closeLeft} side="left" title="章节树">
        {LeftPanelContent}
      </Drawer>

      {/* ── 移动端：右侧抽屉（功能面板，< 1024px） ── */}
      <Drawer open={rightDrawerOpen} onClose={closeRight} side="right" title="面板">
        {RightPanelContent}
      </Drawer>

      {/* ── 权限请求弹窗 ── */}
      {pendingAsks.map((ask) => (
        <PermissionDialog
          key={ask.ask_id}
          ask={ask}
          sessionId={sessionId}
          onResolved={() => removePendingAsk(ask.ask_id)}
        />
      ))}
    </div>
  )
}

// 可见性过滤逻辑已移入 MessageThread 组件
