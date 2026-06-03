/**
 * TextPart — 纯文本叙事段落展示组件。
 *
 * 设计文档要求的独立组件（02-system-architecture.md §P5）。
 * 实现为 NarrativePart 的语义别名：text 类型的 Part 与 narrative 共用渲染器。
 * TextPart 专指无流式效果的静态文本块（如摘要、注记）。
 */
import React from 'react'
import { MessagePart } from '../../stores/story'
import { NarrativePart } from './NarrativePart'

interface Props {
  part: MessagePart
}

export const TextPart: React.FC<Props> = ({ part }) => {
  return <NarrativePart part={part} />
}
