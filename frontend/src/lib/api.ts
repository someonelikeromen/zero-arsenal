/**
 * API 客户端 — 封装所有后端 HTTP 调用
 */

const BASE = '/api'

export interface Session {
  session_id: string
  title: string
  world_plugin: string
  agent_profile: string
  current_mode: 'play' | 'plan' | 'review'
  /** @deprecated use current_mode */
  mode?: 'play' | 'plan' | 'review'
  status: 'active' | 'deleted'
  created_at: string
  character: Record<string, unknown> | null
}

export interface ForkSessionResult {
  new_session_id: string
  parent_session_id: string
  branch_label: string
  forked_from_message_id: string | null
  created_at: string
  messages_copied: number
}

export interface ChapterTree {
  session_id: string
  chapters: Array<{
    chapter_id: string
    title: string
    is_consolidated: boolean
    created_at: string
    children: Array<unknown>
  }>
}

export interface PagedMessages {
  messages: unknown[]
  next_cursor: string | null
  has_more: boolean
}

export interface CreateSessionReq {
  world_plugin?: string
  agent_profile?: string
  title?: string
  character_data?: Record<string, unknown>
  /** 引用已建好的世界模板（NEW-C14-01：补齐后端已支持但前端缺失的字段） */
  world_id?: string
  /** 引用已建好的人物模板 */
  character_template_id?: string
}

export interface DiceRollResult {
  roll_id?: string       // 历史记录 ID（来自 dice_log 表）
  pool: number
  threshold: number
  rolls: number[]
  successes: number
  ones: number
  net: number
  result: string
  botch: boolean
  verdict: 'success' | 'failure' | 'botch' | 'critical'
  narrative_hint: string
  attribute: string
  skill?: string
  reason: string
  pool_formula: string
  timestamp: string
  modifier?: number      // 调整值（来自 dice_log.input_json）
}

export interface RollRequest {
  pool?: number
  attribute?: string
  skill?: string
  modifier?: number
  threshold?: number
  character_data?: Record<string, unknown>
  reason?: string
  session_id?: string
  message_id?: string
}

