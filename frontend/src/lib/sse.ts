/**
 * SSE 客户端 — 带 Last-Event-ID 续传与指数退避重连
 * 参考 opencode SSE 客户端设计
 */

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
    const url = `/api/sessions/${this.sessionId}/events`
    if (this.lastEventId) {
      return `${url}?last_event_id=${encodeURIComponent(this.lastEventId)}`
    }
    return url
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
      if (!this.closed && this.retryCount < this.maxRetry) {
        const delay = Math.min(30000, 1000 * 2 ** this.retryCount)
        this.retryCount++
        setTimeout(() => this._connect(), delay)
      }
    }

    this.es.onopen = () => {
      this.retryCount = 0
      this._resetHeartbeat()
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
