/**
 * 世界事件 Part — 展示 World Agent 输出的世界演变
 */
import React from 'react'
import { MessagePart } from '../../stores/story'

const EVENT_ICON: Record<string, string> = {
  time:    '⏱',
  weather: '🌤',
  npc_move:'🚶',
  faction: '🏛',
}

interface WorldEvent {
  event_type: string
  description: string
  affects?: string
}

interface Props {
  part: MessagePart
}

export const WorldEventPart: React.FC<Props> = ({ part }) => {
  // 后端每条 world_event Part 是扁平 WorldEvent 对象（非 events 数组）
  const raw = part.content as unknown as WorldEvent & { events?: WorldEvent[] }
  // 兼容两种格式：扁平对象 或 {events:[...]} 包裹
  const events: WorldEvent[] = raw.events ?? (raw.event_type ? [raw] : [])
  if (events.length === 0) return null

  return (
    <div className="world-event-part my-1.5 space-y-0.5">
      {events.map((ev, i) => (
        <div key={i} className="flex items-start gap-1.5 text-xs text-zinc-500">
          <span>{EVENT_ICON[ev.event_type] ?? '🌐'}</span>
          <span>{ev.description}</span>
          {ev.affects && (
            <span className="text-zinc-600 ml-auto">[{ev.affects}]</span>
          )}
        </div>
      ))}
    </div>
  )
}
