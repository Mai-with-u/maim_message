"""Mock Napcat Adapter - 用于测试 maim_message 和 MaiMBot 连接的模拟器

这个模块提供了模拟 Napcat Adapter 行为的 WebSocket 服务器，
用于测试 maim_message 库和 MaiMBot 的连接机制。

主要功能：
- WebSocket 服务器（模拟 napcat adapter）
- QQ 消息生成器（message/notice/meta_event）
- 可配置的消息发送策略
- 支持 AI agent 程序化控制
"""

from .mock_server import MockNapcatServer
from .message_generator import MessageGenerator, MessageType
from .config import MockConfig

__all__ = [
    "MockNapcatServer",
    "MessageGenerator",
    "MessageType",
    "MockConfig",
]

__version__ = "0.1.0"
