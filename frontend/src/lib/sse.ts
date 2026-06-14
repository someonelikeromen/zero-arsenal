/**
 * SSE 客户端 — 带 Last-Event-ID 续传与指数退避重连
 * 参考 opencode SSE 客户端设计
 */
import { apiHeaders, apiSseUrl } from './api'

export interface BusEvent {
  type: string
  data: Record<string, unknown>
}

export type EventHandler = (event: BusEvent) => void

/** Heartbeat 超时（ms）— 服务端每 10s 发一次 heartbeat，30s 无响应视为断线 */
const HEARTBEAT_TIMEOUT_MS = 30_000

export class SSEClient {
  private sessionId: string
  private handlers: Map<string, EventHandler[]> = new Map()
  private es: EventSource | null = null
  private lastEventId: string | null = null
  private retryCount = 0
  private maxRetry = 8
  private closed = false
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null

  constructor(sessionId: string) {
    this.sessionId = sessionId
  }

  on(type: string, handler: EventHandler): this {
    const list = this.handlers.get(type) ?? []
    list.push(handler)
    this.handlers.set(type, list)
    return this
  }

  onAny(handler: EventHandler): this {
    return this.on('*', handler)
  }

  async restoreLastEventId(): Promise<void> {
    try {
      const { cache } = await import('../lib/idb')
      const saved = await cache.getLastSyncedEventId(this.sessionId)
      if (saved && !this.lastEventId) {
        this.lastEventId = saved
      }
    } catch {
      // IndexedDB 不可用时跳过
    }
  }

  connect(): this {
    this.closed = false
    // 尝试从 IndexedDB 恢复 lastEventId，然后连接
    this.restoreLastEventId().then(() => this._connect()).catch(() => this._connect())
    return this
  }

  private _buildUrl(): string {
    const path = `/sessions/${this.sessionId}/events`
    if (this.lastEventId) {
      return apiSseUrl(`${path}?last_event_id=${encodeURIComponent(this.lastEventId)}`)
    }
    return apiSseUrl(path)
  }

  private _connect(): void {
    const url = this._buildUrl()
    this.es = new EventSource(url)

    this.es.onmessage = (e) => {
      if (e.lastEventId) {
        this.lastEventId = e.lastEventId
        // 持久化到 IndexedDB（用于刷新/断线后恢复）
        import('../lib/idb').then(({ cache }) => {
          cache.setLastSyncedEventId(this.sessionId, e.lastEventId).catch(() => {})
        }).catch(() => {})
      }
      // 任何消息都重置 heartbeat 计时器
      this._resetHeartbeat()
      try {
        const parsed: BusEvent = JSON.parse(e.data)
        this._dispatch(parsed)
      } catch {
        // ignore parse errors
      }
    }

    this.es.onerror = () => {
      this._clearHeartbeat()
      this.es?.close()
      this.es = null
      if (this.closed) return
      // EventSource 不暴露 HTTP 状态码，主动探测一次以区分「4xx 终止」与「可恢复网络抖动」
      void this._handleError()
    }

    this.es.onopen = () => {
      this.retryCount = 0
      this._resetHeartbeat()
    }
  }

  /**
   * 断线处理（conf_b09 §9.1）：
   * - 探测 events 端点 HTTP 状态：4xx（404/410/401/403…）= 终止性错误，停止重连并派发 connection.failed
   * - 5xx / 网络不可达 = 可恢复，指数退避（含 jitter，避免惊群）重连
   * - 超过 maxRetry 仍失败 = 派发 connection.failed，交由 UI 提示手动重连
   */
  private async _handleError(): Promise<void> {
    const terminal = await this._probeTerminal()
    if (this.closed) return
    if (terminal) {
      this.closed = true
      this._dispatch({ type: 'connection.failed', data: { reason: 'http_4xx', terminal: true } })
      return
    }
    if (this.retryCount >= this.maxRetry) {
      this.closed = true
      this._dispatch({ type: 'connection.failed', data: { reason: 'max_retry', terminal: false } })
      return
    }
    // 指数退避 + jitter（0–1000ms 随机抖动）
    const base = Math.min(30000, 1000 * 2 ** this.retryCount)
    const delay = base + Math.floor(Math.random() * 1000)
    this.retryCount++
    setTimeout(() => { if (!this.closed) this._connect() }, delay)
  }

  /** 探测 SSE 端点状态码，返回 true 表示遇到 4xx 终止性错误。 */
  private async _probeTerminal(): Promise<boolean> {
    const ctrl = new AbortController()
    try {
      const res = await fetch(this._buildUrl(), {
        method: 'GET',
        headers: apiHeaders({ Accept: 'text/event-stream' }, false),
        signal: ctrl.signal,
      })
      // 立即中断流式响应体，仅取状态码
      ctrl.abort()
      return res.status >= 400 && res.status < 500
    } catch {
      // 网络不可达 / 已中断 → 视为可恢复
      return false
    }
  }

  private _dispatch(event: BusEvent): void {
    const list = this.handlers.get(event.type) ?? []
    for (const h of list) h(event)
    const wildcards = this.handlers.get('*') ?? []
    for (const h of wildcards) h(event)
  }

  private _resetHeartbeat(): void {
    this._clearHeartbeat()
    this.heartbeatTimer = setTimeout(() => {
      // Heartbeat 超时：强制重连
      if (!this.closed) {
        console.warn('[SSE] heartbeat timeout, reconnecting...')
        this.es?.close()
        this.es = null
        this._connect()
      }
    }, HEARTBEAT_TIMEOUT_MS)
  }

  private _clearHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearTimeout(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  disconnect(): void {
    this.closed = true
    this._clearHeartbeat()
    this.es?.close()
    this.es = null
  }
}
