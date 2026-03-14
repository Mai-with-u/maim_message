"""WebSocket 通信模块，提供服务器和客户端实现。"""

from __future__ import annotations

import asyncio
import os
import ssl
from typing import Any, Dict, Optional, Set

import socketio
import aiohttp
from aiohttp import web
import uvicorn

from .connection_interface import (
    BaseConnection,
    ClientConnectionInterface,
    ServerConnectionInterface,
)
from .log_utils import configure_uvicorn_logging, get_logger, get_uvicorn_log_config

logger = get_logger()

_CONNECTION_ERROR_KEYWORDS = (
    "1000",
    "1001",
    "1006",
    "1011",
    "1012",
    "closed",
    "disconnect",
    "reset",
    "timeout",
    "broken pipe",
    "connection",
)


def _looks_like_connection_error(exc: BaseException) -> bool:
    """判断异常是否属于常见的连接断开场景。"""

    try:
        message = str(exc).lower()
    except Exception:  # pragma: no cover - 极少数情况下 str(exc) 失败
        return False
    return any(keyword in message for keyword in _CONNECTION_ERROR_KEYWORDS)


class WebSocketServer(BaseConnection, ServerConnectionInterface):
    """基于 Socket.IO 的服务器实现。"""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 18000,
        path: str = "/ws",
        app: Optional[web.Application] = None,
        *,
        ssl_certfile: Optional[str] = None,
        ssl_keyfile: Optional[str] = None,
        enable_token: bool = False,
        enable_custom_uvicorn_logger: bool = False,
        max_message_size: int = 104_857_600,
        heartbeat_interval: float = 30.0,
        heartbeat_timeout: float = 10.0,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.path = path
        self.app = app or web.Application()
        self.own_app = app is None
        self.ssl_certfile = ssl_certfile
        self.ssl_keyfile = ssl_keyfile
        self.enable_custom_uvicorn_logger = enable_custom_uvicorn_logger
        self.max_message_size = max_message_size
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout

        self.enable_token = enable_token
        self.valid_tokens: Set[str] = set()

        # Socket.IO server
        self.sio = socketio.AsyncServer(
            async_mode="aiohttp",
            ping_interval=25,
            ping_timeout=5,
            cors_allowed_origins="*",
            max_http_buffer_size=max_message_size,
        )

        # Connection management: platform <-> sid mapping
        self.platform_sids: Dict[str, str] = {}  # platform -> sid
        self.sid_platforms: Dict[str, str] = {}  # sid -> platform

        self.server: Optional[uvicorn.Server] = None

        self._setup_socketio_handlers()

        # If using external app, mount Socket.IO
        if not self.own_app:
            self.sio.attach(self.app, socketio_path=self.path.lstrip("/"))

    # ------------------------------------------------------------------
    # Socket.IO 事件处理
    # ------------------------------------------------------------------
    def _setup_socketio_handlers(self) -> None:
        @self.sio.event
        async def connect(sid: str, environ: dict) -> None:
            # Extract platform from HTTP headers
            platform = environ.get("HTTP_PLATFORM", "unknown")

            # Token validation
            if self.enable_token:
                auth_header = environ.get("HTTP_AUTHORIZATION")
                if not auth_header or not await self.verify_token(auth_header):
                    logger.warning(f"拒绝平台 {platform} 的连接请求: 令牌无效")
                    raise socketio.exceptions.ConnectionRefusedError("无效的令牌")  # type: ignore[attr-defined]

            # Register connection
            self.sid_platforms[sid] = platform
            self.platform_sids[platform] = sid

            # Handle duplicate connections from same platform
            if platform != "unknown":
                logger.info(f"平台 {platform} Socket.IO 已连接 (sid={sid})")
            else:
                logger.info(f"新的 Socket.IO 连接已建立 (sid={sid})")

        @self.sio.event
        async def disconnect(sid: str) -> None:
            platform = self.sid_platforms.pop(sid, None)
            if platform:
                if self.platform_sids.get(platform) == sid:
                    del self.platform_sids[platform]
                logger.info(f"平台 {platform} Socket.IO 已断开 (sid={sid})")
            else:
                logger.info(f"Socket.IO 连接已断开 (sid={sid})")

        @self.sio.on("message")  # type: ignore[union-attr]
        async def handle_message(sid: str, data: Any) -> None:
            platform = self.sid_platforms.get(sid, "unknown")

            # Add metadata to message
            if isinstance(data, dict):
                data["_platform"] = platform
                data["_sid"] = sid
            elif data is None:
                data = {"_platform": platform, "_sid": sid}

            task = asyncio.create_task(self.process_message(data))
            self.add_background_task(task)

    # ------------------------------------------------------------------
    # 安全与配置信息
    # ------------------------------------------------------------------
    async def verify_token(self, token: str) -> bool:
        if not self.enable_token:
            return True
        return token in self.valid_tokens

    def add_valid_token(self, token: str) -> None:
        self.valid_tokens.add(token)

    def remove_valid_token(self, token: str) -> None:
        self.valid_tokens.discard(token)

    def _validate_ssl_files(self) -> None:
        if self.ssl_certfile and not os.path.exists(self.ssl_certfile):
            logger.error(f"SSL 证书文件不存在: {self.ssl_certfile}")
            raise FileNotFoundError(f"SSL 证书文件不存在: {self.ssl_certfile}")
        if self.ssl_keyfile and not os.path.exists(self.ssl_keyfile):
            logger.error(f"SSL 密钥文件不存在: {self.ssl_keyfile}")
            raise FileNotFoundError(f"SSL 密钥文件不存在: {self.ssl_keyfile}")
        if self.ssl_certfile and self.ssl_keyfile:
            logger.info(
                f"启用 SSL 证书: certfile={self.ssl_certfile}, keyfile={self.ssl_keyfile}"
            )

    def _build_ssl_context(self) -> Optional[ssl.SSLContext]:
        """Build SSL context for aiohttp."""
        if not self.ssl_certfile or not self.ssl_keyfile:
            return None

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(self.ssl_certfile, self.ssl_keyfile)
        return ssl_context

    def _build_uvicorn_config(self) -> uvicorn.Config:
        ssl_context = self._build_ssl_context()

        config_kwargs = {
            "host": self.host,
            "port": self.port,
        }

        if ssl_context is not None:
            config_kwargs["ssl"] = ssl_context

        if self.enable_custom_uvicorn_logger:
            config_kwargs["log_config"] = get_uvicorn_log_config()
            configure_uvicorn_logging()

        return uvicorn.Config(self.app, **config_kwargs)

    # ------------------------------------------------------------------
    # 生命周期控制
    # ------------------------------------------------------------------
    async def start(self) -> None:
        global logger  # noqa: PLW0603 - 保持 log_utils 中的单例
        logger = get_logger()

        self._running = True

        if not self.own_app:
            logger.info("Socket.IO 服务已挂载至外部 aiohttp 应用，仅注册路由")
            return

        self._validate_ssl_files()

        # For own app, we need to attach the socketio server
        self.sio.attach(self.app, socketio_path=self.path.lstrip("/"))

        ssl_context = self._build_ssl_context()
        from aiohttp import web

        self._runner = web.AppRunner(self.app)
        await self._runner.setup()

        if ssl_context:
            site = web.TCPSite(
                self._runner, self.host, self.port, ssl_context=ssl_context
            )
        else:
            site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

        logger.info(f"Socket.IO 服务器已启动: http://{self.host}:{self.port}")

        try:
            await asyncio.Event().wait()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Socket.IO 服务器启动失败")
            raise
        finally:
            if self._runner:
                await self._runner.cleanup()
            self._runner = None
            self._running = False

    def run_sync(self) -> None:
        global logger  # noqa: PLW0603 - 保持 log_utils 中的单例
        logger = get_logger()

        self._running = True

        if not self.own_app:
            logger.info("Socket.IO 服务已挂载至外部 aiohttp 应用，仅注册路由")
            return

        self._validate_ssl_files()

        # For own app, we need to attach the socketio server
        self.sio.attach(self.app, socketio_path=self.path.lstrip("/"))

        config = self._build_uvicorn_config()
        server = uvicorn.Server(config)

        try:
            server.run()
        except Exception:  # pylint: disable=broad-except
            logger.exception("Socket.IO 服务器运行失败")
            raise
        finally:
            self._running = False

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False

        # Disconnect all clients
        for sid in list(self.sid_platforms.keys()):
            try:
                await self.sio.disconnect(sid)
            except Exception:
                logger.debug(f"断开客户端 {sid} 时出现异常")

        # Clear connection mappings
        self.sid_platforms.clear()
        self.platform_sids.clear()

        await self.cleanup_tasks()

        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception:
                logger.warning("停止 Socket.IO 服务器时出现异常", exc_info=True)
            finally:
                self._runner = None

        if self.server is not None:
            try:
                if hasattr(self.server, "should_exit"):
                    self.server.should_exit = True
                if hasattr(self.server, "force_exit"):
                    self.server.force_exit = True
                if hasattr(self.server, "shutdown"):
                    await self.server.shutdown()
            except Exception:
                logger.warning("停止 Socket.IO 服务器时出现异常", exc_info=True)
            finally:
                self.server = None

    # ------------------------------------------------------------------
    # 消息发送与广播
    # ------------------------------------------------------------------
    async def broadcast_message(self, message: Dict[str, Any]) -> None:
        try:
            await self.sio.emit("message", message)
            logger.debug(f"广播消息成功，接收者: 所有已连接客户端")
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(f"广播消息失败: {exc}")

    async def send_message(self, target: str, message: Dict[str, Any]) -> bool:
        logger.debug(
            f"准备向平台 {target} 发送消息，当前映射平台: {list(self.platform_sids.keys())}"
        )

        sid = self.platform_sids.get(target)
        if not sid:
            logger.warning(f"未找到目标平台: {target}")
            return False

        try:
            await self.sio.emit("message", message, room=sid)
            logger.debug(f"向平台 {target} 发送消息成功 (sid={sid})")
            return True
        except Exception as exc:  # pylint: disable=broad-except
            if _looks_like_connection_error(exc):
                logger.debug(f"平台 {target} 连接异常: {exc}")
            else:
                logger.exception(f"发送消息到平台 {target} 失败")

            # Clean up stale mapping
            if target in self.platform_sids:
                del self.platform_sids[target]
            for s, p in list(self.sid_platforms.items()):
                if p == target:
                    del self.sid_platforms[s]
                    break

            return False


