"""Socket.IO 客户端网络驱动器 - 替代 websockets 实现"""

from __future__ import annotations

# 储备: 此代码目前未完成，正在开发中...

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set, List
from enum import Enum

import socketio
import aiohttp
from aiohttp import ClientSession

from aiohttp import TCPConnector

from .message_cache import MessageCache
from .log_utils import get_logger

logger = get_logger()


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
    connection_uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    headers: Dict[str, str] = field(default_factory=dict)
    ping_interval: int = 20
    ping_timeout: int = 10
    close_timeout: int = 10
    max_size: int = 104_857_600
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

    # Socket.IO 特有配置
    socketio_path: str = "socket.io"

    transports: List[str] = field(default_factory=lambda: ["websocket"])

    auth: Optional[Dict[str, Any]] = None

    extra_headers: Optional[Dict[str, str]] = None

    wait_timeout: float = 10.0

    def get_headers(self) -> Dict[str, str]:
        """获取连接用的headers"""
        headers: Dict[str, str] = self.headers.copy()
        headers.update(
            {
                "x-uuid": self.connection_uuid,
                "x-apikey": self.api_key,
                "x-platform": self.platform,
            }
        )
        if self.extra_headers:
            headers.update(self.extra_headers)
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
            "max_size": self.max_size,
            "max_reconnect_attempts": self.max_reconnect_attempts,
            "reconnect_delay": self.reconnect_delay,
            "max_reconnect_delay": self.max_reconnect_delay,
            "ssl_enabled": self.ssl_enabled,
            "ssl_verify": self.ssl_verify,
            "ssl_ca_certs": self.ssl_ca_certs,
            "socketio_path": self.socketio_path,
        }


@dataclass
class NetworkEvent:
    """Network event data class"""

    event_type: EventType
    connection_uuid: str
    config: ConnectionConfig
    payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()


# Type alias for backward compatibility
NetworkEvent = NetworkEvent


