"""Socket.IO 服务端网络驱动器 - 替代 websockets 实现"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, Optional, Set
from enum import Enum

import socketio
import aiohttp
from aiohttp import web
import uvicorn

from .message_cache import MessageCache
from .log_utils import get_logger

logger = get_logger()


class EventType(Enum):
    """事件类型"""

    CONNECT = "connect"
    DISCONNECT = "disconnect"
    MESSAGE = "message"


@dataclass
class ConnectionMetadata:
    """连接元数据"""

    uuid: str
    api_key: str
    platform: str
    headers: Dict[str, str]
    client_ip: Optional[str] = None
    connected_at: float = 0.0
    sid: str = ""  # Socket.IO session id

    def __post_init__(self) -> None:
        if self.connected_at == 0.0:
            self.connected_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        # 清理headers中的敏感信息
        if "authorization" in result["headers"]:
            result["headers"] = {
                k: v
                for k, v in result["headers"].items()
                if k.lower() != "authorization"
            }
        return result


@dataclass
class NetworkEvent:
    """网络事件"""

    event_type: EventType
    uuid: str
    metadata: ConnectionMetadata
    payload: Optional[Dict[str, Any]] = None
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class ServerNetworkDriver:
    """基于 Socket.IO 的服务端网络驱动器"""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 18000,
        path: str = "/ws",
        ssl_enabled: bool = False,
        ssl_certfile: Optional[str] = None,
        ssl_keyfile: Optional[str] = None,
        ssl_ca_certs: Optional[str] = None,
        ssl_verify: bool = False,
        max_message_size: int = 104_857_600,
        custom_logger: Optional[Any] = None,
        heartbeat_interval: float = 25.0,
        heartbeat_timeout: float = 5.0,
    ):
        self.host = host
        self.port = port
        self.path = path

        # SSL配置
        self.ssl_enabled = ssl_enabled
        self.ssl_certfile = ssl_certfile
        self.ssl_keyfile = ssl_keyfile
        self.ssl_ca_certs = ssl_ca_certs
        self.ssl_verify = ssl_verify

        # WebSocket消息大小限制
        self.max_message_size = max_message_size
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout

        if custom_logger is not None:
            self.logger = custom_logger
        else:
            self.logger = logger

        # 连接管理
        self.active_connections: Dict[str, str] = {}  # connection_uuid -> sid
        self.sid_connections: Dict[str, str] = {}  # sid -> connection_uuid
        self.connection_metadata: Dict[str, ConnectionMetadata] = {}

        # 跨线程通信
        self.event_queue: Optional[asyncio.Queue] = None
        self.running = False

        # Socket.IO server
        self.sio = socketio.AsyncServer(
            async_mode="aiohttp",
            ping_interval=int(heartbeat_interval),
            ping_timeout=int(heartbeat_timeout),
            cors_allowed_origins="*",
            max_http_buffer_size=max_message_size,
        )

        # aiohttp app
        self.app = web.Application()
        self._runner: Optional[web.AppRunner] = None

        # 统计信息
        self.stats = {
            "total_connections": 0,
            "current_connections": 0,
            "messages_received": 0,
            "messages_sent": 0,
            "bytes_received": 0,
            "bytes_sent": 0,
        }

        # 消息缓存支持
        self.message_cache: Optional[MessageCache] = None

        # 设置 Socket.IO 事件处理器
        self._setup_socketio_handlers()

    def _setup_socketio_handlers(self) -> None:
        """设置 Socket.IO 事件处理器"""

        @self.sio.event
        async def connect(sid: str, environ: dict, auth: Optional[dict] = None) -> None:
            """处理连接事件"""
            # 提取连接信息
            headers = {}
            for key, value in environ.items():
                if key.startswith("HTTP_"):
                    # CGI converts hyphens to underscores, so restore them
                    # e.g., HTTP_X_PLATFORM -> x-platform (not x_platform)
                    header_name = key[5:].lower().replace("_", "-")
                    headers[header_name] = value

            # 从 headers 或 auth 中提取元数据
            connection_uuid = headers.get("x-uuid") or str(uuid.uuid4())
            api_key = headers.get("x-apikey", "")
            platform = headers.get("x-platform", "unknown")
            client_ip = environ.get("REMOTE_ADDR", "unknown")

            # 创建连接元数据
            metadata = ConnectionMetadata(
                uuid=connection_uuid,
                api_key=api_key,
                platform=platform,
                headers=headers,
                client_ip=client_ip,
                sid=sid,
            )

            # 存储连接映射
            self.active_connections[connection_uuid] = sid
            self.sid_connections[sid] = connection_uuid
            self.connection_metadata[connection_uuid] = metadata

            # 更新统计
            self.stats["total_connections"] += 1
            self.stats["current_connections"] += 1

            self.logger.info(
                f"客户端连接: uuid={connection_uuid}, sid={sid}, platform={platform}"
            )

            # 发送连接事件到业务层
            await self._send_event(EventType.CONNECT, connection_uuid)

        @self.sio.event
        async def disconnect(sid: str) -> None:
            """处理断连事件"""
            connection_uuid = self.sid_connections.get(sid)
            if not connection_uuid:
                self.logger.warning(f"未知的 sid 断开连接: {sid}")
                return

            # 获取元数据
            metadata = self.connection_metadata.get(connection_uuid)

            # 清理连接映射
            if connection_uuid in self.active_connections:
                del self.active_connections[connection_uuid]
            if sid in self.sid_connections:
                del self.sid_connections[sid]
            if connection_uuid in self.connection_metadata:
                del self.connection_metadata[connection_uuid]

            # 更新统计
            if self.stats["current_connections"] > 0:
                self.stats["current_connections"] -= 1

            self.logger.info(f"客户端断开: uuid={connection_uuid}, sid={sid}")

            # 发送断连事件到业务层
            if metadata:
                await self._send_event(EventType.DISCONNECT, connection_uuid)

        @self.sio.on("message")  # type: ignore[union-attr]
        async def handle_message(sid: str, data: Any) -> None:
            """处理消息事件"""
            connection_uuid = self.sid_connections.get(sid)
            if not connection_uuid:
                self.logger.warning(f"收到来自未知 sid 的消息: {sid}")
                return

            # 更新统计
            self.stats["messages_received"] += 1
            if isinstance(data, str):
                self.stats["bytes_received"] += len(data.encode("utf-8"))
            elif isinstance(data, dict):
                self.stats["bytes_received"] += len(str(data))

            # 解析消息
            if isinstance(data, str):
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    payload = {"raw_message": data}
            else:
                payload = data if isinstance(data, dict) else {"data": str(data)}

            # 发送 ACK 确认
            msg_id = payload.get("msg_id")
            if msg_id and payload.get("type") != "sys_ack":
                await self._send_ack(connection_uuid, msg_id)

            # 发送消息事件到业务层
            await self._send_event(EventType.MESSAGE, connection_uuid, payload)

    async def _send_event(
        self,
        event_type: EventType,
        connection_uuid: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """发送事件到业务层"""
        if not self.event_queue:
            self.logger.warning("事件队列未初始化，事件被丢弃")
            return

        try:
            metadata = self.connection_metadata.get(connection_uuid)
            if not metadata:
                # 对于清理事件，创建基本元数据
                if event_type == EventType.DISCONNECT:
                    metadata = ConnectionMetadata(
                        uuid=connection_uuid,
                        api_key="",
                        platform="unknown",
                        headers={},
                        client_ip="unknown",
                        sid="",
                    )
                else:
                    self.logger.debug(
                        f"连接 {connection_uuid} 的元数据未找到 - 可能已被清理"
                    )
                    return

            event = NetworkEvent(
                event_type=event_type,
                uuid=connection_uuid,
                metadata=metadata,
                payload=payload,
            )

            await self.event_queue.put(event)
            self.logger.debug(f"事件 {event_type.value} 已发送: {connection_uuid}")

        except Exception as e:
            self.logger.error(f"发送事件到业务层时出错: {e}")

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
                "payload": {"status": "received", "server_timestamp": time.time()},
            }

            await self._send_raw_message(connection_uuid, ack_message)

            # 从缓存中移除已确认的消息
            if self.message_cache and self.message_cache.enabled:
                self.message_cache.remove(msg_id)

        except Exception as e:
            self.logger.error(f"发送 ACK 到 {connection_uuid} 时出错: {e}")

    async def _retry_cached_messages(self, connection_uuid: str) -> None:
        """重发该连接的缓存消息"""
        if not self.message_cache or not self.message_cache.enabled:
            return

        cached_messages = self.message_cache.get_by_target(connection_uuid)
        if not cached_messages:
            return

        self.logger.info(f"重发 {len(cached_messages)} 条缓存消息到 {connection_uuid}")

        for cached in cached_messages:
            try:
                success = await self._send_raw_message(connection_uuid, cached.message)
                if success:
                    self.logger.debug(f"重发成功: {cached.message_id}")
            except Exception as e:
                self.logger.debug(f"重发错误: {cached.message_id}, {e}")

    async def _send_raw_message(
        self, connection_uuid: str, message: Dict[str, Any]
    ) -> bool:
        """发送原始消息到指定连接"""
        sid = self.active_connections.get(connection_uuid)
        if not sid:
            self.logger.warning(f"连接 {connection_uuid} 未找到")

            if self.message_cache and self.message_cache.enabled:
                msg_id = message.get("msg_id", "")
                if msg_id:
                    self.message_cache.add(msg_id, message, connection_uuid)
            return False

        try:
            await self.sio.emit("message", message, room=sid)

            # 更新统计
            self.stats["messages_sent"] += 1
            message_str = json.dumps(message)
            self.stats["bytes_sent"] += len(message_str.encode("utf-8"))

            return True

        except Exception as e:
            self.logger.error(f"发送消息到 {connection_uuid} 时出错: {e}")

            if self.message_cache and self.message_cache.enabled:
                msg_id = message.get("msg_id", "")
                if msg_id:
                    self.message_cache.add(msg_id, message, connection_uuid)

            # 清理连接
            await self._cleanup_connection(connection_uuid)
            return False

    async def _cleanup_connection(self, connection_uuid: str) -> None:
        """清理连接资源"""
        try:
            sid = self.active_connections.get(connection_uuid)

            if sid:
                try:
                    await self.sio.disconnect(sid)
                except Exception:
                    pass

            # 清理映射
            if connection_uuid in self.active_connections:
                del self.active_connections[connection_uuid]
            if sid and sid in self.sid_connections:
                del self.sid_connections[sid]
            if connection_uuid in self.connection_metadata:
                del self.connection_metadata[connection_uuid]

            # 更新统计
            if self.stats.get("current_connections", 0) > 0:
                self.stats["current_connections"] -= 1

        except Exception as e:
            self.logger.debug(
                f"清理连接 {connection_uuid} 时出错: {type(e).__name__}: {str(e)}"
            )

    async def send_message(self, connection_uuid: str, message: Dict[str, Any]) -> bool:
        """发送消息到指定连接（业务层接口）"""
        return await self._send_raw_message(connection_uuid, message)

    async def broadcast_message(
        self, message: Dict[str, Any], filter_func: Optional[Callable] = None
    ) -> Dict[str, bool]:
        """广播消息到所有连接"""
        results = {}

        for connection_uuid in list(self.active_connections.keys()):
            if filter_func:
                metadata = self.connection_metadata.get(connection_uuid)
                if not filter_func(metadata):
                    continue

            success = await self._send_raw_message(connection_uuid, message)
            results[connection_uuid] = success

        return results

    def set_message_cache(self, message_cache: MessageCache) -> None:
        """设置消息缓存实例"""
        self.message_cache = message_cache
        self.logger.info(f"消息缓存已设置: enabled={message_cache.enabled}")

    async def disconnect_client(
        self, connection_uuid: str, reason: str = "Server initiated disconnect"
    ) -> bool:
        """主动断开客户端连接"""
        sid = self.active_connections.get(connection_uuid)
        if not sid:
            return False

        try:
            await self.sio.disconnect(sid)
            await self._cleanup_connection(connection_uuid)
            return True
        except Exception as e:
            self.logger.error(f"断开客户端 {connection_uuid} 时出错: {e}")
            return False

    def get_connection_count(self) -> int:
        """获取当前连接数"""
        return len(self.active_connections)

    def get_connection_list(self) -> Set[str]:
        """获取所有连接UUID"""
        return set(self.active_connections.keys())

    def get_connection_metadata(
        self, connection_uuid: str
    ) -> Optional[ConnectionMetadata]:
        """获取连接元数据"""
        return self.connection_metadata.get(connection_uuid)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.stats.copy()

    def _build_ssl_context(self):
        """构建 SSL 上下文"""
        if not self.ssl_enabled:
            return None

        import ssl

        if not self.ssl_certfile or not self.ssl_keyfile:
            raise ValueError("SSL 已启用但未提供证书文件")

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(self.ssl_certfile, self.ssl_keyfile)

        if self.ssl_ca_certs:
            ssl_context.load_verify_locations(self.ssl_ca_certs)

        if self.ssl_verify:
            ssl_context.verify_mode = ssl.CERT_REQUIRED

        return ssl_context

    async def start(self, event_queue: asyncio.Queue) -> None:
        """启动网络驱动器"""
        if self.running:
            self.logger.warning(f"网络驱动器已在 {self.host}:{self.port} 运行")
            return

        self.event_queue = event_queue
        self.running = True

        # 挂载 Socket.IO 到 aiohttp app
        self.sio.attach(self.app, socketio_path=self.path.lstrip("/"))

        self.logger.info(
            f"启动 Socket.IO 网络驱动器: {self.host}:{self.port}{self.path}"
        )

        # 构建 SSL 上下文
        ssl_context = self._build_ssl_context()

        # 启动 aiohttp server
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()

        if ssl_context:
            site = web.TCPSite(
                self._runner, self.host, self.port, ssl_context=ssl_context
            )
        else:
            site = web.TCPSite(self._runner, self.host, self.port)

        await site.start()

        self.logger.info(f"Socket.IO 服务器已启动: http://{self.host}:{self.port}")

        try:
            await asyncio.Event().wait()
        except Exception:
            self.logger.exception("Socket.IO 服务器启动失败")
            raise
        finally:
            if self._runner:
                await self._runner.cleanup()
            self._runner = None
            self.running = False

    async def stop(self) -> None:
        """停止网络驱动器"""
        if not self.running:
            return

        self.logger.info("停止网络驱动器...")
        self.running = False

        # 断开所有客户端
        for connection_uuid in list(self.active_connections.keys()):
            try:
                await self._cleanup_connection(connection_uuid)
            except Exception:
                pass

        # 清理状态
        self.active_connections.clear()
        self.sid_connections.clear()
        self.connection_metadata.clear()

        await self.cleanup_tasks()

        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception:
                self.logger.warning("停止 Socket.IO 服务器时出现异常")
            finally:
                self._runner = None

        # 重置统计
        self.stats = {
            "total_connections": 0,
            "current_connections": 0,
            "messages_received": 0,
            "messages_sent": 0,
            "bytes_received": 0,
            "bytes_sent": 0,
        }

        # 清理消息缓存
        if self.message_cache:
            await self.message_cache.stop()

        self.logger.info("网络驱动器已完全停止")

    async def cleanup_tasks(self) -> None:
        """清理后台任务（兼容性方法）"""
        pass

    async def process_message(self, data: Any) -> None:
        """处理消息（兼容性方法，由 Socket.IO 事件处理器调用）"""
        pass


# Socket.IO 驱动器别名（用于从旧名称迁移）
ServerSocketIODriver = ServerNetworkDriver
