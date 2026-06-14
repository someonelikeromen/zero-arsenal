/**
 * bindSSEToStores — SSE 事件路由中枢
 * 设计文档 12-frontend-architecture.md §3.3
 *
 * 将 BusEvent 分发到各 Zustand Store，与 SessionPage 解耦。
 * SessionPage 只需调用 createSSEHandler(deps) 获取 onEvent 回调，
 * 无需在组件内部维护庞大的 switch-case。
 *
 * 用法示例：
 *   const onEvent = createSSEHandler({
 *     storyStore, sessionStore, characterStore,
 *     setSending, setActiveAgent, setChapterRefreshKey,
 *   })
 *   connectSSE(sessionId, onEvent)
 */
import type { BusEvent } from './sse'
import type { MessagePart } from '../stores/story'
import type { DiceRoll } from '../stores/dice'

// ── 依赖接口（各 store 的 action subset + 局部 state setter） ─────────────────

export interface SSEHandlerDeps {
  /** StoryStore actions */
  addPart: (part: MessagePart) => void
  appendDelta: (partId: string, delta: string) => void
  finalizePart: (partId: string, content: Record<string, unknown>) => void
  /** StyleAgent 润色替换（part.done with _polished:true） */
  updatePartContent?: (partId: string, content: Record<string, unknown>) => void

  /** CharacterStore actions */
  applyPatch: (patches: Array<{ cmd: string; key: string; value: string; delta: number | null }>) => void

  /** SessionStore actions */
  addPendingAsk: (ask: { ask_id: string; tool_name: string; tool_args: unknown; reason: string }) => void
  removePendingAsk: (askId: string) => void
  setMode: (mode: 'play' | 'plan' | 'review') => void

  /** DiceStore actions (差距027) */
  addDiceRoll: (roll: DiceRoll) => void

  /** SessionPage local state setters */
  setSending: (v: boolean) => void
  setActiveAgent: (agent: string | null) => void
  setChapterRefreshKey: (updater: (k: number) => number) => void
  /** 任意 SSE 事件到达时触发（用于兜底解锁的「活动心跳」判定，NEW-C14-02） */
  onActivity?: () => void
}

// ── 事件处理工厂 ──────────────────────────────────────────────────────────────

/**
 * 创建 SSE onEvent 回调。
 * 每次 sessionId 变化时重新调用（deps 对象按引用传入，保持最新闭包）。
 */
