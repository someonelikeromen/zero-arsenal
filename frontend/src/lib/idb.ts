/**
 * IndexedDB 本地缓存层
 * 设计文档 12-frontend-architecture.md §9
 * 缓存会话列表、最近消息、角色卡——离线优先 + 快速冷启动
 */

const DB_NAME = 'zero_arsenal'
const DB_VERSION = 1

type StoreName = 'sessions' | 'messages' | 'parts' | 'character'

interface IDBStore {
  sessions: { id: string; data: unknown; ts: number }
  messages: { id: string; session_id: string; data: unknown; ts: number }
  parts:    { id: string; session_id: string; data: unknown; ts: number }
  character:{ session_id: string; data: unknown; ts: number }
}

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains('sessions')) {
        db.createObjectStore('sessions', { keyPath: 'id' })
      }
      if (!db.objectStoreNames.contains('messages')) {
        const ms = db.createObjectStore('messages', { keyPath: 'id' })
        ms.createIndex('by_session', 'session_id')
      }
      if (!db.objectStoreNames.contains('parts')) {
        const ps = db.createObjectStore('parts', { keyPath: 'id' })
        ps.createIndex('by_session', 'session_id')
      }
      if (!db.objectStoreNames.contains('character')) {
        db.createObjectStore('character', { keyPath: 'session_id' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

/**
 * 每个 store 的最大条目数（D22：LRU 驱逐上限）。
 * 超过上限时，按 `ts`（最后访问时间）升序删除最久未访问的条目。
 */
const STORE_LIMITS: Record<StoreName, number> = {
  sessions: 200,
  messages: 2000,
  parts: 5000,
  character: 200,
}

async function idbPut<S extends StoreName>(
  store: S,
  value: IDBStore[S]
): Promise<void> {
  const db = await openDB()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite')
    tx.objectStore(store).put(value)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
  // 写入后异步执行 LRU 驱逐（不阻塞主流程）
  void enforceLimit(store, STORE_LIMITS[store]).catch(() => {})
}

/**
 * LRU 驱逐：将 store 条目数压缩到 limit 以内，优先删除 `ts` 最小（最久未访问）者。
 * `sse_cursor:` 前缀的续传游标条目永不驱逐。
 */
async function enforceLimit(store: StoreName, limit: number): Promise<void> {
  const db = await openDB()
  const rows: Array<{ ts: number; key: IDBValidKey; protect: boolean }> = await new Promise(
    (resolve, reject) => {
      const tx = db.transaction(store, 'readonly')
      const os = tx.objectStore(store)
      const keyPath = os.keyPath as string
      const req = os.getAll()
      req.onsuccess = () => {
        const list = (req.result as Array<Record<string, unknown>>).map((r) => {
          const key = r[keyPath] as IDBValidKey
          return {
            ts: typeof r.ts === 'number' ? r.ts : 0,
            key,
            protect: typeof key === 'string' && key.startsWith('sse_cursor:'),
          }
        })
        resolve(list)
      }
      req.onerror = () => reject(req.error)
    }
  )
  const evictable = rows.filter((r) => !r.protect)
  if (evictable.length <= limit) return
  evictable.sort((a, b) => a.ts - b.ts)
  const toDelete = evictable.slice(0, evictable.length - limit)
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite')
    const os = tx.objectStore(store)
    for (const d of toDelete) os.delete(d.key)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

/** 触碰条目：更新 `ts` 为当前时间，使 LRU 反映最后访问而非仅写入时间。 */
async function idbTouch(store: StoreName, key: IDBValidKey): Promise<void> {
  try {
    const db = await openDB()
    await new Promise<void>((resolve) => {
      const tx = db.transaction(store, 'readwrite')
      const os = tx.objectStore(store)
      const req = os.get(key)
      req.onsuccess = () => {
        const row = req.result as Record<string, unknown> | undefined
        if (row) {
          row.ts = Date.now()
          os.put(row)
        }
        resolve()
      }
      req.onerror = () => resolve()
    })
  } catch {
    // 触碰失败不影响主流程
  }
}

async function idbGet<S extends StoreName>(
  store: S,
  key: string
): Promise<IDBStore[S] | undefined> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readonly')
    const req = tx.objectStore(store).get(key)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function idbGetByIndex<S extends StoreName>(
  store: S,
  indexName: string,
  key: string
): Promise<IDBStore[S][]> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readonly')
    const idx = tx.objectStore(store).index(indexName)
    const req = idx.getAll(key)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function idbDelete(store: StoreName, key: string): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite')
    tx.objectStore(store).delete(key)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

// ── 高层封装 ─────────────────────────────────────────────────────────────────

const STALE_MS = 5 * 60 * 1000  // 5 分钟缓存有效期

export const cache = {
  /** 缓存会话列表条目 */
  async putSession(id: string, data: unknown): Promise<void> {
    await idbPut('sessions', { id, data, ts: Date.now() })
  },

  async getSession(id: string): Promise<unknown | null> {
    const row = await idbGet('sessions', id)
    if (!row || Date.now() - row.ts > STALE_MS) return null
    void idbTouch('sessions', id)
    return row.data
  },

  /** 缓存角色卡 */
  async putCharacter(session_id: string, data: unknown): Promise<void> {
    await idbPut('character', { session_id, data, ts: Date.now() })
  },

  async getCharacter(session_id: string): Promise<unknown | null> {
    const row = await idbGet('character', session_id)
    if (!row || Date.now() - row.ts > STALE_MS) return null
    void idbTouch('character', session_id)
    return row.data
  },

  /** 缓存 Parts */
  async putPart(id: string, session_id: string, data: unknown): Promise<void> {
    await idbPut('parts', { id, session_id, data, ts: Date.now() })
  },

  async getPartsBySession(session_id: string): Promise<unknown[]> {
    const rows = await idbGetByIndex('parts', 'by_session', session_id)
    const fresh = rows.filter(r => Date.now() - r.ts < STALE_MS * 6)
    // 触碰命中的 parts，使其在 LRU 中保持「最近访问」
    for (const r of fresh) void idbTouch('parts', r.id)
    return fresh
      .sort((a, b) => a.ts - b.ts)
      .map(r => r.data)
  },

  /** 清除会话相关所有缓存 */
  async clearSession(session_id: string): Promise<void> {
    await idbDelete('sessions', session_id)
    await idbDelete('character', session_id)
    const parts = await idbGetByIndex('parts', 'by_session', session_id)
    for (const p of parts) {
      await idbDelete('parts', (p as { id: string }).id)
    }
    const msgs = await idbGetByIndex('messages', 'by_session', session_id)
    for (const m of msgs) {
      await idbDelete('messages', (m as { id: string }).id)
    }
  },

  /**
   * SSE 断点续传：记录最后一次成功接收的 event ID（对应 SSE Last-Event-ID）。
   * 设计文档 09 §5 "Last-Event-ID 断点续传"
   */
  async getLastSyncedEventId(session_id: string): Promise<string | null> {
    try {
      const row = await idbGet('sessions', `sse_cursor:${session_id}`)
      return (row as { id: string; data: string; ts: number } | undefined)?.data ?? null
    } catch {
      return null
    }
  },

  async setLastSyncedEventId(session_id: string, eventId: string): Promise<void> {
    try {
      await idbPut('sessions', {
        id: `sse_cursor:${session_id}`,
        data: eventId,
        ts: Date.now(),
      } as unknown as IDBStore['sessions'])
    } catch {
      // 写缓存失败不影响主流程
    }
  },
}
