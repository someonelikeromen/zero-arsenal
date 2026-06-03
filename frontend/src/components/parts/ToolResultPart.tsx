/**
 * ToolResultPart — 工具调用结果展示组件。
 *
 * 设计文档要求的独立组件（02-system-architecture.md §P5）。
 * 实现为 ToolCallPart 的语义别名：tool_result 类型的 Part 与 tool_call 共用渲染器，
 * 但 ToolResultPart 重点展示"结果"而非"调用参数"。
 */
import React from 'react'
import { MessagePart } from '../../stores/story'
import { ToolCallPart } from './ToolCallPart'

interface Props {
  part: MessagePart
}

export const ToolResultPart: React.FC<Props> = ({ part }) => {
  // 将 tool_result 类型的 part 代理给 ToolCallPart 渲染
  // ToolCallPart 内部已处理 tool_result 类型的差异化展示
  return <ToolCallPart part={part} />
}
