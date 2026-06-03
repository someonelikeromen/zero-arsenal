/**
 * InputBar — 底部输入区（文本框 + 发送按钮 + 行动选项条 + Agent 进度指示器）
 * 参考 12-frontend-architecture.md §3
 */
import React, { useRef, useState, useMemo } from 'react'

const AGENT_DISPLAY: Record<string, string> = {
  rules:      '规则校验',
  dm_gate:    'DM 阈门',
  dice:       '骰子判定',
  npc:        'NPC 行为',
  world:      '世界演变',
  narrator:   '叙事生成',
  style:      '文风润色',
  var:        '变量结算',
  chronicler: '章节固化',
  options:    '行动选项',
  gacha_agent:'抽卡发货',
}

interface ActionOption {
  label: string
  text: string
}

/** Lorebook 条目（用于 # 触发的下拉搜索） */
export interface LorebookEntry {
  id: string
  title: string
  content?: string
}

/** 系统状态机：决定 InputBar 的可用性与占位提示文案 */
export type SystemState = 'no_llm' | 'no_world' | 'no_character' | 'ready'

const STATE_PLACEHOLDER: Record<SystemState, string> = {
  no_llm: '⚠ 尚未配置 LLM，请先到「设置 → API Keys」配置模型',
  no_world: '⚠ 当前会话未关联世界设定',
  no_character: '⚠ 当前会话未关联角色',
  ready: '输入行动、对话或指令 (Enter 发送，Shift+Enter 换行)',
}

interface Props {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  /** 停止当前生成（取消管线） */
  onStop?: () => void
  sending?: boolean
  activeAgent?: string | null
  actionOptions?: ActionOption[]
  onSelectOption?: (text: string) => void
  /** 直接触发选项（点一次即发送，无需二次确认） */
  directSelectOption?: boolean
  placeholder?: string
  /** 系统状态：未就绪时禁用输入并显示对应提示 */
  systemState?: SystemState
  /** Lorebook 条目：输入 # 时弹出下拉搜索 */
  lorebook?: LorebookEntry[]
}

