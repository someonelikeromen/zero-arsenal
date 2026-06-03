"""
事件类型常量与 BusEvent 数据类。
从 event_bus.py 抽离，供外部模块（SSE adapter、测试等）独立导入，
避免引入整个 EventBus 的依赖。

参考设计文档 09-event-bus-sse.md §3。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime


class EventType:
    """所有 BusEvent 的 type 字符串常量。"""
    SESSION_STARTED      = "session.started"
    SESSION_ERROR        = "session.error"           # 会话级错误
    SESSION_IDLE         = "session.idle"            # Agent 管线完成，等待下一轮输入
    SESSION_DONE         = "session.done"
    SESSION_MODE_CHANGED = "session.mode_changed"
    AGENT_STARTED        = "agent.started"
    AGENT_ENDED          = "agent.ended"
    AGENT_ERROR          = "agent.error"             # 单 Agent 节点错误
    TURN_STARTED         = "turn.started"
    TURN_ENDED           = "turn.ended"
    PART_CREATED         = "part.created"
    PART_UPDATED         = "part.updated"            # 流式 delta
    PART_DONE            = "part.done"
    PART_ERROR           = "part.error"
    PERMISSION_ASK       = "permission.ask"
    PERMISSION_GRANTED   = "permission.granted"
    PERMISSION_DENIED    = "permission.denied"
    CHAPTER_CONSOLIDATED = "chapter.consolidated"
    TURN_COMPLETE        = "turn.complete"           # 每回合 anchor 写入后（02-arch §8）
    REPLAY_START         = "replay.start"            # Last-Event-ID 补偿开始
    REPLAY_END           = "replay.end"              # 补偿结束
    HEARTBEAT            = "heartbeat"
    SERVER_CONNECTED     = "server.connected"        # SSE 连接建立确认（首事件，含 id: 行）


@dataclass
class BusEvent:
    """单个总线事件（不可变载体）。"""
    type: str
    session_id: str
    data: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())

    def to_sse(self) -> str:
        """
        序列化为标准 SSE 格式字符串。
        含 id: 行（供前端 Last-Event-ID 断点续传）、data: JSON 行、空行结束符。
        """
        payload = json.dumps(
            {
                "type": self.type,
                "session_id": self.session_id,
                "timestamp": self.timestamp,
                "data": self.data,
            },
            ensure_ascii=False,
        )
        return f"id: {self.id}\ndata: {payload}\n\n"

    def to_dict(self) -> dict:
        return asdict(self)