/**
 * 统一 HTTP 调用入口：拼接 BASE、注入默认 header、对 !res.ok 抛错（带 body）。
 * 各 store 应复用本函数而非裸 fetch，保证 base URL / 鉴权头 / 错误语义一致
 * （NEW-C13-03）。导出供 stores 直接调用。
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API ${path} → ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  createSession: (req: CreateSessionReq) =>
    apiFetch<Session & { chapter_id: string }>('/sessions', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  listSessions: () =>
    apiFetch<{ items: Session[]; next_cursor: string | null; has_more: boolean; total: number }>('/sessions'),

  getSession: (id: string) => apiFetch<Session>(`/sessions/${id}`),

  sendMessage: (sessionId: string, content: string, messageType = 'player_action') =>
    apiFetch<{ message_id: string; session_id: string; status: string; stream_url: string }>(
      `/sessions/${sessionId}/message`,
      {
        method: 'POST',
        body: JSON.stringify({ content, message_type: messageType }),
      }
    ),

  setMode: (sessionId: string, mode: string) =>
    apiFetch<{ mode: string }>(`/sessions/${sessionId}/mode`, {
      method: 'POST',
      body: JSON.stringify({ mode }),
    }),

  forkSession: (sessionId: string, branchLabel: string, forkFromMessageId?: string) =>
    apiFetch<ForkSessionResult>(`/sessions/${sessionId}/fork`, {
      method: 'POST',
      body: JSON.stringify({ branch_label: branchLabel, fork_from_message_id: forkFromMessageId }),
    }),

  getCharacter: (sessionId: string) =>
    apiFetch<{ character: Record<string, unknown>; schema_version: string }>(
      `/sessions/${sessionId}/character`
    ),

  getMessages: (sessionId: string) =>
    apiFetch<unknown[]>(`/sessions/${sessionId}/messages`),

  getChapters: (sessionId: string) =>
    apiFetch<ChapterTree>(`/sessions/${sessionId}/chapters`),

  rollDice: (req: RollRequest) =>
    apiFetch<DiceRollResult>('/engine/roll', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  getDiceHistory: (sessionId: string, limit = 20) =>
    apiFetch<{ history: unknown[]; count: number }>(`/sessions/${sessionId}/dice-history?limit=${limit}`),

  getParts: (sessionId: string, messageId?: string, partType?: string) => {
    const params = new URLSearchParams()
    if (messageId) params.set('message_id', messageId)
    if (partType) params.set('part_type', partType)
    return apiFetch<{ parts: unknown[]; count: number }>(
      `/sessions/${sessionId}/parts?${params}`
    )
  },

  revertToMessage: (sessionId: string, messageId: string) =>
    apiFetch<{ reverted_to: string; turn_index: number }>(`/sessions/${sessionId}/revert`, {
      method: 'POST',
      body: JSON.stringify({ message_id: messageId }),
    }),

  patchCharacter: (sessionId: string, patches: unknown[], rawJson?: unknown) =>
    apiFetch<{ character: Record<string, unknown> }>(`/sessions/${sessionId}/character`, {
      method: 'PATCH',
      body: JSON.stringify({ patches, raw_json: rawJson }),
    }),

  getWorldArchives: (sessionId: string) =>
    apiFetch<{ archives: unknown[]; count: number }>(`/sessions/${sessionId}/world-archives`),

  // ── 开场叙事 ───────────────────────────────────────────────────────────────
  generateOpening: (sessionId: string) =>
    apiFetch<{ status: string; message_id?: string }>(`/sessions/${sessionId}/opening`, {
      method: 'POST', body: '{}',
    }),

  // ── 取消生成 ───────────────────────────────────────────────────────────────
  cancelStream: (sessionId: string) =>
    apiFetch<{ ok: boolean; cancelled: boolean }>(`/sessions/${sessionId}/stream`, { method: 'DELETE' }),

  // ── MCP 服务器 ─────────────────────────────────────────────────────────────
  listMcpServers: () =>
    apiFetch<{ servers: Array<{ id: string; command?: string; args?: string[]; enabled?: boolean }>; total: number }>('/mcp/servers'),
  connectMcp: (req: { server_id: string; command: string; args?: string[]; env?: Record<string, string>; enabled?: boolean }) =>
    apiFetch<{ registered: number; server_id: string }>('/mcp/connect', {
      method: 'POST', body: JSON.stringify(req),
    }),
  disconnectMcp: (serverId: string) =>
    apiFetch<{ removed_tools: string[]; count: number }>(`/mcp/${serverId}`, { method: 'DELETE' }),

  // ── 引擎规则 ───────────────────────────────────────────────────────────────
  listExtensions: () =>
    apiFetch<{ extensions: Array<{ key: string; name: string; description?: string; agent_profile?: string }>; count: number }>('/engine/extensions'),
  listEngineRules: () =>
    apiFetch<{ rules: Array<{ id: string; name?: string; description?: string; enabled?: boolean; active?: boolean }>; count: number }>('/engine/rules'),
  activateRule: (ruleId: string, enabled: boolean) =>
    apiFetch<{ rule_id: string; enabled: boolean }>(`/engine/rules/${ruleId}/activate?enabled=${enabled}`, {
      method: 'POST', body: '{}',
    }),

  // ── 文风 ───────────────────────────────────────────────────────────────────
  getWritingStyles: () =>
    apiFetch<{ styles: Array<{ name: string; description?: string }>; total: number }>('/config/writing-styles'),
  getSessionWritingStyles: (sessionId: string) =>
    apiFetch<{ writing_styles: string[] }>(`/sessions/${sessionId}/writing-styles`),
  setSessionWritingStyles: (sessionId: string, styles: string[]) =>
    apiFetch<{ ok: boolean; writing_styles: string[] }>(`/sessions/${sessionId}/writing-styles`, {
      method: 'PUT', body: JSON.stringify({ writing_styles: styles }),
    }),

  // ── 经济 & 战斗 ────────────────────────────────────────────────────────────
  getEconomy: (sessionId: string) =>
    apiFetch<{
      world_plugin: string
      currency: string
      balance: number
      badges: unknown[]
      battle_points: number
      pools: Array<{ id: string; display_name?: string; cost_per_draw?: number; description?: string }>
      shop: unknown
      has_economy: boolean
    }>(`/engine/economy/${sessionId}`),
  combatAction: (req: {
    session_id: string; action?: 'damage' | 'heal'; amount: number; part?: string
    damage_type?: string; attacker_tier?: number; is_critical?: boolean | null; bypass_armor?: boolean
  }) =>
    apiFetch<{
      ok: boolean; action: string; result: Record<string, unknown>
      overall_hp_ratio: number; parts: Record<string, { current: number; max: number; status_effects?: string[] }>
    }>(`/engine/combat`, { method: 'POST', body: JSON.stringify(req) }),

  // ── 记忆管理 ───────────────────────────────────────────────────────────────
  browseMemory: (sessionId: string, tier?: string, topK = 50) => {
    const params = new URLSearchParams({ top_k: String(topK) })
    if (tier) params.set('tier', tier)
    return apiFetch<{ results: string; entries: Array<{ id: string; content: string; tier: string; source_agent: string; created_at: number }>; full_mode: boolean }>(
      `/sessions/${sessionId}/memory?${params}`
    )
  },
  consolidateMemory: (sessionId: string) =>
    apiFetch<{ status: string } & Record<string, unknown>>(`/sessions/${sessionId}/memory/consolidate`, {
      method: 'POST', body: '{}',
    }),
  rollbackMemory: (sessionId: string, req: { chapter_id?: string; since_iso?: string }) =>
    apiFetch<{ status: string; result: unknown }>(`/sessions/${sessionId}/memory/rollback`, {
      method: 'POST', body: JSON.stringify(req),
    }),

  // ── 会话内 NPC CRUD ────────────────────────────────────────────────────────
  listSessionNpcs: (sessionId: string) =>
    apiFetch<{ npcs: Array<{ id: string; key: string; name: string; world_key: string; profile: Record<string, unknown> }> }>(
      `/sessions/${sessionId}/npcs`
    ),
  createSessionNpc: (sessionId: string, req: { name: string; key?: string; profile?: Record<string, unknown> }) =>
    apiFetch<{ npc_id: string; key: string; name: string }>(`/sessions/${sessionId}/npcs`, {
      method: 'POST', body: JSON.stringify(req),
    }),
  updateSessionNpc: (sessionId: string, npcKey: string, req: { name?: string; profile?: Record<string, unknown> }) =>
    apiFetch<{ ok: boolean }>(`/sessions/${sessionId}/npcs/${npcKey}`, {
      method: 'PATCH', body: JSON.stringify(req),
    }),
  deleteSessionNpc: (sessionId: string, npcKey: string) =>
    apiFetch<{ ok: boolean }>(`/sessions/${sessionId}/npcs/${npcKey}`, { method: 'DELETE' }),

  createWorldArchive: (sessionId: string, title: string, content: unknown, archiveType = 'lore') =>
    apiFetch<{ archive_id: string; title: string }>(`/sessions/${sessionId}/world-archives`, {
      method: 'POST',
      body: JSON.stringify({ title, content, archive_type: archiveType }),
    }),

  searchMemory: (sessionId: string, query: string, topK = 8) =>
    apiFetch<{ results: string; full_mode: boolean }>(
      `/sessions/${sessionId}/memory?q=${encodeURIComponent(query)}&top_k=${topK}`
    ),

  addMemory: (sessionId: string, content: string, nodeType = 'event') =>
    apiFetch<{ added: boolean }>(`/sessions/${sessionId}/memory`, {
      method: 'POST',
      body: JSON.stringify({ content, node_type: nodeType }),
    }),

  resolveAsk: (sessionId: string, askId: string, decision: 'allow' | 'deny') =>
    apiFetch<{ ask_id: string; decision: string }>(`/sessions/${sessionId}/asks/${askId}`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),

  deleteSession: (sessionId: string) =>
    apiFetch<{ deleted: boolean }>(`/sessions/${sessionId}`, { method: 'DELETE' }),

  rollbackToChapter: (sessionId: string, chapterId: string) =>
    apiFetch<{
      session_id: string
      rolled_back_to: string
      deleted_chapters: string[]
      character_state_restored: boolean
    }>(
      `/sessions/${sessionId}/chapters/${chapterId}/rollback`,
      { method: 'POST', body: JSON.stringify({ confirm: true, create_branch: false }) }
    ),

  getSystemInfo: () =>
    apiFetch<Record<string, unknown>>('/system/info'),

  getMemoryHealth: () =>
    apiFetch<{ ok: boolean; memory: Record<string, unknown> }>('/config/system/memory-health'),

  // Config API (11 §5)
  listWorldPlugins: () =>
    apiFetch<{ plugins: unknown[]; total: number }>('/config/world-plugins'),

  // Sessions with cursor pagination
  listSessionsPaged: (status = 'active', limit = 20, cursor?: string, worldPlugin?: string) => {
    const params = new URLSearchParams({ status, limit: String(limit) })
    if (cursor) params.set('cursor', cursor)
    if (worldPlugin) params.set('world_plugin', worldPlugin)
    return apiFetch<{ items: Session[]; next_cursor: string | null; has_more: boolean; total: number }>(
      `/sessions?${params}`
    )
  },

  // Messages with cursor pagination
  getMessagesPaged: (sessionId: string, limit = 50, cursor?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (cursor) params.set('cursor', cursor)
    return apiFetch<PagedMessages>(`/sessions/${sessionId}/messages?${params}`)
  },

  // Manual chapter consolidation
  consolidateChapter: (sessionId: string) =>
    apiFetch<{ chapter_id: string; summary: string }>(
      `/sessions/${sessionId}/chapters/consolidate`,
      { method: 'POST', body: '{}' }
    ),

  // LLM 路由配置
  getLlmRoutes: () =>
    apiFetch<{ routes: Record<string, unknown>; source: string }>('/config/llm-routes'),

  updateLlmRoute: (req: {
    agent: string; provider: string; model: string;
    temperature?: number; max_tokens?: number
  }) =>
    apiFetch<{ ok: boolean; agent: string; config: unknown }>('/config/llm-routes', {
      method: 'PUT',
      body: JSON.stringify(req),
    }),

  // NPC CRUD：统一走上方 *SessionNpc 系列（已删除重复定义，NEW-C13-01）

  // 通用方法（供 OOC 指令和其他动态调用使用）
  patch: (path: string, body: unknown) =>
    apiFetch<unknown>(path, { method: 'PATCH', body: JSON.stringify(body) }),

  get: (path: string) => apiFetch<unknown>(path),

  post: (path: string, body?: unknown) =>
    apiFetch<unknown>(path, {
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),

  // ── 全局世界模板 ───────────────────────────────────────────────────────────
  listWorlds: (worldPlugin?: string) => {
    const q = worldPlugin ? `?world_plugin=${worldPlugin}` : ''
    return apiFetch<{ worlds: World[] }>(`/worlds${q}`)
  },
  createWorld: (req: { name: string; world_plugin?: string; description?: string }) =>
    apiFetch<{ world_id: string; name: string }>('/worlds', { method: 'POST', body: JSON.stringify(req) }),
  updateWorld: (wid: string, req: { name?: string; world_plugin?: string; description?: string }) =>
    apiFetch<{ ok: boolean }>(`/worlds/${wid}`, { method: 'PATCH', body: JSON.stringify(req) }),
  deleteWorld: (wid: string) =>
    apiFetch<{ ok: boolean }>(`/worlds/${wid}`, { method: 'DELETE' }),
  listGlobalWorldArchives: (wid: string) =>
    apiFetch<{ archives: WorldArchiveEntry[] }>(`/worlds/${wid}/archives`),
  createGlobalWorldArchive: (wid: string, req: { title: string; content?: string; archive_type?: string; trigger_keywords?: string }) =>
    apiFetch<{ archive_id: string; title: string }>(`/worlds/${wid}/archives`, { method: 'POST', body: JSON.stringify(req) }),
  updateGlobalWorldArchive: (wid: string, aid: string, req: { title?: string; content?: string; archive_type?: string; trigger_keywords?: string }) =>
    apiFetch<{ ok: boolean }>(`/worlds/${wid}/archives/${aid}`, { method: 'PATCH', body: JSON.stringify(req) }),
  deleteGlobalWorldArchive: (wid: string, aid: string) =>
    apiFetch<{ ok: boolean }>(`/worlds/${wid}/archives/${aid}`, { method: 'DELETE' }),
  confirmLore: (wid: string, entries: Array<{ title: string; content: string; archive_type: string }>) =>
    apiFetch<{ ok: boolean; written: number }>(`/worlds/${wid}/confirm-lore`, { method: 'POST', body: JSON.stringify({ entries }) }),

  // ── 全局人物模板 ───────────────────────────────────────────────────────────
  listCharacterTemplates: (worldPlugin?: string) => {
    const q = worldPlugin ? `?world_plugin=${worldPlugin}` : ''
    return apiFetch<{ characters: CharacterTemplate[] }>(`/characters${q}`)
  },
  getCharacterTemplate: (cid: string) =>
    apiFetch<CharacterTemplate & { data_json: Record<string, unknown> }>(`/characters/${cid}`),
  createCharacterTemplate: (req: { name: string; world_plugin?: string; data_json?: Record<string, unknown> }) =>
    apiFetch<{ character_id: string; name: string }>('/characters', { method: 'POST', body: JSON.stringify(req) }),
  updateCharacterTemplate: (cid: string, req: { name?: string; world_plugin?: string; data_json?: Record<string, unknown> }) =>
    apiFetch<{ ok: boolean }>(`/characters/${cid}`, { method: 'PATCH', body: JSON.stringify(req) }),
  deleteCharacterTemplate: (cid: string) =>
    apiFetch<{ ok: boolean }>(`/characters/${cid}`, { method: 'DELETE' }),
  importCharacterPng: async (file: File, worldPlugin?: string) => {
    const form = new FormData()
    form.append('file', file)
    const q = worldPlugin ? `?world_plugin=${worldPlugin}` : ''
    const res = await fetch(`${BASE}/characters/import-png${q}`, { method: 'POST', body: form })
    if (!res.ok) throw new Error(`导入失败 ${res.status}: ${await res.text()}`)
    return res.json() as Promise<{ character_id: string; name: string }>
  },
  exportCharacterPngUrl: (cid: string) => `${BASE}/characters/${cid}/export-png`,

  // ── 全局资产库 ─────────────────────────────────────────────────────────────
  listNpcTemplates: (worldPlugin?: string) => {
    const q = worldPlugin ? `?world_plugin=${worldPlugin}` : ''
    return apiFetch<{ npcs: NpcTemplate[] }>(`/assets/npcs${q}`)
  },
  createNpcTemplate: (req: { name: string; key?: string; world_plugin?: string; profile_json?: Record<string, unknown> }) =>
    apiFetch<{ npc_id: string; key: string; name: string }>('/assets/npcs', { method: 'POST', body: JSON.stringify(req) }),
  updateNpcTemplate: (nid: string, req: { name?: string; world_plugin?: string; profile_json?: Record<string, unknown> }) =>
    apiFetch<{ ok: boolean }>(`/assets/npcs/${nid}`, { method: 'PATCH', body: JSON.stringify(req) }),
  deleteNpcTemplate: (nid: string) =>
    apiFetch<{ ok: boolean }>(`/assets/npcs/${nid}`, { method: 'DELETE' }),
  importNpcToSession: (nid: string, sessionId: string) =>
    apiFetch<{ ok: boolean; npc_id: string }>(`/assets/npcs/${nid}/import`, { method: 'POST', body: JSON.stringify({ session_id: sessionId }) }),

  listItemTemplates: (itemType?: string, worldPlugin?: string) => {
    const params = new URLSearchParams()
    if (itemType) params.set('item_type', itemType)
    if (worldPlugin) params.set('world_plugin', worldPlugin)
    const q = params.toString() ? `?${params}` : ''
    return apiFetch<{ items: ItemTemplate[] }>(`/assets/items${q}`)
  },
  createItemTemplate: (req: { name: string; item_type?: string; world_plugin?: string; data_json?: Record<string, unknown> }) =>
    apiFetch<{ item_id: string; name: string }>('/assets/items', { method: 'POST', body: JSON.stringify(req) }),
  updateItemTemplate: (iid: string, req: { name?: string; item_type?: string; world_plugin?: string; data_json?: Record<string, unknown> }) =>
    apiFetch<{ ok: boolean }>(`/assets/items/${iid}`, { method: 'PATCH', body: JSON.stringify(req) }),
  deleteItemTemplate: (iid: string) =>
    apiFetch<{ ok: boolean }>(`/assets/items/${iid}`, { method: 'DELETE' }),
  grantItemToSession: (iid: string, sessionId: string, quantity = 1) =>
    apiFetch<{ ok: boolean }>(`/assets/items/${iid}/grant`, { method: 'POST', body: JSON.stringify({ session_id: sessionId, quantity }) }),

  // ── 全局提示词模板 ─────────────────────────────────────────────────────────
  listPrompts: (agent?: string) => {
    const q = agent ? `?agent=${agent}` : ''
    return apiFetch<{ prompts: PromptTemplate[] }>(`/prompts${q}`)
  },
  createPrompt: (req: { agent: string; label: string; content?: string; enabled?: number; sort_order?: number }) =>
    apiFetch<{ prompt_id: string; label: string }>('/prompts', { method: 'POST', body: JSON.stringify(req) }),
  updatePrompt: (pid: string, req: { label?: string; content?: string; enabled?: number; sort_order?: number }) =>
    apiFetch<{ ok: boolean }>(`/prompts/${pid}`, { method: 'PATCH', body: JSON.stringify(req) }),
  deletePrompt: (pid: string) =>
    apiFetch<{ ok: boolean }>(`/prompts/${pid}`, { method: 'DELETE' }),
  resetPrompts: () =>
    apiFetch<{ ok: boolean; reset_count: number }>('/prompts/reset', { method: 'POST' }),

  // ── 爬虫站点规则管理 ────────────────────────────────────────────────────────
  listScraperRules: () =>
    apiFetch<{ rules: ScraperRule[] }>('/scraper-rules'),
  updateScraperRules: (rules: ScraperRule[]) =>
    apiFetch<{ ok: boolean; total: number }>('/scraper-rules', { method: 'PUT', body: JSON.stringify(rules) }),
  reloadScraperRules: () =>
    apiFetch<{ ok: boolean; total: number; enabled: number }>('/scraper-rules/reload', { method: 'POST' }),
}

// ── 新增类型 ─────────────────────────────────────────────────────────────────

export interface World {
  id: string
  name: string
  world_plugin: string
  description: string
  created_at: number | null
  updated_at: number
}

export interface WorldArchiveEntry {
  id: string
  world_id: string
  title: string
  content: string
  archive_type: string
  trigger_keywords?: string
  created_at: number | null
  updated_at: number
}

export interface CharacterTemplate {
  id: string
  name: string
  world_plugin: string
  schema_version: string
  data_json?: Record<string, unknown>
  created_at: number | null
  updated_at: number
}

export interface NpcTemplate {
  id: string
  name: string
  key: string
  world_plugin: string
  profile_json: Record<string, unknown>
  created_at: number | null
  updated_at: number
}

export interface ItemTemplate {
  id: string
  name: string
  item_type: string
  world_plugin: string
  data_json: Record<string, unknown>
  created_at: number | null
  updated_at: number
}

export interface PromptTemplate {
  id: string
  agent: string
  label: string
  content: string
  enabled: number
  sort_order: number
  created_at: number | null
  updated_at: number
}

export interface ScraperRule {
  domain: string
  alias: string
  engine: 'httpx' | 'playwright'
  content_selectors: string[]
  wait_ms: number
  max_chars: number
  enabled: boolean
  notes: string
}