export const InputBar: React.FC<Props> = ({
  value,
  onChange,
  onSend,
  onStop,
  sending = false,
  activeAgent = null,
  actionOptions = [],
  onSelectOption,
  directSelectOption = true,
  placeholder,
  systemState = 'ready',
  lorebook = [],
}) => {
  const sendBtnRef = useRef<HTMLButtonElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const notReady = systemState !== 'ready'
  const effectivePlaceholder = placeholder ?? STATE_PLACEHOLDER[systemState]

  // ── Lorebook # 触发下拉 ──────────────────────────────────────────────
  const [hashQuery, setHashQuery] = useState<string | null>(null)
  const [hashIndex, setHashIndex] = useState(0)

  const hashMatches = useMemo(() => {
    if (hashQuery === null || lorebook.length === 0) return []
    const q = hashQuery.toLowerCase()
    return lorebook
      .filter(e => !q || e.title.toLowerCase().includes(q))
      .slice(0, 8)
  }, [hashQuery, lorebook])

  /** 解析光标前的 #token；返回当前查询词或 null */
  const detectHash = (text: string, caret: number): string | null => {
    const before = text.slice(0, caret)
    const m = before.match(/#([^\s#]*)$/)
    return m ? m[1] : null
  }

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = e.target.value
    onChange(text)
    if (lorebook.length > 0) {
      const q = detectHash(text, e.target.selectionStart ?? text.length)
      setHashQuery(q)
      setHashIndex(0)
    }
  }

  const insertLorebook = (entry: LorebookEntry) => {
    const ta = textareaRef.current
    const caret = ta?.selectionStart ?? value.length
    const before = value.slice(0, caret)
    const after = value.slice(caret)
    const replaced = before.replace(/#([^\s#]*)$/, `「${entry.title}」`)
    onChange(replaced + after)
    setHashQuery(null)
    setTimeout(() => ta?.focus(), 0)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Lorebook 下拉激活时，方向键/回车/Esc 由下拉接管
    if (hashQuery !== null && hashMatches.length > 0) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setHashIndex(i => (i + 1) % hashMatches.length); return }
      if (e.key === 'ArrowUp')   { e.preventDefault(); setHashIndex(i => (i - 1 + hashMatches.length) % hashMatches.length); return }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); insertLorebook(hashMatches[hashIndex]); return }
      if (e.key === 'Escape')    { e.preventDefault(); setHashQuery(null); return }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend()
    }
  }

  const handleOptionClick = (opt: ActionOption) => {
    onSelectOption?.(opt.text)
    if (directSelectOption) {
      // 填入后延迟一帧发送（等 onChange 更新）
      setTimeout(() => sendBtnRef.current?.click(), 50)
    }
  }

  return (
    <div className="border-t border-zinc-800 flex-shrink-0">
      {/* 行动选项条 */}
      {!sending && actionOptions.length > 0 && (
        <div className="px-3 pt-2 pb-1 flex gap-1.5 flex-wrap border-b border-zinc-800/60">
          {actionOptions.map((opt) => (
            <button
              key={opt.label}
              onClick={() => handleOptionClick(opt)}
              className="flex-1 min-w-[80px] px-2 py-1.5 bg-zinc-800/80 border border-zinc-700
                         hover:border-indigo-500 hover:bg-zinc-700 rounded text-xs text-zinc-300
                         transition-colors text-left flex items-start gap-1.5"
              title={opt.text}
            >
              <span className="text-indigo-400 font-bold shrink-0">{opt.label}</span>
              <span className="line-clamp-2 leading-relaxed">{opt.text}</span>
            </button>
          ))}
        </div>
      )}

      <div className="p-3">
        {/* Agent 进度 */}
        {sending && (
          <div className="flex items-center gap-2 mb-2 px-1">
            <div className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse flex-shrink-0" />
            <span className="text-[10px] text-indigo-400 font-mono">
              {activeAgent
                ? `${AGENT_DISPLAY[activeAgent] ?? activeAgent} 运行中...`
                : 'Agent 管线处理中...'}
            </span>
          </div>
        )}

        <div className="flex gap-2 relative">
          {/* Lorebook # 下拉 */}
          {hashQuery !== null && hashMatches.length > 0 && (
            <div className="absolute bottom-full left-0 mb-1 w-72 max-h-56 overflow-y-auto bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-20">
              <div className="px-2.5 py-1 text-[10px] text-zinc-600 border-b border-zinc-800">
                🔑 知识库条目（↑↓ 选择，Enter/Tab 插入）
              </div>
              {hashMatches.map((entry, i) => (
                <button
                  key={entry.id}
                  onMouseDown={(e) => { e.preventDefault(); insertLorebook(entry) }}
                  className={`w-full text-left px-2.5 py-1.5 text-xs transition-colors ${
                    i === hashIndex ? 'bg-indigo-600/30 text-zinc-100' : 'text-zinc-400 hover:bg-zinc-800'
                  }`}
                >
                  <div className="font-medium truncate">{entry.title}</div>
                  {entry.content && <div className="text-[10px] text-zinc-600 truncate">{entry.content}</div>}
                </button>
              ))}
            </div>
          )}
          <textarea
            ref={textareaRef}
            className="flex-1 bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm
                       resize-none focus:outline-none focus:border-indigo-500 placeholder-zinc-600
                       disabled:opacity-60"
            rows={2}
            placeholder={effectivePlaceholder}
            value={value}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            disabled={sending || notReady}
          />
          {sending ? (
            <button
              onClick={() => onStop?.()}
              className="px-4 py-2 bg-red-700 hover:bg-red-600 text-white text-sm rounded
                         transition-colors flex-shrink-0 self-end flex items-center gap-1.5"
              title="停止生成"
            >
              <span className="w-2.5 h-2.5 bg-white rounded-sm" /> 停止
            </button>
          ) : (
            <button
              ref={sendBtnRef}
              id="__send_btn"
              onClick={onSend}
              disabled={notReady || !value.trim()}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50
                         disabled:cursor-not-allowed text-white text-sm rounded
                         transition-colors flex-shrink-0 self-end"
            >
              发送
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
