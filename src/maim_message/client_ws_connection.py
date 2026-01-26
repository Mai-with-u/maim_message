"""WebSocket客户端网络驱动器 - 纯网络I/O层，不处理业务逻辑"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set
from enum import Enum

import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

from .message_cache import MessageCache
from .log_queue import LoggerProxy, LogQueueProcessor, LogMessage, create_log_queue

logger = logging.getLogger(__name__)


class EventType(Enum):
    """事件类型"""

    CONNECT = "connect"
    DISCONNECT = "disconnect"
    MESSAGE = "message"


@dataclass
class ConnectionConfig:
    """连接配置"""

    url: str
    api_key: str
    platform: str
    connection_uuid: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    ping_interval: int = 20
    ping_timeout: int = 10
    close_timeout: int = 10
    max_reconnect_attempts: int = 5
    reconnect_delay: float = 2.0
    max_reconnect_delay: float = 10.0

    # SSL配置
    ssl_enabled: bool = False
    ssl_verify: bool = True
    ssl_ca_certs: Optional[str] = None
    ssl_certfile: Optional[str] = None
    ssl_keyfile: Optional[str] = None
    ssl_check_hostname: bool = True

    def __post_init__(self) -> None:
        if self.connection_uuid is None:
            self.connection_uuid = str(uuid.uuid4())
        if self.headers is None:
            self.headers = {}

    def get_headers(self) -> Dict[str, str]:
        """获取连接用的headers"""
        headers = self.headers.copy()
        headers.update(
            {
                "x-uuid": self.connection_uuid,
                "x-apikey": self.api_key,
                "x-platform": self.platform,
            }
        )
        return headers

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "url": self.url,
            "api_key": self.api_key,
            "platform": self.platform,
            "connection_uuid": self.connection_uuid,
            "headers": self.headers,
            "ping_interval": self.ping_interval,
            "ping_timeout": self.ping_timeout,
            "close_timeout": self.close_timeout,
            "max_reconnect_attempts": self.max_reconnect_attempts,
            "reconnect_delay": self.reconnect_delay,
            "max_reconnect_delay": self.max_reconnect_delay,
        }


@dataclass
class NetworkEvent:
    """网络事件"""

    event_type: EventType
    connection_uuid: str
    config: ConnectionConfig
    payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class ClientNetworkDriver:
    """客户端网络驱动器 - 纯I/O层，负责WebSocket连接管理"""

    MAX_CONCURRENT_CONNECTIONS = 100

    def __init__(self, custom_logger: Optional[Any] = None):
        # 连接管理
        self.connections: Dict[str, ConnectionConfig] = {}
        self.active_connections: Dict[str, websockets.WebSocketServerProtocol] = {}
        self.connection_states: Dict[str, str] = {}

        self._log_queue: Optional[queue.Queue[LogMessage]] = None
        self._log_processor: Optional[LogQueueProcessor] = None
        self._real_logger: Optional[Any] = None
        self._using_log_proxy = False

        if custom_logger is not None:
            self._real_logger = custom_logger
            self.logger = custom_logger
        else:
            self.logger = logger

        # 跨线程通信
        self.event_queue: Optional[asyncio.Queue] = None
        self.queue_loop: Optional[asyncio.AbstractEventLoop] = None
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.running = False

        # 连接任务管理
        self.connection_tasks: Dict[str, asyncio.Task] = {}

        # 统计信息
        self.stats = {
            "total_connections": 0,
            "current_connections": 0,
            "messages_received": 0,
            "messages_sent": 0,
            "bytes_received": 0,
            "bytes_sent": 0,
            "reconnect_attempts": 0,
        }

        # 优雅关闭支持
        self._shutdown_event = asyncio.Event()
        self._worker_loop_task: Optional[asyncio.Task] = None

        # 消息缓存支持
        self.message_cache: Optional[MessageCache] = None

    def _init_log_queue(self) -> None:
        if self._log_queue is not None:
            return

        self._log_queue = create_log_queue(maxsize=1000)

        if self._real_logger is not None:
            self._log_processor = LogQueueProcessor(
                log_queue=self._log_queue,
                real_logger=self._real_logger,
                batch_size=10,
                batch_timeout=0.1,
            )
            self.logger = LoggerProxy(
                log_queue=self._log_queue,
                logger_name="ClientNetworkDriver",
            )
            self._using_log_proxy = True

    async def add_connection(self, config: ConnectionConfig) -> bool:
        """添加新的连接配置"""
        connection_uuid = config.connection_uuid

        if connection_uuid in self.connections:
            existing = self.connections[connection_uuid]
            if (
                existing.url == config.url
                and existing.api_key == config.api_key
                and existing.platform == config.platform
            ):
                self.connection_states[connection_uuid] = "disconnected"
                logger.info(f"Reusing existing connection {connection_uuid}")
                return True
            else:
                logger.warning(
                    f"Connection {connection_uuid} already exists with different config. "
                    f"Existing: {existing.url}, New: {config.url}"
                )
                return False

        self.connections[connection_uuid] = config
        self.connection_states[connection_uuid] = "disconnected"
        logger.info(f"Added connection {connection_uuid} to {config.url}")
        return True

    async def remove_connection(self, connection_uuid: str) -> bool:
        """移除连接"""
        if connection_uuid not in self.connections:
            logger.warning(f"Connection {connection_uuid} not found")
            return False

        # 停止连接任务
        if connection_uuid in self.connection_tasks:
            self.connection_tasks[connection_uuid].cancel()
            try:
                await self.connection_tasks[connection_uuid]
            except asyncio.CancelledError:
                pass
            del self.connection_tasks[connection_uuid]

        # 断开WebSocket连接
        if connection_uuid in self.active_connections:
            websocket = self.active_connections[connection_uuid]
            try:
                await websocket.close()
            except Exception:
                pass
            del self.active_connections[connection_uuid]

        # 清理状态
        del self.connections[connection_uuid]
        del self.connection_states[connection_uuid]

        logger.info(f"Removed connection {connection_uuid}")
        return True

    async def connect(self, connection_uuid: str) -> bool:
        if connection_uuid not in self.connections:
            logger.error(f"Connection {connection_uuid} not found")
            return False

        if self.connection_states[connection_uuid] == "connected":
            logger.info(f"Connection {connection_uuid} already connected")
            return True

        if len(self.active_connections) >= self.MAX_CONCURRENT_CONNECTIONS:
            logger.error(
                f"连接数达到上限 {self.MAX_CONCURRENT_CONNECTIONS}，拒绝新连接 {connection_uuid}"
            )
            return False

        # 启动连接任务
        if connection_uuid not in self.connection_tasks:
            # 如果网络驱动器运行在独立线程中，需要将任务发送到那个线程
            if self.main_loop and self.main_loop != asyncio.get_running_loop():
                # 使用call_soon_threadsafe将任务发送到工作线程
                logger.info(f"📡 将连接任务发送到工作线程: {connection_uuid}")
                self.main_loop.call_soon_threadsafe(
                    self._create_connection_task, connection_uuid
                )
            else:
                # 在当前事件循环中创建任务
                self._create_connection_task(connection_uuid)

        return True

    def _create_connection_task(self, connection_uuid: str) -> None:
        task = asyncio.create_task(self._connection_loop(connection_uuid))
        self.connection_tasks[connection_uuid] = task

        def task_done_callback(fut):
            if fut.exception():
                logger.error(f"❌ 连接任务 {connection_uuid} 异常: {fut.exception()}")
                import traceback

                logger.error(f"连接任务错误详情: {traceback.format_exc()}")
            else:
                logger.info(f"✅ 连接任务 {connection_uuid} 正常结束")

            if connection_uuid in self.connection_tasks:
                del self.connection_tasks[connection_uuid]

        task.add_done_callback(task_done_callback)

    async def disconnect(self, connection_uuid: str) -> bool:
        """断开指定连接"""
        if connection_uuid not in self.connections:
            logger.warning(f"Connection {connection_uuid} not found")
            return False

        try:
            self.connection_states[connection_uuid] = "disconnecting"

            if connection_uuid in self.connection_tasks:
                task = self.connection_tasks[connection_uuid]
                if task and not task.done():
                    task.cancel()
                    logger.debug(f"Cancelled task for {connection_uuid}")
                del self.connection_tasks[connection_uuid]

            if connection_uuid in self.active_connections:
                websocket = self.active_connections[connection_uuid]
                try:
                    if hasattr(websocket, "close"):
                        await websocket.close()
                        logger.info(
                            f"Waiting for {connection_uuid} connection to close..."
                        )
                        await asyncio.sleep(0.5)  # 等待连接完全关闭和端口释放
                        logger.info(f"Connection {connection_uuid} fully closed")
                except Exception as e:
                    logger.debug(f"Error closing websocket {connection_uuid}: {e}")
                finally:
                    del self.active_connections[connection_uuid]
                    logger.info(
                        f"Removed connection {connection_uuid} from active connections"
                    )

            self.connection_states[connection_uuid] = "disconnected"
            return True

        except Exception as e:
            logger.warning(
                f"Error during disconnect {connection_uuid}: {type(e).__name__}: {str(e)}"
            )
            self.connection_states[connection_uuid] = "disconnected"
            return True

        except Exception as e:
            # 记录错误但继续清理流程
            logger.warning(
                f"Error during disconnect {connection_uuid}: {type(e).__name__}: {str(e)}"
            )
            # 确保状态清理
            try:
                if connection_uuid in self.active_connections:
                    del self.active_connections[connection_uuid]
                if connection_uuid in self.connection_tasks:
                    del self.connection_tasks[connection_uuid]
                self.connection_states[connection_uuid] = "disconnected"
            except Exception:
                pass
            return True

    async def _connection_loop(self, connection_uuid: str) -> None:
        """单个连接的管理循环"""
        logger.info(f"🔄 开始连接循环: {connection_uuid}")
        logger.info(
            f"📋 连接前置条件: running={self.running}, connection_exists={connection_uuid in self.connections}, shutdown_not_set={not self._shutdown_event.is_set()}"
        )
        config = self.connections[connection_uuid]
        reconnect_delay = config.reconnect_delay
        logger.info(
            f"📋 连接配置: url={config.url}, api_key={config.api_key}, platform={config.platform}"
        )
        reconnect_attempts = 0
        consecutive_failures = 0  # 连续失败计数

        while (
            self.running
            and connection_uuid in self.connections
            and not self._shutdown_event.is_set()
        ):
            if (
                config.max_reconnect_attempts > 0
                and reconnect_attempts >= config.max_reconnect_attempts
            ):
                logger.error(
                    f"连接 {connection_uuid} 已达到最大重连次数 {config.max_reconnect_attempts}，停止重连"
                )
                break
            try:
                # 尝试连接
                self.connection_states[connection_uuid] = "connecting"
                logger.info(f"Connecting {connection_uuid} to {config.url}")

                # 使用async with语法建立WebSocket连接并传递headers
                # 构建websockets连接参数
                ws_kwargs = {
                    "ping_interval": config.ping_interval,
                    "ping_timeout": config.ping_timeout,
                    "close_timeout": config.close_timeout,
                    "additional_headers": config.get_headers(),
                }

                logger.info(f"🔌 开始连接 {connection_uuid} 到 {config.url}")
                logger.info(f"📋 连接参数: {ws_kwargs}")
                logger.info(f"📋 Headers: {config.get_headers()}")

                # 添加SSL配置
                if config.ssl_enabled:
                    import ssl

                    ssl_context = ssl.create_default_context()

                    if not config.ssl_verify:
                        ssl_context.check_hostname = False
                        ssl_context.verify_mode = ssl.CERT_NONE

                    if config.ssl_ca_certs:
                        ssl_context.load_verify_locations(config.ssl_ca_certs)

                    if config.ssl_certfile and config.ssl_keyfile:
                        ssl_context.load_cert_chain(
                            config.ssl_certfile, keyfile=config.ssl_keyfile
                        )

                    if not config.ssl_check_hostname:
                        ssl_context.check_hostname = False

                    ws_kwargs["ssl"] = ssl_context

                logger.info(f"🚀 正在创建WebSocket连接到: {config.url}")
                websocket_connect = websockets.connect(config.url, **ws_kwargs)
                logger.info("✅ WebSocket连接对象已创建，开始握手...")

                async with websocket_connect as websocket:
                    logger.info("🤝 WebSocket握手成功，连接已建立")
                    self.active_connections[connection_uuid] = websocket
                    self.connection_states[connection_uuid] = "connected"
                    reconnect_attempts = 0
                    reconnect_delay = config.reconnect_delay

                    # 更新统计
                    self.stats["total_connections"] += 1
                    self.stats["current_connections"] += 1

                    logger.info(f"Connection {connection_uuid} established")

                    await self._send_event(EventType.CONNECT, connection_uuid)

                    consecutive_failures = 0
                    logger.info("✅ 连接成功,重置连续失败计数")

                    await self._retry_cached_messages(connection_uuid)

                    # 消息接收循环
                    async for message in websocket:
                        if not self.running or connection_uuid not in self.connections:
                            break

                        await self._handle_message(connection_uuid, message)

            except ConnectionClosedError as e:
                if self.running:
                    error_msg = str(e)
                    if "close reason is" in error_msg or "1006" in error_msg:
                        logger.warning(
                            f"🔌 连接 {connection_uuid} 异常关闭: {e} (可能是网络问题或超时)"
                        )
                    else:
                        logger.info(f"🔌 连接 {connection_uuid} 已关闭: {e}")
                    logger.info(
                        f"📊 连接统计: 当前尝试={reconnect_attempts}, 最大尝试={config.max_reconnect_attempts}"
                    )
                    # 关键修复: 发送断开事件
                    await self._send_event(
                        EventType.DISCONNECT, connection_uuid, error=str(e)
                    )
                else:
                    logger.debug(f"🔌 连接 {connection_uuid} 已关闭 (shutdown): {e}")
            except Exception as e:
                # 只在关闭过程中记录这些信息，避免在正常运行时产生过多日志
                if not self.running or self._shutdown_event.is_set():
                    logger.debug(
                        f"❌ 连接异常 {connection_uuid}: {type(e).__name__}: {e}"
                    )
                    # 不记录详细连接信息以减少日志噪音

                self.stats["reconnect_attempts"] += 1

                consecutive_failures += 1
                logger.info(f"📉 连续失败次数: {consecutive_failures}")

                if (
                    consecutive_failures >= 3
                    and self.message_cache
                    and self.message_cache.enabled
                ):
                    logger.warning(
                        f"🗑️ 连续失败 {consecutive_failures} 次,清空消息缓存以避免消息堆积"
                    )
                    self.message_cache.clear()
                    consecutive_failures = 0

                # 安全地发送断开事件
                try:
                    await self._send_event(
                        EventType.DISCONNECT, connection_uuid, error=str(e)
                    )
                except Exception as event_error:
                    logger.debug(
                        f"Error sending disconnect event {connection_uuid}: {event_error}"
                    )

            finally:
                # 清理连接状态
                logger.debug(f"🧹 开始清理连接 {connection_uuid} 的状态")
                if connection_uuid in self.active_connections:
                    del self.active_connections[connection_uuid]
                self.stats["current_connections"] -= 1
                self.connection_states[connection_uuid] = "disconnected"
                logger.debug(
                    f"📊 连接状态已更新为: disconnected, 当前连接数: {self.stats['current_connections']}"
                )

            # 重连逻辑 - 检查是否收到关闭信号
            should_reconnect = (
                self.running
                and connection_uuid in self.connections
                and not self._shutdown_event.is_set()
            )

            if should_reconnect:
                reconnect_attempts += 1
                logger.info(
                    f"🔄 {connection_uuid} 将在 {reconnect_delay}s 后进行第 {reconnect_attempts} 次重连"
                )

                # 使用wait_for来支持关闭中断
                try:
                    logger.info(f"⏳ 等待 {reconnect_delay}s 后重连...")
                    await asyncio.wait_for(asyncio.sleep(reconnect_delay), timeout=30.0)
                    logger.info("✅ 重连等待完成")
                except asyncio.TimeoutError:
                    logger.info("⏰ 重连等待超时，继续重连逻辑")
                    pass

                # 检查关闭状态
                if self._shutdown_event.is_set():
                    logger.info(f"🛑 收到关闭信号，停止 {connection_uuid} 的重连")
                    break

                reconnect_delay = min(config.max_reconnect_delay, reconnect_delay * 2)
                logger.info(f"📈 下次重连延迟将调整为: {reconnect_delay}s")
            else:
                if connection_uuid in self.connections:
                    if self._shutdown_event.is_set():
                        logger.info(f"🛑 {connection_uuid} 优雅关闭")
                else:
                    logger.info(f"🗑️ 连接 {connection_uuid} 已被移除，停止重连")
                break

    async def _handle_message(self, connection_uuid: str, message: Any) -> None:
        """处理接收到的消息"""
        try:
            # 更新统计
            self.stats["messages_received"] += 1
            if isinstance(message, str):
                self.stats["bytes_received"] += len(message.encode("utf-8"))

            logger.info(
                f"📨 收到来自 {connection_uuid} 的消息: {type(message).__name__}"
            )

            if isinstance(message, str):
                try:
                    data = json.loads(message)
                    logger.info(
                        f"✅ JSON解析成功: {list(data.keys()) if isinstance(data, dict) else 'N/A'}"
                    )
                except json.JSONDecodeError as e:
                    logger.info(f"⚠️ JSON解析失败: {e}")
                    data = {"raw_message": message}
            elif isinstance(message, dict):
                data = message
            else:
                data = {"data": str(message)}

            if data.get("type") == "sys_ack":
                acked_msg_id = data.get("meta", {}).get("acked_msg_id")
                if acked_msg_id:
                    logger.info(f"📬 收到ACK确认: acked_msg_id={acked_msg_id}")
                    if self.message_cache and self.message_cache.enabled:
                        removed = self.message_cache.mark_acked(acked_msg_id)
                        if removed:
                            logger.info(f"💾 已从缓存移除消息: {acked_msg_id}")
            else:
                msg_id = data.get("msg_id")
                if msg_id:
                    logger.info(f"📬 发送ACK确认: msg_id={msg_id}")
                    await self._send_ack(connection_uuid, msg_id)

            # 发送消息事件到业务层
            msg_type = data.get("type") if isinstance(data, dict) else "unknown"
            logger.info(f"🚀 发送消息事件到业务层: type={msg_type}")
            await self._send_event(EventType.MESSAGE, connection_uuid, data)

        except Exception as e:
            logger.info(f"❌ 处理 {connection_uuid} 消息时出错: {e}")
            logger.error(f"Message handling error from {connection_uuid}: {e}")

    async def _send_ack(self, connection_uuid: str, msg_id: str) -> None:
        """发送消息确认"""
        try:
            ack_message = {
                "ver": 1,
                "msg_id": str(uuid.uuid4()),
                "type": "sys_ack",
                "meta": {
                    "uuid": connection_uuid,
                    "acked_msg_id": msg_id,
                    "timestamp": time.time(),
                },
                "payload": {"status": "received", "client_timestamp": time.time()},
            }

            await self._send_raw_message(connection_uuid, ack_message)

        except Exception as e:
            logger.error(f"Error sending ACK to {connection_uuid}: {e}")

    async def _retry_cached_messages(self, connection_uuid: str) -> None:
        """重发缓存的消息"""
        if not self.message_cache or not self.message_cache.enabled:
            logger.debug("💾 缓存重试未启用")
            return

        cached_messages = self.message_cache.get_all()
        if not cached_messages:
            logger.debug("💾 没有需要重发的缓存消息")
            return

        logger.info(
            f"💾 开始重发 {len(cached_messages)} 条缓存消息到 {connection_uuid}"
        )

        retry_count = 0
        for cached in cached_messages:
            try:
                success = await self._send_raw_message(connection_uuid, cached.message)
                if success:
                    logger.info(f"✅ 缓存消息重发成功: {cached.message_id}")
                    self.message_cache.mark_retrying(cached.message_id)
                    retry_count += 1
                else:
                    logger.warning(
                        f"⚠️  缓存消息重发失败，保留在缓存中: {cached.message_id}"
                    )
            except Exception as e:
                logger.warning(f"❌ 重发缓存消息时出错: {cached.message_id}, {e}")

        logger.info(f"💾 重发完成: {retry_count}/{len(cached_messages)} 条消息成功")

    def set_message_cache(self, message_cache: MessageCache) -> None:
        """设置消息缓存"""
        self.message_cache = message_cache
        logger.info(f"💾 消息缓存已设置: enabled={message_cache.enabled}")

    async def _send_raw_message(
        self, connection_uuid: str, message: Dict[str, Any]
    ) -> bool:
        """发送原始消息到指定连接"""
        if connection_uuid not in self.active_connections:
            logger.info(f"⚠️ 连接 {connection_uuid} 不活跃，无法发送消息")

            if self.message_cache and self.message_cache.enabled:
                msg_id = message.get("msg_id", "")
                if msg_id:
                    self.message_cache.add(msg_id, message, connection_uuid)
                    logger.info(f"💾 消息已缓存（连接不活跃）: {msg_id}")
            return False

        websocket = self.active_connections[connection_uuid]

        try:
            message_str = json.dumps(message)
            message_size = len(message_str.encode("utf-8"))
            logger.info(
                f"📤 向 {connection_uuid} 发送消息: type={message.get('type', 'unknown')}, size={message_size}字节"
            )

            await websocket.send(message_str)

            # 更新统计
            self.stats["messages_sent"] += 1
            self.stats["bytes_sent"] += message_size

            logger.info(
                f"✅ 消息发送成功: 总计发送 {self.stats['messages_sent']} 条消息"
            )

            return True

        except ConnectionClosed:
            logger.info(f"🔌 发送消息时连接 {connection_uuid} 已关闭")
            self.connection_states[connection_uuid] = "disconnected"

            if self.message_cache and self.message_cache.enabled:
                msg_id = message.get("msg_id", "")
                if msg_id:
                    self.message_cache.add(msg_id, message, connection_uuid)
                    logger.info(f"💾 消息已缓存（连接关闭）: {msg_id}")
            return False
        except Exception as e:
            logger.info(f"❌ 向 {connection_uuid} 发送消息失败: {e}")
            logger.error(f"Error sending message to {connection_uuid}: {e}")

            if self.message_cache and self.message_cache.enabled:
                msg_id = message.get("msg_id", "")
                if msg_id:
                    self.message_cache.add(msg_id, message, connection_uuid)
                    logger.info(f"💾 消息已缓存（发送失败）: {msg_id}")
            return False

    async def send_message(self, connection_uuid: str, message: Dict[str, Any]) -> bool:
        """发送消息到指定连接（业务层接口）"""
        # 如果我们在不同的循环中，必须调度到工作循环
        if (
            self.main_loop
            and self.main_loop.is_running()
            and self.main_loop != asyncio.get_running_loop()
        ):
            # 使用 run_coroutine_threadsafe 调度并通过 wrap_future 等待结果
            future = asyncio.run_coroutine_threadsafe(
                self._send_raw_message(connection_uuid, message), self.main_loop
            )
            return await asyncio.wrap_future(future)

        return await self._send_raw_message(connection_uuid, message)

    async def _send_event(
        self,
        event_type: EventType,
        connection_uuid: str,
        payload: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """发送事件到业务层"""
        if not self.event_queue:
            logger.warning("Event queue not available, event dropped")
            return

        try:
            config = self.connections.get(connection_uuid)
            if not config:
                logger.warning(f"No config for connection {connection_uuid}")
                return

            event = NetworkEvent(
                event_type=event_type,
                connection_uuid=connection_uuid,
                config=config,
                payload=payload,
                error=error,
            )

            # 直接发送事件到队列
            # 注意：这是跨线程操作！我们必须使用 queue_loop 的 call_soon_threadsafe
            if self.queue_loop and self.queue_loop != asyncio.get_running_loop():
                logger.debug(f"Cross-thread dispatch to loop {id(self.queue_loop)}")
                self.queue_loop.call_soon_threadsafe(self.event_queue.put_nowait, event)
            else:
                # 如果我们在同一个循环中（或者没有捕获 loop），可以直接 put
                logger.debug("Same-loop dispatch")
                # 注意：put 是协程，会等待队列空闲。但在同一个Loop中是安全的。
                await self.event_queue.put(event)

        except Exception as e:
            logger.error(f"Error sending event to business layer: {e}")

    def get_connection_count(self) -> int:
        """获取当前连接数"""
        return len(self.active_connections)

    def get_connection_list(self) -> Set[str]:
        """获取所有连接UUID"""
        return set(self.connections.keys())

    def get_active_connections(self) -> Set[str]:
        """获取活跃连接UUID"""
        return set(self.active_connections.keys())

    def get_connection_state(self, connection_uuid: str) -> Optional[str]:
        """获取连接状态"""
        return self.connection_states.get(connection_uuid)

    def get_connection_config(self, connection_uuid: str) -> Optional[ConnectionConfig]:
        """获取连接配置"""
        return self.connections.get(connection_uuid)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.stats.copy()

    def _worker_loop_run(self, event_queue: asyncio.Queue) -> None:
        """工作线程中运行的事件循环"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # 添加全局异常处理器以屏蔽关闭时的噪声
        def ignore_shutdown_noise(loop, context):
            message = context.get("message", "")
            # 屏蔽 asyncio 关闭时的常见噪声
            if "Event loop is closed" in message or "Task was destroyed" in message:
                return
            # 屏蔽 connection_loop 相关的 Coroutine 警告
            if "connection_loop" in str(context.get("future", "")):
                return
            # 默认处理
            loop.default_exception_handler(context)

        loop.set_exception_handler(ignore_shutdown_noise)

        try:
            # 设置事件队列和主循环引用
            self.event_queue = event_queue
            self.main_loop = loop
            self.running = True

            # 运行连接管理循环
            loop.run_until_complete(self._manage_connections())

        except Exception as e:
            logger.error(f"Worker loop error: {e}")
        finally:
            self.running = False

            # 标准的 asyncio 优雅关闭流程
            try:
                # 1. 获取所有未完成的任务（排除当前任务如果存在）
                pending = asyncio.all_tasks(loop)
                if pending:
                    logger.debug(
                        f"Cleaning up {len(pending)} pending tasks in worker loop..."
                    )
                    for task in pending:
                        task.cancel()

                    # 2. 运行直到所有任务取消完成
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )

                # 3. 关闭异步生成器
                loop.run_until_complete(loop.shutdown_asyncgens())

                # 4. 关闭执行器 (如果有的话，默认是 None 但为了保险)
                # await loop.shutdown_default_executor() # Python 3.9+

            except Exception as e:
                logger.error(f"Error during worker loop graceful shutdown: {e}")
            finally:
                logger.debug("Worker loop closed")
                loop.close()

    async def _manage_connections(self) -> None:
        """管理所有连接"""
        while self.running:
            try:
                await asyncio.sleep(0.1)  # 避免CPU占用过高
            except asyncio.CancelledError:
                break

    def set_event_queue(self, event_queue: asyncio.Queue) -> None:
        """设置事件队列"""
        self.event_queue = event_queue
        # 捕获队列所属的事件循环
        try:
            self.queue_loop = asyncio.get_running_loop()
            logger.info(f"Set event queue loop: {id(self.queue_loop)}")
        except RuntimeError:
            # 如果在非async环境调用(不太可能，除了测试)，尝试获取队列的循环
            self.queue_loop = getattr(event_queue, "_loop", None)
            logger.info(
                f"Set event queue loop from arg: {id(self.queue_loop) if self.queue_loop else 'None'}"
            )

    async def start(self, event_queue: Optional[asyncio.Queue] = None) -> None:
        if self.running:
            logger.warning("Network driver already running")
            return

        self._shutdown_event.clear()

        self._init_log_queue()

        if self._log_processor:
            await self._log_processor.start()

        if event_queue:
            self.event_queue = event_queue

        if not self.event_queue:
            raise ValueError("Event queue is required")

        self.worker_thread = threading.Thread(
            target=self._worker_loop_run, args=(self.event_queue,), daemon=True
        )
        self.worker_thread.start()

        await asyncio.sleep(0.5)

        logger.info("Client network driver started")

    async def _cleanup_worker_tasks(self) -> None:
        """在工作线程循环中清理所有任务（这是内部方法，必须在工作线程中运行）"""
        logger.debug("🧹 正在工作线程中执行清理...")

        # 1. 取消所有连接任务
        active_tasks = []
        for connection_uuid, task in list(self.connection_tasks.items()):
            if task and not task.done():
                task.cancel()
                active_tasks.append(task)

        # 2. 等待任务取消完成
        if active_tasks:
            logger.debug(f"⏳ 等待 {len(active_tasks)} 个连接任务取消...")
            # 使用 return_exceptions=True 防止异常中断清理流程
            await asyncio.gather(*active_tasks, return_exceptions=True)

        # 3. 显式关闭所有活跃的 WebSocket 连接
        # 虽然 connection_loop 被取消会触发 context manager 退出从而关闭 WS，
        # 但显式关闭更安全，且能处理那些不在 context manager 管理下的连接（如果有）
        close_futs = []
        for connection_uuid, websocket in list(self.active_connections.items()):
            try:
                # 发送关闭帧，不等待对方确认以加快速度
                close_futs.append(websocket.close())
            except Exception:
                pass

        if close_futs:
            logger.debug(f"🔌 关闭 {len(close_futs)} 个活跃 WebSocket 连接...")
            await asyncio.gather(*close_futs, return_exceptions=True)

        # 4. 清理状态
        self.active_connections.clear()
        self.connection_tasks.clear()
        self.connection_states.clear()
        self.connections.clear()
        logger.debug("✅ 工作线程资源清理完成")

    async def stop(self) -> None:
        """停止网络驱动器 - 完全清理所有协程"""
        if not self.running:
            return

        logger.info("Stopping client network driver...")

        self._shutdown_event.set()
        self.running = False

        if self._log_processor:
            await self._log_processor.stop()
            self._log_processor = None

        if self.main_loop and self.main_loop.is_running():
            try:
                cleanup_future = asyncio.run_coroutine_threadsafe(
                    self._cleanup_worker_tasks(), self.main_loop
                )
                cleanup_future.result(timeout=3.0)
            except Exception as e:
                logger.warning(f"Error during worker cleanup dispatch: {e}")

        if self.worker_thread and self.worker_thread.is_alive():
            try:
                self.worker_thread.join(timeout=3.0)
                if self.worker_thread.is_alive():
                    logger.warning("Worker thread did not stop gracefully")
            except Exception as e:
                logger.error(f"Error joining worker thread: {e}")

        self.stats = {
            "total_connections": 0,
            "current_connections": 0,
            "messages_received": 0,
            "messages_sent": 0,
            "bytes_received": 0,
            "bytes_sent": 0,
            "reconnect_attempts": 0,
        }

        self.main_loop = None
        self.worker_thread = None
        self._log_queue = None

        logger.info("Client network driver stopped completely")