class ClientNetworkDriver:
    """基于 Socket.IO 的客户端网络驱动器"""

    MAX_CONCURRENT_CONNECTIONS = 100

    def __init__(self, custom_logger: Optional[Any] = None):
        # 连接管理
        self.connections: Dict[str, ConnectionConfig] = {}
        self.active_connections: Dict[str, socketio.AsyncClient] = {}
        self.connection_states: Dict[str, str] = {}

        if custom_logger is not None:
            self.logger = custom_logger
        else:
            self.logger = logger

        # 跨线程通信
        self.event_queue: Optional[asyncio.Queue] = None
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

        # 消息缓存支持
        self.message_cache: Optional[MessageCache] = None

        # SSL context
        self._ssl_context = None

        # HTTP session for SSL
        self._http_session: Optional[ClientSession] = None

    def _build_ssl_context(self, config: ConnectionConfig) -> Optional[Any]:
        """构建 SSL 上下文"""
        if not config.ssl_enabled:
            return None
        import ssl

        ssl_context = ssl.create_default_context()
        if not config.ssl_verify:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        if config.ssl_ca_certs:
            ssl_context.load_verify_locations(config.ssl_ca_certs)
        if config.ssl_certfile and config.ssl_keyfile:
            ssl_context.load_cert_chain(config.ssl_certfile, keyfile=config.ssl_keyfile)
        if not config.ssl_check_hostname:
            ssl_context.check_hostname = False
        return ssl_context

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
                self.logger.info(f"复用现有连接 {connection_uuid}")
                return True
            else:
                self.logger.warning(
                    f"连接 {connection_uuid} 已存在不同配置。 "
                    f"现有: {existing.url}, 新: {config.url}"
                )
                return False
        self.connections[connection_uuid] = config
        self.connection_states[connection_uuid] = "disconnected"
        self.logger.info(f"添加连接 {connection_uuid} 到 {config.url}")
        return True

    async def remove_connection(self, connection_uuid: str) -> bool:
        """移除连接"""
        if connection_uuid not in self.connections:
            self.logger.warning(f"连接 {connection_uuid} 未找到")
            return False
        # 壜止连接任务
        if connection_uuid in self.connection_tasks:
            self.connection_tasks[connection_uuid].cancel()
            try:
                await self.connection_tasks[connection_uuid]
            except asyncio.CancelledError:
                pass
            del self.connection_tasks[connection_uuid]
        # 断开 Socket.IO 连接
        if connection_uuid in self.active_connections:
            sio = self.active_connections[connection_uuid]
            try:
                await sio.disconnect()
            except Exception:
                pass
            del self.active_connections[connection_uuid]
        # 清理状态
        del self.connections[connection_uuid]
        del self.connection_states[connection_uuid]
        self.logger.info(f"移除连接 {connection_uuid}")
        return True

    async def connect(self, connection_uuid: str) -> bool:
        """连接到服务器"""
        if connection_uuid not in self.connections:
            self.logger.error(f"连接 {connection_uuid} 未找到")
            return False
        if self.connection_states[connection_uuid] == "connected":
            self.logger.info(f"连接 {connection_uuid} 已连接")
            return True
        if len(self.active_connections) >= self.MAX_CONCURRENT_CONNECTIONS:
            self.logger.error(
                f"连接数达到上限 {self.MAX_CONCURRENT_CONNECTIONS}，拒绝新连接 {connection_uuid}"
            )
            return False
        config = self.connections[connection_uuid]
        # 启动连接任务
        if connection_uuid not in self.connection_tasks:
            self._create_connection_task(connection_uuid)
        return True

    def _create_connection_task(self, connection_uuid: str) -> None:
        """创建连接任务"""
        task = asyncio.create_task(self._connection_loop(connection_uuid))
        self.connection_tasks[connection_uuid] = task

        def task_done_callback(fut):
            if fut.exception():
                self.logger.error(f"连接任务 {connection_uuid} 异常: {fut.exception()}")
            else:
                self.logger.info(f"连接任务 {connection_uuid} 正常结束")
            if connection_uuid in self.connection_tasks:
                del self.connection_tasks[connection_uuid]

        task.add_done_callback(task_done_callback)

    async def disconnect(self, connection_uuid: str) -> bool:
        """断开连接"""
        if connection_uuid not in self.connections:
            self.logger.warning(f"连接 {connection_uuid} 未找到")
            return False
        try:
            self.connection_states[connection_uuid] = "disconnecting"
            # 壜止连接任务
            if connection_uuid in self.connection_tasks:
                task = self.connection_tasks[connection_uuid]
                if task and not task.done():
                    task.cancel()
                    self.logger.debug(f"取消 {connection_uuid} 的任务")
                del self.connection_tasks[connection_uuid]
            # 断开 Socket.IO 连接
            if connection_uuid in self.active_connections:
                sio = self.active_connections[connection_uuid]
                try:
                    await sio.disconnect()
                    self.logger.info(f"等待 {connection_uuid} 断开...")
                    await asyncio.sleep(0.5)
                    self.logger.info(f"连接 {connection_uuid} 已断开")
                except Exception as e:
                    self.logger.debug(f"断开 WebSocket 锶 {connection_uuid} 错: {e}")
                finally:
                    del self.active_connections[connection_uuid]
                    self.logger.info(f"从活跃连接移除 {connection_uuid}")
            self.connection_states[connection_uuid] = "disconnected"
            return True
        except Exception as e:
            self.logger.warning(f"断开 {connection_uuid} 时出错: {e}")
            self.connection_states[connection_uuid] = "disconnected"
            return True

    async def _connection_loop(self, connection_uuid: str) -> None:
        """连接管理循环"""
        self.logger.info(f"开始连接循环: {connection_uuid}")
        config = self.connections[connection_uuid]
        reconnect_delay = config.reconnect_delay
        reconnect_attempts = 0
        consecutive_failures = 0
        # 创建 Socket.IO 客户端
        sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,  # 无限重连
            reconnection_delay=1,
            reconnection_delay_max=5,
        )
        # 设置 SSL
        ssl_context = self._build_ssl_context(config)
        if ssl_context:
            # 创建带有 SSL 的 HTTP session
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self._http_session = aiohttp.ClientSession(connector=connector)
            self._ssl_context = ssl_context
            # 重新创建带有 HTTP session 的 Socket.IO 客户端
            sio = socketio.AsyncClient(
                reconnection=True,
                reconnection_attempts=0,
                reconnection_delay=1,
                reconnection_delay_max=5,
                http_session=self._http_session,
            )
        while (
            self.running
            and connection_uuid in self.connections
            and not self._shutdown_event.is_set()
        ):
            if (
                config.max_reconnect_attempts > 0
                and reconnect_attempts >= config.max_reconnect_attempts
            ):
                self.logger.error(
                    f"连接 {connection_uuid} 达到最大重连次数 {config.max_reconnect_attempts}"
                )
                break
            try:
                # 尝试连接
                self.connection_states[connection_uuid] = "connecting"
                self.logger.info(f"连接 {connection_uuid} 到 {config.url}")
                # 提取 URL 中的 path
                from urllib.parse import urlparse

                parsed = urlparse(
                    config.url.replace("wss://", "https://").replace("ws://", "http://")
                )
                socketio_path = parsed.path if parsed.path else config.socketio_path
                extra_headers = config.get_headers()
                if config.auth:
                    extra_headers.update(config.auth)
                # 连接选项
                connect_kwargs = {
                    "socketio_path": socketio_path,
                    "headers": extra_headers,
                    "wait_timeout": config.wait_timeout,
                    "transports": config.transports,
                }
                self.logger.info(
                    f"Socket.IO 连接参数: path={socketio_path}, headers={extra_headers}"
                )
                await sio.connect(
                    config.url.replace("wss://", "https://").replace(
                        "ws://", "http://"
                    ),
                    **connect_kwargs,
                )
                self.active_connections[connection_uuid] = sio
                self.connection_states[connection_uuid] = "connected"
                reconnect_attempts = 0
                reconnect_delay = config.reconnect_delay
                # 更新统计
                self.stats["total_connections"] += 1
                self.stats["current_connections"] += 1
                self.logger.info(f"连接 {connection_uuid} 已建立")
                await self._send_event(EventType.CONNECT, connection_uuid)
                consecutive_failures = 0
                self.logger.info("连接成功, 重置连续失败计数")
                # 重发缓存消息
                await self._retry_cached_messages(connection_uuid)

                # 设置消息处理器
                @sio.on("message")  # type: ignore[union-attr]
                async def on_message(data: Any) -> None:
                    await self._handle_message(connection_uuid, data)

                # 等待连接断开或关闭信号
                while self.running and connection_uuid in self.connections:
                    try:
                        await asyncio.sleep(1.0)
                    except asyncio.CancelledError:
                        break
            except Exception as e:
                if self.running:
                    error_msg = str(e)
                    self.logger.warning(f"连接 {connection_uuid} 异常关闭: {e}")
                else:
                    self.logger.info(f"连接 {connection_uuid} 已关闭: {e}")
                await self._send_event(
                    EventType.DISCONNECT, connection_uuid, error=str(e)
                )

            finally:
                # 清理连接状态
                self.logger.debug(f"清理连接 {connection_uuid} 的状态")
                if connection_uuid in self.active_connections:
                    del self.active_connections[connection_uuid]
                self.stats["current_connections"] -= 1
                self.connection_states[connection_uuid] = "disconnected"
                self.logger.debug(
                    f"连接状态: disconnected, 当前连接数: {self.stats['current_connections']}"
                )
            # 重连逻辑
            should_reconnect = (
                self.running
                and connection_uuid in self.connections
                and not self._shutdown_event.is_set()
            )
            if should_reconnect:
                reconnect_attempts += 1
                self.logger.info(
                    f"{connection_uuid} 将在 {reconnect_delay}s 后进行第 {reconnect_attempts} 次重连"
                )
                try:
                    await asyncio.wait_for(asyncio.sleep(reconnect_delay), timeout=30.0)
                    self.logger.debug("重连等待完成")
                except asyncio.TimeoutError:
                    self.logger.debug("重连等待超时")
                pass
                if self._shutdown_event.is_set():
                    self.logger.info(f"收到关闭信号, 停止 {connection_uuid} 的重连")
                    break
                reconnect_delay = min(config.max_reconnect_delay, reconnect_delay * 2)
            else:
                if connection_uuid in self.connections:
                    if self._shutdown_event.is_set():
                        self.logger.info(f"{connection_uuid} 优雅关闭")
                else:
                    self.logger.info(f"连接 {connection_uuid} 已移除, 停止重连")
                break

    async def _handle_message(self, connection_uuid: str, message: Any) -> None:
        """处理接收到的消息"""
        try:
            self.stats["messages_received"] += 1
            if isinstance(message, str):
                self.stats["bytes_received"] += len(message.encode("utf-8"))
            self.logger.info(f"收到来自 {connection_uuid} 的消息")

            data: Dict[str, Any]
            if isinstance(message, str):
                try:
                    parsed = json.loads(message)
                    if isinstance(parsed, dict):
                        data = parsed
                    else:
                        data = {"data": parsed}
                    self.logger.debug(f"JSON 解析成功")
                except json.JSONDecodeError:
                    self.logger.warning(f"JSON 解析失败")
                    data = {"raw_message": message}
            elif isinstance(message, dict):
                data = message
            else:
                data = {"data": str(message)}

            if data.get("type") == "sys_ack":
                meta = data.get("meta", {})
                acked_msg_id = (
                    meta.get("acked_msg_id") if isinstance(meta, dict) else None
                )
                if acked_msg_id:
                    self.logger.debug(f"收到 ACK 确认: acked_msg_id={acked_msg_id}")
                    if self.message_cache and self.message_cache.enabled:
                        removed = self.message_cache.mark_acked(acked_msg_id)
                        if removed:
                            self.logger.debug(f"从缓存移除消息: {acked_msg_id}")
            else:
                msg_id = data.get("msg_id")
                if msg_id:
                    self.logger.debug(f"发送 ACK 确认: msg_id={msg_id}")
                    await self._send_ack(connection_uuid, msg_id)
            await self._send_event(EventType.MESSAGE, connection_uuid, data)
        except Exception as e:
            self.logger.error(f"处理 {connection_uuid} 消息出错: {e}")

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
            self.logger.error(f"发送 ACK 到 {connection_uuid} 头败: {e}")

    async def _retry_cached_messages(self, connection_uuid: str) -> None:
        """重发缓存的消息"""
        if not self.message_cache or not self.message_cache.enabled:
            self.logger.debug("缓存重试未启用")
            return
        cached_messages = self.message_cache.get_all()
        if not cached_messages:
            self.logger.debug("没有需要重发的缓存消息")
            return
        self.logger.info(f"重发 {len(cached_messages)} 条缓存消息到 {connection_uuid}")
        retry_count = 0
        for cached in cached_messages:
            try:
                success = await self._send_raw_message(connection_uuid, cached.message)
                if success:
                    self.logger.info(f"缓存消息重发成功: {cached.message_id}")
                    self.message_cache.mark_retrying(cached.message_id)
                    retry_count += 1
                else:
                    self.logger.warning(f"缓存消息重发失败: {cached.message_id}")
            except Exception as e:
                self.logger.warning(f"重发缓存消息出错: {cached.message_id}, {e}")
        self.logger.info(f"重发完成: {retry_count}/{len(cached_messages)} 条成功")

    def set_message_cache(self, message_cache: MessageCache) -> None:
        """设置消息缓存"""
        self.message_cache = message_cache
        self.logger.info(f"消息缓存已设置: enabled={message_cache.enabled}")

    async def _send_raw_message(
        self, connection_uuid: str, message: Dict[str, Any]
    ) -> bool:
        """发送原始消息"""
        if connection_uuid not in self.active_connections:
            self.logger.warning(f"连接 {connection_uuid} 不活跃, 无法发送消息")
            if self.message_cache and self.message_cache.enabled:
                msg_id = message.get("msg_id", "")
                if msg_id:
                    self.message_cache.add(msg_id, message, connection_uuid)
                    self.logger.info(f"消息已缓存: {msg_id}")
            return False
        sio = self.active_connections[connection_uuid]
        try:
            if isinstance(message, dict):
                message_str = json.dumps(message)
            else:
                message_str = str(message)
            message_size = len(message_str.encode("utf-8"))
            self.logger.debug(
                f"发送消息到 {connection_uuid}, 大小: {message_size} 字节"
            )
            await sio.emit("message", message)
            # 更新统计
            self.stats["messages_sent"] += 1
            self.stats["bytes_sent"] += message_size
            self.logger.debug(f"消息发送成功")
            return True
        except Exception as e:
            self.logger.error(f"发送消息到 {connection_uuid} 失败: {e}")
            if self.message_cache and self.message_cache.enabled:
                msg_id = message.get("msg_id", "")
                if msg_id:
                    self.message_cache.add(msg_id, message, connection_uuid)
            return False

    async def send_message(self, connection_uuid: str, message: Dict[str, Any]) -> bool:
        """发送消息（业务层接口）"""
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
            self.logger.warning("事件队列不可用, 事件被丢弃")
            return
        try:
            config = self.connections.get(connection_uuid)
            if not config:
                self.logger.warning(f"连接 {connection_uuid} 没有配置")
                return
            event = NetworkEvent(
                event_type=event_type,
                connection_uuid=connection_uuid,
                config=config,
                payload=payload,
                error=error,
            )
            await self.event_queue.put(event)
            self.logger.debug(f"事件 {event_type.value} 已发送")
        except Exception as e:
            self.logger.error(f"发送事件到业务层失败: {e}")

    def get_connection_count(self) -> int:
        """获取当前连接数"""
        return len(self.active_connections)

    def get_connection_list(self) -> Set[str]:
        """获取所有连接 UUID"""
        return set(self.connections.keys())

    def get_active_connections(self) -> Set[str]:
        """获取活跃连接 UUID"""
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

    def set_event_queue(self, event_queue: asyncio.Queue) -> None:
        """设置事件队列"""
        self.event_queue = event_queue
        self.logger.debug(f"事件队列已设置")

    async def start(self, event_queue: Optional[asyncio.Queue] = None) -> None:
        """启动网络驱动器"""
        if self.running:
            self.logger.warning("网络驱动器已在运行")
            return
        self._shutdown_event.clear()
        if event_queue:
            self.event_queue = event_queue
        if not self.event_queue:
            raise ValueError("事件队列是必需的")
        self.running = True
        self.logger.info("客户端网络驱动器已启动")

    async def stop(self) -> None:
        """停止网络驱动器"""
        if not self.running:
            return
        self.logger.info("停止客户端网络驱动器...")
        self._shutdown_event.set()
        self.running = False
        # 取消所有连接任务
        for connection_uuid in list(self.connection_tasks.keys()):
            try:
                await self.disconnect(connection_uuid)
            except Exception as e:
                self.logger.warning(f"断开 {connection_uuid} 时出错: {e}")
        # 清理 HTTP session
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None
        self._ssl_context = None
        # 清理状态
        self.active_connections.clear()
        self.connection_tasks.clear()
        self.connection_states.clear()
        self.connections.clear()
        self.stats = {
            "total_connections": 0,
            "current_connections": 0,
            "messages_received": 0,
            "messages_sent": 0,
            "bytes_received": 0,
            "bytes_sent": 0,
            "reconnect_attempts": 0,
        }
        self.logger.info("客户端网络驱动器已完全停止")
