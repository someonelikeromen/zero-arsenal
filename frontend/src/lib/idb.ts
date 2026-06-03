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

async function idbPut<S extends StoreName>(
  store: S,
  value: IDBStore[S]
): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite')
    tx.objectStore(store).put(value)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
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
    return row.data
  },

  /** 缓存角色卡 */
  async putCharacter(session_id: string, data: unknown): Promise<void> {
    await idbPut('character', { session_id, data, ts: Date.now() })
  },

  async getCharacter(session_id: string): Promise<unknown | null> {
    const row = await idbGet('character', session_id)
    if (!row || Date.now() - row.ts > STALE_MS) return null
    return row.data
  },

  /** 缓存 Parts */
  async putPart(id: string, session_id: string, data: unknown): Promise<void> {
    await idbPut('parts', { id, session_id, data, ts: Date.now() })
  },

  async getPartsBySession(session_id: string): Promise<unknown[]> {
    const rows = await idbGetByIndex('parts', 'by_session', session_id)
    return rows
      .filter(r => Date.now() - r.ts < STALE_MS * 6)
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