class WebSocketClient(BaseConnection, ClientConnectionInterface):
    """基于 Socket.IO 的客户端实现。"""

    def __init__(self) -> None:
        super().__init__()
        self.url: Optional[str] = None
        self.platform: Optional[str] = None
        self.token: Optional[str] = None
        self.ssl_verify: Optional[str] = None
        self.headers: Dict[str, str] = {}
        self.max_message_size: int = 104_857_600

        # aiohttp session for SSL connections
        self.http_session: Optional[aiohttp.ClientSession] = None

        # Socket.IO client
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,  # infinite
            reconnection_delay=1,
            reconnection_delay_max=5,
            http_session=None,  # Will be set in configure() when SSL is needed
        )

        self._connected = False

        self._setup_handlers()

    # ------------------------------------------------------------------
    # Socket.IO 事件处理
    # ------------------------------------------------------------------
    def _setup_handlers(self) -> None:
        @self.sio.event
        async def connect() -> None:
            self._connected = True
            logger.info(f"已连接到服务器")

        @self.sio.event
        async def disconnect() -> None:
            self._connected = False
            logger.info(f"与服务器断开连接")

        @self.sio.on("message")  # type: ignore[union-attr]
        async def on_message(data: Any) -> None:
            task = asyncio.create_task(self.process_message(data))
            self.add_background_task(task)

    # ------------------------------------------------------------------
    # 配置与连接管理
    # ------------------------------------------------------------------
    async def configure(
        self,
        url: str,
        platform: str,
        *,
        token: Optional[str] = None,
        ssl_verify: Optional[str] = None,
        max_message_size: Optional[int] = None,
        heartbeat_interval: Optional[int] = None,
    ) -> None:
        # Transform URL: ws:// -> http://, wss:// -> https://
        self.url = url.replace("ws://", "http://").replace("wss://", "https://")

        # Remove path suffix for socketio.connect() - it will append the path
        # Socket.IO uses query params for the path, not URL path
        # Keep the path but transform protocol

        self.platform = platform
        self.token = token
        self.ssl_verify = ssl_verify

        if max_message_size is not None:
            self.max_message_size = max_message_size
        # Note: heartbeat is handled by Socket.IO internally (ping_interval/ping_timeout)

        self.headers = {"platform": platform}
        if token:
            self.headers["Authorization"] = str(token)

        # Create http_session for SSL connections
        if self.ssl_verify and self.url.startswith("https://"):
            logger.info(f"使用证书验证: {self.ssl_verify}")
            ssl_context = ssl.create_default_context()
            ssl_context.load_verify_locations(self.ssl_verify)
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self.http_session = aiohttp.ClientSession(connector=connector)
            # Reinitialize sio with http_session
            self.sio = socketio.AsyncClient(
                reconnection=True,
                reconnection_attempts=0,
                reconnection_delay=1,
                reconnection_delay_max=5,
                http_session=self.http_session,
            )
        elif self.url.startswith("https://"):
            logger.warning("未提供证书验证，当前连接将跳过 SSL 校验")
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self.http_session = aiohttp.ClientSession(connector=connector)
            self.sio = socketio.AsyncClient(
                reconnection=True,
                reconnection_attempts=0,
                reconnection_delay=1,
                reconnection_delay_max=5,
                http_session=self.http_session,
            )

    async def connect(self) -> bool:
        global logger  # noqa: PLW0603 - 保持 log_utils 中的单例
        logger = get_logger()

        if not self.url or not self.platform:
            raise ValueError("连接前必须先调用 configure 方法配置连接参数")

        options: Dict[str, Any] = {
            "headers": self.headers,
        }

        # http_session is now set in configure() method when SSL is needed
        # The sio client already has http_session configured

        try:
            # Extract path from URL for Socket.IO
            from urllib.parse import urlparse

            parsed = urlparse(self.url)
            path = parsed.path if parsed.path else "/ws"

            logger.info(f"正在连接到 {self.url} (path={path})")
            await self.sio.connect(self.url, socketio_path=path.lstrip("/"), **options)

            self._connected = True
            logger.info(f"已成功连接到 {self.url}")
            return True

        except Exception as exc:  # pylint: disable=broad-except
            logger.error(f"连接错误: {exc}")

        self._connected = False
        return False

    async def _cleanup_connection(self) -> None:
        try:
            if self.sio.connected:
                await self.sio.disconnect()
        except Exception:
            logger.debug("关闭 Socket.IO 连接时出现异常", exc_info=True)
        finally:
            self._connected = False

    # ------------------------------------------------------------------
    # 生命周期控制
    # ------------------------------------------------------------------
    async def start(self) -> None:
        global logger  # noqa: PLW0603 - 保持 log_utils 中的单例
        logger = get_logger()

        self._running = True

        if not self._connected:
            success = await self.connect()
            if not success:
                logger.warning("初始连接失败，将在后台重试")

        # Note: Socket.IO client handles reconnection automatically
        # The client event loop is managed by the sio object

        # Wait for disconnection or errors
        try:
            # The wait() method blocks until disconnection
            await self.sio.wait()
        except asyncio.CancelledError:
            logger.debug("Socket.IO 客户端任务被取消")
        except Exception as exc:  # pylint: disable=broad-except
            if _looks_like_connection_error(exc):
                logger.debug(f"Socket.IO 连接关闭: {exc}")
            else:
                logger.exception("Socket.IO 连接发生错误")

        self._running = False

    async def stop(self) -> None:
        logger.info("正在停止 Socket.IO 客户端...")
        self._running = False

        try:
            if self.sio.connected:
                await self.sio.disconnect()
                logger.debug("Socket.IO 连接已关闭")
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(f"关闭 Socket.IO 时出现异常: {exc}")

        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
            logger.debug("aiohttp session 已关闭")

        await self.cleanup_tasks()

        self._connected = False
        logger.info("Socket.IO 客户端已停止")

    async def send_message(self, target: str, message: Dict[str, Any]) -> bool:
        if not self.is_connected():
            logger.warning("Socket.IO 未连接，无法发送消息")
            return False

        try:
            # Emit to server - target is ignored for client (server knows who we are)
            await self.sio.emit("message", message)
            return True
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(f"发送消息失败: {exc}")

        self._connected = False
        return False

    def is_connected(self) -> bool:
        return self._connected and self.sio.connected

    async def ping(self) -> bool:
        if not self.is_connected():
            return False

        try:
            # Socket.IO handles ping/pong internally
            # We can use the manager to check connection state
            return self.sio.connected
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(f"Ping 失败: {exc}")
            self._connected = False
            return False

    async def reconnect(self) -> bool:
        logger.info("尝试重新连接 Socket.IO...")
        await self._cleanup_connection()
        return await self.connect()
