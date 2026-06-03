/**
 * InventoryPanel — 角色物品栏面板
 * 设计文档 12-frontend-architecture.md §4.7
 * 展示角色的 inventory 数组，支持按稀有度过滤
 */
import React, { useMemo, useState } from 'react'

interface InventoryItem {
  id: string
  key: string
  name: string
  count: number
  quality?: string
  description?: string
  metadata?: Record<string, unknown>
}

interface InventoryPanelProps {
  items: InventoryItem[]
  isLoading?: boolean
}

const QUALITY_COLORS: Record<string, string> = {
  common:    'text-zinc-400 border-zinc-700',
  uncommon:  'text-green-400 border-green-800',
  rare:      'text-blue-400 border-blue-800',
  epic:      'text-purple-400 border-purple-800',
  legendary: 'text-yellow-400 border-yellow-700',
}

const QUALITY_LABELS: Record<string, string> = {
  common: '普通',
  uncommon: '罕见',
  rare: '稀有',
  epic: '史诗',
  legendary: '传说',
}

export const InventoryPanel: React.FC<InventoryPanelProps> = ({ items, isLoading }) => {
  const [expanded, setExpanded] = useState(true)
  const [filterQuality, setFilterQuality] = useState<string>('all')
  const [expandedItem, setExpandedItem] = useState<string | null>(null)

  const qualities = useMemo(() => {
    const set = new Set(items.map(i => i.quality ?? 'common'))
    return ['all', ...Array.from(set)]
  }, [items])

  const filtered = filterQuality === 'all'
    ? items
    : items.filter(i => (i.quality ?? 'common') === filterQuality)

  const totalCount = items.reduce((sum, i) => sum + i.count, 0)

  return (
    <div className="inventory-panel flex flex-col bg-zinc-900 rounded-lg border border-zinc-800">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between px-3 py-2 text-xs font-semibold text-zinc-400 hover:text-zinc-200"
      >
        <span>🎒 物品栏 ({totalCount}件)</span>
        <span>{expanded ? '▾' : '▸'}</span>
      </button>

      {expanded && (
        <div className="px-2 pb-2 flex flex-col gap-1">
          {isLoading && (
            <div className="text-xs text-zinc-600 px-1 text-center py-2">加载中...</div>
          )}

          {/* 稀有度过滤 */}
          {qualities.length > 2 && (
            <div className="flex gap-1 flex-wrap">
              {qualities.map(q => (
                <button
                  key={q}
                  onClick={() => setFilterQuality(q)}
                  className={`text-[10px] px-1.5 py-0.5 rounded border ${
                    filterQuality === q
                      ? 'bg-zinc-700 border-zinc-500 text-zinc-200'
                      : `${QUALITY_COLORS[q] ?? 'text-zinc-500 border-zinc-700'} hover:opacity-80`
                  }`}
                >
                  {q === 'all' ? '全部' : (QUALITY_LABELS[q] ?? q)}
                </button>
              ))}
            </div>
          )}

          {/* 物品列表 */}
          <div className="flex flex-col gap-1 max-h-56 overflow-y-auto">
            {filtered.length === 0 && !isLoading && (
              <div className="text-xs text-zinc-700 px-1 py-3 text-center">背包为空</div>
            )}
            {filtered.map(item => {
              const qColor = QUALITY_COLORS[item.quality ?? 'common'] ?? 'text-zinc-400 border-zinc-700'
              const isExp = expandedItem === item.id
              return (
                <div
                  key={item.id}
                  className={`rounded border px-2 py-1.5 cursor-pointer ${qColor} bg-zinc-800`}
                  onClick={() => setExpandedItem(isExp ? null : item.id)}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium truncate">{item.name}</span>
                    {item.count > 1 && (
                      <span className="ml-auto text-[10px] text-zinc-500 shrink-0">×{item.count}</span>
                    )}
                    {item.quality && item.quality !== 'common' && (
                      <span className="text-[9px] shrink-0 opacity-70">
                        {QUALITY_LABELS[item.quality] ?? item.quality}
                      </span>
                    )}
                  </div>
                  {isExp && item.description && (
                    <p className="text-[10px] text-zinc-500 mt-1 leading-relaxed">
                      {item.description}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export default InventoryPanel
