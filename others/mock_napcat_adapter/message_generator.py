"""QQ 消息生成器 - 生成模拟的 QQ 消息

支持的消息类型：
- message: 私聊/群聊消息
- notice: 通知事件（撤回、戳一戳、群管理等）
- meta_event: 元事件（生命周期、心跳）
"""

from __future__ import annotations

import enum
import random
import time
from typing import Any, Dict

try:
    from .config import MockConfig
except ImportError:
    from config import MockConfig


class MessageType(enum.Enum):
    """消息类型枚举"""

    PRIVATE_MESSAGE = "private_message"
    GROUP_MESSAGE = "group_message"
    FRIEND_RECALL = "friend_recall"
    GROUP_RECALL = "group_recall"
    POKE = "poke"
    GROUP_BAN = "group_ban"
    GROUP_INCREASE = "group_increase"
    GROUP_DECREASE = "group_decrease"
    META_EVENT_LIFECYCLE = "meta_event_lifecycle"
    META_EVENT_HEARTBEAT = "meta_event_heartbeat"


class MessageGenerator:
    """QQ 消息生成器

    AI agent 使用示例：
    >>> gen = MessageGenerator(config)
    >>> message = gen.generate_message()  # 生成随机消息
    >>> message = gen.generate_message(MessageType.GROUP_MESSAGE)  # 生成特定类型消息
    """

    def __init__(self, config: MockConfig):
        """初始化消息生成器

        Args:
            config: 配置对象
        """
        self.config = config
        self._message_count = 0

        # 消息类型池（用于随机生成）
        self._message_types = []

        if config.enable_message:
            self._message_types.extend(
                [MessageType.PRIVATE_MESSAGE, MessageType.GROUP_MESSAGE]
            )

        if config.enable_notice:
            self._message_types.extend(
                [
                    MessageType.FRIEND_RECALL,
                    MessageType.GROUP_RECALL,
                    MessageType.POKE,
                    MessageType.GROUP_BAN,
                    MessageType.GROUP_INCREASE,
                    MessageType.GROUP_DECREASE,
                ]
            )

        if config.enable_meta_event:
            self._message_types.extend(
                [MessageType.META_EVENT_LIFECYCLE, MessageType.META_EVENT_HEARTBEAT]
            )

    def generate_message(
        self, message_type: MessageType | None = None
    ) -> Dict[str, Any]:
        """生成一条消息

        Args:
            message_type: 消息类型，如果为 None 则随机选择

        Returns:
            消息字典（符合 Napcat 消息格式）
        """
        self._message_count += 1

        # 如果没有指定类型，则随机选择
        if message_type is None:
            if not self._message_types:
                return self._create_heartbeat()
            message_type = random.choice(self._message_types)

        # 根据类型生成消息
        if message_type == MessageType.PRIVATE_MESSAGE:
            return self._create_private_message()
        elif message_type == MessageType.GROUP_MESSAGE:
            return self._create_group_message()
        elif message_type == MessageType.FRIEND_RECALL:
            return self._create_friend_recall()
        elif message_type == MessageType.GROUP_RECALL:
            return self._create_group_recall()
        elif message_type == MessageType.POKE:
            return self._create_poke()
        elif message_type == MessageType.GROUP_BAN:
            return self._create_group_ban()
        elif message_type == MessageType.GROUP_INCREASE:
            return self._create_group_increase()
        elif message_type == MessageType.GROUP_DECREASE:
            return self._create_group_decrease()
        elif message_type == MessageType.META_EVENT_LIFECYCLE:
            return self._create_meta_event_lifecycle()
        elif message_type == MessageType.META_EVENT_HEARTBEAT:
            return self._create_heartbeat()
        else:
            # 未知类型，返回心跳
            return self._create_heartbeat()

    def _create_base_message(self, post_type: str) -> Dict[str, Any]:
        """创建基础消息结构

        Args:
            post_type: 消息类型（message/notice/meta_event）

        Returns:
            基础消息字典
        """
        return {
            "post_type": post_type,
            "time": int(time.time()),
        }

    def _create_private_message(self) -> Dict[str, Any]:
        """创建私聊消息"""
        message = self._create_base_message("message")
        message.update(
            {
                "message_type": "private",
                "sub_type": "friend",
                "message_id": str(int(time.time() * 1000) + random.randint(0, 999)),
                "user_id": self.config.user_id,
                "self_id": self.config.self_id,
                "message": self._generate_message_segments(),
                "sender": {
                    "user_id": self.config.user_id,
                    "nickname": f"User{self.config.user_id}",
                    "card": "",
                    "sex": "unknown",
                    "age": 0,
                    "level": "1",
                    "role": "member",
                },
                "raw_message": self._generate_raw_message(),
                "font": 0,
                "message_format": "array",
            }
        )
        return message

    def _create_group_message(self) -> Dict[str, Any]:
        """创建群聊消息"""
        message = self._create_base_message("message")
        message.update(
            {
                "message_type": "group",
                "sub_type": "normal",
                "message_id": str(int(time.time() * 1000) + random.randint(0, 999)),
                "group_id": self.config.group_id,
                "user_id": self.config.user_id,
                "self_id": self.config.self_id,
                "message": self._generate_message_segments(),
                "sender": {
                    "user_id": self.config.user_id,
                    "nickname": f"User{self.config.user_id}",
                    "card": f"Card{self.config.user_id}",
                    "sex": "unknown",
                    "age": 0,
                    "level": "1",
                    "role": "member",
                    "title": "",
                },
                "raw_message": self._generate_raw_message(),
                "font": 0,
                "message_format": "array",
            }
        )
        return message

    def _create_friend_recall(self) -> Dict[str, Any]:
        """创建好友消息撤回通知"""
        message = self._create_base_message("notice")
        message.update(
            {
                "notice_type": "friend_recall",
                "user_id": self.config.user_id,
                "self_id": self.config.self_id,
                "message_id": str(int(time.time() * 1000) - 1000),
            }
        )
        return message

    def _create_group_recall(self) -> Dict[str, Any]:
        """创建群消息撤回通知"""
        message = self._create_base_message("notice")
        message.update(
            {
                "notice_type": "group_recall",
                "group_id": self.config.group_id,
                "user_id": self.config.user_id,
                "self_id": self.config.self_id,
                "message_id": str(int(time.time() * 1000) - 1000),
                "operator_id": self.config.user_id,
            }
        )
        return message

    def _create_poke(self) -> Dict[str, Any]:
        """创建戳一戳通知"""
        message = self._create_base_message("notice")
        message.update(
            {
                "notice_type": "notify",
                "sub_type": "poke",
                "group_id": self.config.group_id,
                "user_id": self.config.user_id,
                "self_id": self.config.self_id,
                "target_id": self.config.user_id,
                "sender_id": self.config.user_id,
            }
        )
        return message

    def _create_group_ban(self) -> Dict[str, Any]:
        """创建群禁言通知"""
        message = self._create_base_message("notice")
        message.update(
            {
                "notice_type": "group_ban",
                "sub_type": random.choice(["ban", "lift_ban"]),
                "group_id": self.config.group_id,
                "user_id": self.config.user_id,
                "self_id": self.config.self_id,
                "operator_id": self.config.user_id,
                "duration": random.randint(60, 3600),
            }
        )
        return message

    def _create_group_increase(self) -> Dict[str, Any]:
        """创建群成员增加通知"""
        message = self._create_base_message("notice")
        message.update(
            {
                "notice_type": "group_increase",
                "sub_type": random.choice(["approve", "invite"]),
                "group_id": self.config.group_id,
                "user_id": self.config.user_id,
                "self_id": self.config.self_id,
                "operator_id": self.config.user_id,
            }
        )
        return message

    def _create_group_decrease(self) -> Dict[str, Any]:
        """创建群成员减少通知"""
        message = self._create_base_message("notice")
        message.update(
            {
                "notice_type": "group_decrease",
                "sub_type": random.choice(["leave", "kick", "kick_me"]),
                "group_id": self.config.group_id,
                "user_id": self.config.user_id,
                "self_id": self.config.self_id,
                "operator_id": self.config.user_id,
            }
        )
        return message

    def _create_meta_event_lifecycle(self) -> Dict[str, Any]:
        """创建生命周期元事件"""
        message = self._create_base_message("meta_event")
        message.update(
            {
                "meta_event_type": "lifecycle",
                "sub_type": "connect",
                "self_id": self.config.self_id,
            }
        )
        return message

    def _create_heartbeat(self) -> Dict[str, Any]:
        """创建心跳元事件"""
        message = self._create_base_message("meta_event")
        message.update(
            {
                "meta_event_type": "heartbeat",
                "self_id": self.config.self_id,
                "status": {
                    "online": True,
                    "good": True,
                },
                "interval": 5000,
            }
        )
        return message

    def _generate_message_segments(self) -> list:
        """生成消息段列表

        Returns:
            消息段列表（符合 Napcat 格式）
        """
        # 简单的文本消息
        return [
            {
                "type": "text",
                "data": {"text": self._generate_raw_message()},
            }
        ]

    def _generate_raw_message(self) -> str:
        """生成原始消息文本

        Returns:
            消息文本
        """
        test_messages = [
            "Hello, this is a test message!",
            "测试消息：这是一条测试消息",
            "Mock adapter is working!",
            "Testing WebSocket connection",
            "这是一条中文测试消息",
            "Hello, bot!",
            "你好，机器人！",
            "Test message #{self._message_count}",
            f"消息序号: {self._message_count}",
            "Testing message handling",
            "这是一个用于测试的消息",
            "Mock adapter test message",
        ]

        return random.choice(test_messages)
