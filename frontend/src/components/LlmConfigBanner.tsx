/**
 * LlmConfigBanner — 首页顶部配置健康横幅（Phase 3B）。
 * - LLM 无可用路由 → 橙色警告 + 「去配置」跳转 Settings
 * - 记忆系统降级（memory-health 非 ok）→ 黄色提示
 * 正常时不渲染任何内容。
 */
import { useEffect, useState } from 'react'
import { api } from '../lib/api'

export function LlmConfigBanner({ onGoSettings }: { onGoSettings?: () => void }) {
  const [llmMissing, setLlmMissing] = useState(false)
  const [memoryDegraded, setMemoryDegraded] = useState(false)

  useEffect(() => {
    api.getLlmRoutes()
      .then(r => {
        const routes = r?.routes || {}
        setLlmMissing(!routes || Object.keys(routes).length === 0)
      })
      .catch(() => setLlmMissing(true))

    api.getMemoryHealth()
      .then(r => {
        const mode = r?.memory?.mode as string | undefined
        const full = r?.memory?.is_full_mode === true || mode === 'full'
        setMemoryDegraded(!full)
      })
      .catch(() => setMemoryDegraded(true))
  }, [])

  if (!llmMissing && !memoryDegraded) return null

  return (
    <div className="space-y-1">
      {llmMissing && (
        <div className="flex items-center gap-2 bg-orange-950/60 border border-orange-700/60 rounded px-3 py-1.5 text-xs text-orange-200">
          <span>⚠</span>
          <span className="flex-1">尚未配置可用的 LLM 路由，叙事生成将无法工作。</span>
          {onGoSettings && (
            <button onClick={onGoSettings} className="underline hover:text-orange-100">去配置 →</button>
          )}
        </div>
      )}
      {memoryDegraded && (
        <div className="flex items-center gap-2 bg-amber-950/50 border border-amber-700/50 rounded px-3 py-1.5 text-xs text-amber-200">
          <span>ℹ</span>
          <span className="flex-1">记忆系统处于降级模式（向量库不可用，已回退 SQLite），长程记忆检索质量可能下降。</span>
        </div>
      )}
    </div>
  )
}