export function createSSEHandler(deps: SSEHandlerDeps): (e: BusEvent) => void {
  const {
    addPart, appendDelta, finalizePart,
    updatePartContent,
    applyPatch,
    addPendingAsk, removePendingAsk, setMode,
    addDiceRoll,
    setSending, setActiveAgent, setChapterRefreshKey,
    onActivity,
  } = deps

  return function onEvent(e: BusEvent): void {
    // 记录一次 SSE 活动（除 connection.failed 这类终止性事件外都算进度）
    if (onActivity && e.type !== 'connection.failed') onActivity()

    switch (e.type) {

      // ── Part 生命周期 ──────────────────────────────────────────────────────
      case 'part.created': {
        const d = e.data as {
          part_id: string; part_type: string; message_id: string; agent: string
          tool_name?: string
        }
        // tool_call part 在创建时即携带 tool_name，避免执行期间显示「未知工具」
        const initialContent: Record<string, unknown> =
          d.part_type === 'tool_call' && d.tool_name
            ? { tool_name: d.tool_name, status: 'pending' }
            : {}
        addPart({
          id: d.part_id,
          message_id: d.message_id,
          type: d.part_type as MessagePart['type'],
          content: initialContent,
          status: 'streaming',
          agent: d.agent,
          streamBuffer: d.part_type === 'narrative' ? '' : undefined,
        })
        break
      }

      case 'part.updated': {
        const d = e.data as { part_id: string; delta: string }
        appendDelta(d.part_id, d.delta)
        break
      }

      case 'part.done': {
        const d = e.data as {
          part_id: string
          content: Record<string, unknown>
          part_type?: string
        }
        // StyleAgent 润色替换：_polished:true 表示已有 done 的 part 被后处理修改
        if (d.content?._polished && updatePartContent) {
          updatePartContent(d.part_id, d.content)
        } else {
          finalizePart(d.part_id, d.content)
        }
        // state_patch → 实时更新角色面板
        if (d.part_type === 'state_patch' || (d.content && Array.isArray(d.content.patches))) {
          const patches = d.content.patches as Array<{
            cmd: string; key: string; value: string; delta: number | null
          }>
          if (patches?.length) applyPatch(patches)
        }
        // dice_roll → 推入 diceStore（差距027）
        if (d.part_type === 'dice_roll' && d.content) {
          const c = d.content
          addDiceRoll({
            roll_id: d.part_id,
            pool: (c.pool as number) ?? 0,
            successes: (c.successes as number) ?? 0,
            outcome: (c.verdict as 'success' | 'failure' | 'critical') ?? 'failure',
            attribute: (c.attribute as string) ?? '',
            skill: c.skill as string | undefined,
            modifier: c.modifier as number | undefined,
            detail: (c.rolls as number[]) ?? [],
            created_at: Date.now(),
            message_id: undefined,
          })
        }
        break
      }

      // ── 权限询问 ───────────────────────────────────────────────────────────
      case 'permission.ask': {
        const d = e.data as { ask_id: string; tool_name: string; tool_args: unknown; reason: string }
        addPendingAsk(d)
        break
      }

      case 'permission.granted':
      case 'permission.denied': {
        const d = e.data as { ask_id: string }
        if (d.ask_id) removePendingAsk(d.ask_id)
        break
      }

      // ── Agent 状态 ─────────────────────────────────────────────────────────
      case 'agent.started': {
        const d = e.data as { agent: string }
        setActiveAgent(d.agent)
        break
      }

      case 'agent.ended': {
        setActiveAgent(null)
        break
      }

      // ── Session 状态 ───────────────────────────────────────────────────────
      case 'session.idle': {
        setSending(false)
        setActiveAgent(null)
        break
      }

      case 'session.error': {
        const d = e.data as { error: string; recoverable: boolean }
        setSending(false)
        addPart({
          id: `err-${Date.now()}`,
          message_id: '',
          type: 'dm_note',
          content: { note: `系统错误: ${d.error}`, error: true },
          status: 'done',
          agent: 'system',
        })
        break
      }

      case 'session.mode_changed': {
        const d = e.data as { mode: string; previous_mode?: string; active_tools?: string[] }
        setMode(d.mode as 'play' | 'plan' | 'review')
        break
      }

      // ── 连接彻底失败（conf_b09 §5/§9：4xx 终止 或 超过最大重试）─────────────
      case 'connection.failed': {
        const d = e.data as { reason?: string; terminal?: boolean }
        setSending(false)
        setActiveAgent(null)
        addPart({
          id: `conn-failed-${Date.now()}`,
          message_id: '',
          type: 'dm_note',
          content: {
            note: d.terminal
              ? '连接已断开（会话不存在或无访问权限），已停止重连。请返回会话列表或刷新页面。'
              : '连接多次重试仍失败，已暂停重连。请检查网络后刷新页面手动重连。',
            error: true,
          },
          status: 'done',
          agent: 'system',
        })
        // 派发窗口事件，便于上层提供「手动重连」入口
        window.dispatchEvent(new CustomEvent('sse.connection.failed', { detail: d }))
        break
      }

      // ── 回合完成（每回合 anchor 写入后，02-arch §8）─────────────────────────
      case 'turn.complete': {
        // 静默确认：回合锚点已写入，无需前端动作（保留供调试扩展）
        break
      }

      // ── 章节事件 ───────────────────────────────────────────────────────────
      case 'chapter.consolidated': {
        const d = e.data as { chapter_id: string }
        window.dispatchEvent(new CustomEvent('chapter.consolidated', { detail: d }))
        setChapterRefreshKey((k) => k + 1)
        break
      }

      // 未处理的事件类型静默忽略（允许后端扩展新事件而不 crash）
      default:
        break
    }
  }
}
