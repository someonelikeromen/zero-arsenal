/**
 * WritingStylePanel — 会话文风选择面板
 * 四层模型（骨架/节奏/心理/温度）+ 配件 + NSFW 分类多选 chip，带 tooltip 说明。
 * 选择持久化到 PUT /sessions/{id}/writing-styles。
 */
import React, { useEffect, useState, useCallback } from 'react'
import { api } from '../../lib/api'
import { notify } from '../../stores/ui'

interface Props {
  sessionId: string
}

interface Style {
  name: string
  description?: string
}

// 文风名称 → 四层模型分类（参照 03-writing-style 规则）
const LAYER_OF: (name: string) => string = (name) => {
  const skeleton = ['网文', '小此说故事-零度写作', '紙芝居', '漫改', '闲谈散文-小此', '闲谈散文-Eula', '江南式', '古风-视觉小说', '舞台剧2.0', '广播剧-纯对话', 'ASMR']
  const rhythm = ['小此爽写-中文', '小此爽写-日语', '节奏大师', '异世界战斗-Elainades', '日日日式-电波喜剧']
  const psyche = ['伏见司式', '入间人间式', '意识流-第一人称2.0', '意识流-第三人称', '王小波式']
  const temperature = ['鲁迅式']
  if (name.startsWith('nsfw') || name === '男性视觉' || name === '哥杀专用') return 'nsfw'
  if (name.startsWith('配件')) return 'accessory'
  if (skeleton.includes(name)) return 'skeleton'
  if (rhythm.includes(name)) return 'rhythm'
  if (psyche.includes(name)) return 'psyche'
  if (temperature.includes(name) || name === '江南式') return 'temperature'
  return 'other'
}

const LAYER_META: { id: string; label: string; hint: string }[] = [
  { id: 'skeleton', label: '骨架层', hint: '叙事者是谁 / 如何讲（必选一个）' },
  { id: 'rhythm', label: '节奏层', hint: '信息密度 / 速度控制（慢↔快）' },
  { id: 'psyche', label: '心理层', hint: '某角色内心如何呈现' },
  { id: 'temperature', label: '温度层', hint: '叙事者对情感的距离（冷↔热）' },
  { id: 'accessory', label: '配件', hint: '概念锚定 / 禁词表（叠在一切之上）' },
  { id: 'nsfw', label: 'NSFW', hint: '成人向骨架与配件' },
  { id: 'other', label: '其他', hint: '未分类文风' },
]

export const WritingStylePanel: React.FC<Props> = ({ sessionId }) => {
  const [styles, setStyles] = useState<Style[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setLoading(true)
    Promise.all([api.getWritingStyles(), api.getSessionWritingStyles(sessionId)])
      .then(([all, sess]) => {
        setStyles(all.styles ?? [])
        setSelected(sess.writing_styles ?? [])
      })
      .catch(e => notify.error(`加载文风失败：${(e as Error).message}`))
      .finally(() => setLoading(false))
  }, [sessionId])

  const toggle = useCallback((name: string) => {
    setSelected(prev => prev.includes(name) ? prev.filter(s => s !== name) : [...prev, name])
    setDirty(true)
  }, [])

  const save = useCallback(async () => {
    setSaving(true)
    try {
      await api.setSessionWritingStyles(sessionId, selected)
      notify.success('文风配置已保存')
      setDirty(false)
    } catch (e) {
      notify.error(`保存失败：${(e as Error).message}`)
    } finally {
      setSaving(false)
    }
  }, [sessionId, selected])

  if (loading) return <div className="text-xs text-zinc-600 px-3 py-3">加载中...</div>

  const byLayer = (layerId: string) => styles.filter(s => LAYER_OF(s.name) === layerId)

  return (
    <div className="flex flex-col text-xs bg-zinc-900 rounded-lg border border-zinc-800">
      <div className="px-3 py-2 border-b border-zinc-800 flex items-center justify-between">
        <span className="text-zinc-400 font-semibold uppercase tracking-wider">✍ 文风</span>
        <button onClick={save} disabled={saving || !dirty}
          className="text-[10px] px-2 py-0.5 rounded bg-indigo-700 hover:bg-indigo-600 text-white disabled:opacity-40">
          {saving ? '保存中...' : dirty ? '保存' : '已保存'}
        </button>
      </div>

      <div className="px-2 py-2 space-y-2 max-h-80 overflow-y-auto">
        {LAYER_META.map(layer => {
          const items = byLayer(layer.id)
          if (items.length === 0) return null
          return (
            <div key={layer.id}>
              <div className="text-[10px] text-zinc-500 mb-1" title={layer.hint}>
                {layer.label} <span className="text-zinc-700">· {layer.hint}</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {items.map(s => (
                  <button
                    key={s.name}
                    onClick={() => toggle(s.name)}
                    title={s.description || s.name}
                    className={`text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                      selected.includes(s.name)
                        ? 'bg-indigo-700 border-indigo-500 text-white'
                        : 'bg-zinc-800 border-zinc-700 text-zinc-400 hover:text-zinc-200'
                    }`}
                  >
                    {s.name}
                  </button>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      {selected.length > 0 && (
        <div className="px-3 py-1.5 border-t border-zinc-800 text-[10px] text-zinc-500">
          已选 {selected.length} 项：{selected.join(' + ')}
        </div>
      )}
    </div>
  )
}

export default WritingStylePanel
