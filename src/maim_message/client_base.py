"""WebSocket 客户端基类 - 提供通用的客户端功能"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, Set

from .client_socketio_driver import ClientNetworkDriver, EventType, NetworkEvent
from .ws_config import ClientConfig


class WebSocketClientBase(ABC):
    """WebSocket 客户端基类 - 提供通用的客户端功能

    所有客户端都应该继承这个基类，实现特定的连接和发送逻辑。
    """

    def __init__(self, default_config: Optional[ClientConfig] = None):
        self.default_config = default_config

        custom_logger = default_config.get_logger() if default_config else None
        if not hasattr(self, "logger"):
            self.logger = (
                custom_logger if custom_logger else logging.getLogger(__name__)
            )

        self.network_driver = ClientNetworkDriver(custom_logger=custom_logger)

        self.event_queue: asyncio.Queue = asyncio.Queue()
        self.running = False
        self.dispatcher_task: Optional[asyncio.Task] = None

        self._connected_count = 0

        self.custom_handlers: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        if default_config:
            self.custom_handlers = default_config.custom_handlers.copy()

        self.stats = {
            "connect_attempts": 0,
            "successful_connects": 0,
            "failed_connects": 0,
            "messages_received": 0,
            "messages_sent": 0,
            "custom_messages_processed": 0,
            "reconnect_attempts": 0,
            "active_handler_tasks": 0,
        }

        self.active_handler_tasks: Set[asyncio.Task] = set()
        self.task_counter = 0

    def register_custom_handler(
        self, message_type: str, handler: Callable[[Dict[str, Any]], None]
    ) -> None:
        """注册自定义消息处理器"""
        if not message_type.startswith("custom_"):
            message_type = f"custom_{message_type}"
        self.custom_handlers[message_type] = handler
        self.logger.info(f"注册自定义处理器: {message_type}")

    def unregister_custom_handler(self, message_type: str) -> None:
        """注销自定义消息处理器"""
        if not message_type.startswith("custom_"):
            message_type = f"custom_{message_type}"
        self.custom_handlers.pop(message_type, None)
        self.logger.info(f"注销自定义处理器: {message_type}")

    async def _cleanup_completed_tasks(self) -> None:
        """清理已完成的handler任务"""
        completed_tasks = {task for task in self.active_handler_tasks if task.done()}
        self.active_handler_tasks -= completed_tasks
        self.stats["active_handler_tasks"] = len(self.active_handler_tasks)

        # 获取任务结果并记录异常
        for task in completed_tasks:
            try:
                await task
            except Exception as e:
                self.logger.error(f"Handler task异常: {e}")

    async def _create_handler_task(self, coro, description: str = "handler") -> None:
        """创建并管理handler任务"""
        self.task_counter += 1
        task_id = self.task_counter

        # 创建任务包装器，用于异常处理和日志
        async def task_wrapper():
            try:
                await coro
                self.logger.debug(
                    f"✅ Client handler task {task_id} ({description}) 完成"
                )
            except Exception as e:
                self.logger.error(
                    f"❌ Client handler task {task_id} ({description}) 异常: {e}"
                )
                import traceback

                self.logger.error(f"   Traceback: {traceback.format_exc()}")
            finally:
                # 任务完成后自动清理
                if task in self.active_handler_tasks:
                    self.active_handler_tasks.remove(task)
                self.stats["active_handler_tasks"] = len(self.active_handler_tasks)

        task = asyncio.create_task(task_wrapper())
        self.active_handler_tasks.add(task)
        self.stats["active_handler_tasks"] = len(self.active_handler_tasks)

        self.logger.debug(
            f"🚀 Client handler task {task_id} ({description}) 已创建，当前活跃任务数: {len(self.active_handler_tasks)}"
        )

    async def _handle_message_event(self, event: NetworkEvent) -> None:
        """处理消息事件 - 子类可以重写此方法"""
        try:
            payload = event.payload
            if payload is None:
                self.logger.warning("收到空消息事件")
                return

            self.stats["messages_received"] += 1

            # 处理标准消息
            if payload.get("type") == "sys_std":
                if self.default_config and self.default_config.on_message:
                    try:
                        # 子类可以重写这个方法来处理标准消息
                        await self._handle_standard_message(payload)
                    except Exception as e:
                        self.logger.error(f"处理标准消息时出错: {e}")
            # 处理自定义消息
            elif payload.get("type", "").startswith("custom_"):
                message_type = payload.get("type")
                message_data = payload.get("payload", {})
                self.stats["custom_messages_processed"] += 1

                if message_type in self.custom_handlers:
                    try:
                        await self._create_handler_task(
                            self.custom_handlers[message_type](message_data),
                            f"客户端自定义消息处理器-{message_type}",
                        )
                    except Exception as e:
                        self.logger.error(
                            f"创建自定义消息处理器任务错误 {message_type}: {e}"
                        )
                else:
                    self.logger.warning(f"未找到自定义消息处理器: {message_type}")
        except Exception as e:
            self.logger.error(f"处理消息事件时出错: {e}")

    async def _handle_standard_message(self, payload: Optional[Dict[str, Any]]) -> None:
        """处理标准消息 - 子类可以重写此方法"""
        if payload is None:
            return
        if self.default_config and self.default_config.on_message:
            message_data = payload.get("payload", {})
            if message_data:
                from .message import APIMessageBase

                message = APIMessageBase.from_dict(message_data)
                await self._create_handler_task(
                    self.default_config.on_message(message, payload.get("meta") or {}),
                    "客户端标准消息处理器",
                )

    async def _event_dispatcher(self) -> None:
        """事件分发器"""
        self.logger.info(f"{self.__class__.__name__} event dispatcher started")
        try:
            while self.running:
                try:
                    event = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)

                    # 子类处理连接事件
                    if event.event_type == EventType.CONNECT:
                        await self._handle_connect_event(event)
                    elif event.event_type == EventType.DISCONNECT:
                        await self._handle_disconnect_event(event)
                    elif event.event_type == EventType.MESSAGE:
                        await self._handle_message_event(event)

                except asyncio.TimeoutError:
                    # 清理已完成的任务并继续循环
                    await self._cleanup_completed_tasks()
                    continue
                except Exception as e:
                    self.logger.error(f"Dispatcher error: {e}")

        except Exception as e:
            self.logger.error(f"Event dispatcher crashed: {e}")

        self.logger.info(f"{self.__class__.__name__} event dispatcher stopped")

    @abstractmethod
    async def _handle_connect_event(self, event: NetworkEvent) -> None:
        """处理连接事件 - 子类必须实现"""
        pass

    @abstractmethod
    async def _handle_disconnect_event(self, event: NetworkEvent) -> None:
        """处理断连事件 - 子类必须实现"""
        pass

    async def start(self) -> None:
        """启动客户端"""
        if self.running:
            self.logger.warning(f"{self.__class__.__name__} is already running")
            return

        self.running = True
        self.network_driver.set_event_queue(self.event_queue)

        if self.default_config and self.default_config.enable_message_cache:
            from .message_cache import MessageCache

            message_cache = MessageCache(
                enabled=self.default_config.enable_message_cache,
                ttl=self.default_config.message_cache_ttl,
                max_size=self.default_config.message_cache_max_size,
                cleanup_interval=self.default_config.message_cache_cleanup_interval,
                custom_logger=self.default_config.get_logger(),
            )
            await message_cache.start()
            self.network_driver.set_message_cache(message_cache)
            self.logger.info(
                f"Message cache initialized: TTL={self.default_config.message_cache_ttl}s, max_size={self.default_config.message_cache_max_size}"
            )

        # 启动网络驱动器
        await self.network_driver.start()

        # 启动事件分发器
        self.dispatcher_task = asyncio.create_task(self._event_dispatcher())
        self.logger.info(f"{self.__class__.__name__} started")

    async def stop(self) -> None:
        """停止客户端 - 完全清理所有协程"""
        if not self.running:
            return

        self.logger.info(f"Stopping {self.__class__.__name__}...")

        # 1. 首先停止运行状态
        self.running = False

        # 2. 取消事件分发器协程
        if self.dispatcher_task and not self.dispatcher_task.done():
            self.dispatcher_task.cancel()
            try:
                await asyncio.wait_for(self.dispatcher_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self.dispatcher_task = None

        # 3. 停止网络驱动器（这会清理所有连接协程）
        await self.network_driver.stop()

        # 4. 取消并等待所有handler任务完成
        if self.active_handler_tasks:
            self.logger.info(
                f"正在清理 {len(self.active_handler_tasks)} 个客户端handler任务..."
            )
            for task in self.active_handler_tasks:
                if not task.done():
                    task.cancel()

            # 等待所有任务完成或超时
            if self.active_handler_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(
                            *self.active_handler_tasks, return_exceptions=True
                        ),
                        timeout=3.0,
                    )
                except asyncio.TimeoutError:
                    self.logger.warning("部分客户端handler任务清理超时")

            self.active_handler_tasks.clear()
            self.stats["active_handler_tasks"] = 0

        # 5. 清空事件队列
        while not self.event_queue.empty():
            try:
                self.event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # 5. 重置统计信息
        self.stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "connection_errors": 0,
            "reconnections": 0,
            "custom_messages_processed": 0,
        }

        self.logger.info(f"{self.__class__.__name__} stopped completely")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        network_stats = self.network_driver.get_stats()
        return {
            **self.stats,
            "network": network_stats,
        }

    def is_running(self) -> bool:
        """检查客户端是否在运行"""
        return self.running

    def get_coroutine_status(self) -> Dict[str, Any]:
        """获取协程状态信息"""
        status = {
            "client_running": self.running,
            "dispatcher_task": None,
            "network_driver_running": False,
            "event_queue_size": 0,
        }

        # 检查事件分发器状态
        if self.dispatcher_task:
            status["dispatcher_task"] = {
                "exists": True,
                "done": self.dispatcher_task.done(),
                "cancelled": self.dispatcher_task.cancelled()
                if hasattr(self.dispatcher_task, "cancelled")
                else False,
            }

        # 检查网络驱动器状态
        status["network_driver_running"] = (
            self.network_driver.running
            if hasattr(self.network_driver, "running")
            else False
        )

        # 检查事件队列大小
        try:
            status["event_queue_size"] = self.event_queue.qsize()
        except AttributeError:
            pass

        return status
