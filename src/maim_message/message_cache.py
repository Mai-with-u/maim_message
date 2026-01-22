"""
消息缓存管理器 - 用于缓存发送失败的消息，支持TTL和重连重发
"""

import time
import asyncio
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, field
from enum import Enum


class MessageStatus(Enum):
    PENDING = "pending"
    RETRYING = "retrying"
    ACKED = "acked"


@dataclass
class CachedMessage:
    """缓存的消息条目"""

    message_id: str
    message: Dict[str, Any]
    target_uuid: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    retry_count: int = 0
    last_retry_at: Optional[float] = None
    status: MessageStatus = MessageStatus.PENDING


class MessageCache:
    """
    消息缓存管理器

    功能：
    1. 缓存发送失败的消息
    2. 支持 TTL（生存时间）配置
    3. 支持重连后批量重发
    4. 支持 ACK 确认后从缓存移除
    """

    def __init__(
        self,
        enabled: bool = True,
        ttl: int = 300,
        max_size: int = 1000,
        cleanup_interval: float = 60.0,
        custom_logger: Optional[Any] = None,
    ):
        self.enabled = enabled
        self.ttl = ttl
        self.max_size = max_size
        self.cleanup_interval = cleanup_interval

        if custom_logger is not None:
            self.logger = custom_logger
        else:
            import logging

            self.logger = logging.getLogger(__name__)

        self._messages: Dict[str, CachedMessage] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if not self.enabled:
            self.logger.info("消息缓存未启用")
            return

        if self._running:
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self.logger.info(f"消息缓存已启动: TTL={self.ttl}s, 最大缓存数={self.max_size}")

    async def stop(self) -> None:
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self.logger.info(f"消息缓存已停止，当前缓存数={len(self._messages)}")

    def add(
        self,
        message_id: str,
        message: Dict[str, Any],
        target_uuid: Optional[str] = None,
    ) -> bool:
        """
        添加消息到缓存

        Args:
            message_id: 消息ID
            message: 消息内容
            target_uuid: 目标连接UUID（服务端使用）

        Returns:
            是否成功添加
        """
        if not self.enabled:
            return False

        if len(self._messages) >= self.max_size:
            self.logger.warning(f"消息缓存已满（{self.max_size}），移除最旧的消息")
            self._remove_oldest()

        cached = CachedMessage(
            message_id=message_id,
            message=message,
            target_uuid=target_uuid,
            status=MessageStatus.PENDING,
        )
        self._messages[message_id] = cached
        self.logger.debug(f"消息已缓存: {message_id}, 当前缓存数={len(self._messages)}")
        return True

    def get_pending_message_ids(self) -> List[str]:
        """获取所有待重发的消息ID"""
        return [
            msg_id
            for msg_id, cached in self._messages.items()
            if cached.status == MessageStatus.PENDING
        ]

    def mark_retrying(self, message_id: str) -> bool:
        """标记消息为重发中"""
        if message_id in self._messages:
            self._messages[message_id].status = MessageStatus.RETRYING
            self._messages[message_id].retry_count += 1
            self._messages[message_id].last_retry_at = time.time()
            self.logger.debug(f"消息标记为重发中: {message_id}")
            return True
        return False

    def mark_acked(self, message_id: str) -> bool:
        """
        标记消息已确认并从缓存中移除（收到ACK确认时调用）

        Args:
            message_id: 消息ID

        Returns:
            是否成功移除
        """
        if message_id in self._messages:
            del self._messages[message_id]
            self.logger.debug(
                f"消息已从缓存移除: {message_id}, 剩余缓存数={len(self._messages)}"
            )
            return True
        return False

    def remove(self, message_id: str) -> bool:
        """
        从缓存中移除消息（保持兼容性，内部调用mark_acked）

        Args:
            message_id: 消息ID

        Returns:
            是否成功移除
        """
        return self.mark_acked(message_id)

    def get_all(self) -> List[CachedMessage]:
        """获取所有缓存的消息"""
        return list(self._messages.values())

    def get_by_target(self, target_uuid: str) -> List[CachedMessage]:
        """
        获取指定目标的缓存消息（服务端重发时使用）

        Args:
            target_uuid: 目标连接UUID

        Returns:
            缓存消息列表
        """
        return [
            msg for msg in self._messages.values() if msg.target_uuid == target_uuid
        ]

    def clear(self) -> int:
        """清空所有缓存

        Returns:
            清理的消息数量
        """
        count = len(self._messages)
        self._messages.clear()
        self.logger.info(f"消息缓存已清空，清理了{count}条消息")
        return count

    def _remove_oldest(self) -> None:
        """移除最旧的消息"""
        if not self._messages:
            return

        oldest_id = min(
            self._messages.keys(), key=lambda k: self._messages[k].created_at
        )
        del self._messages[oldest_id]
        self.logger.debug(f"移除最旧消息: {oldest_id}")

    def _cleanup_expired(self) -> int:
        """清理过期消息

        Returns:
            清理的消息数量
        """
        now = time.time()
        expired_ids = [
            msg_id
            for msg_id, cached in self._messages.items()
            if now - cached.created_at > self.ttl
        ]

        for msg_id in expired_ids:
            del self._messages[msg_id]

        if expired_ids:
            self.logger.info(f"清理过期消息: {len(expired_ids)}条")

        return len(expired_ids)

    async def _cleanup_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"清理过期消息时出错: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            "enabled": self.enabled,
            "cached_messages": len(self._messages),
            "max_size": self.max_size,
            "ttl": self.ttl,
            "cleanup_interval": self.cleanup_interval,
        }
