"""Mock WebSocket 服务器 - 模拟 Napcat Adapter 行为

这个模块实现了一个简单的 WebSocket 服务器，用于测试 maim_message 和 MaiMBot 的连接。

主要功能：
- WebSocket 服务器（模拟 napcat adapter 监听来自 MaiBot 的连接）
- 支持自动发送 QQ 消息（message/notice/meta_event）
- 响应 API 调用（基于 echo 字段的请求-响应匹配）
- 可配置的消息生成策略
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

import websockets

try:
    from .config import MockConfig
    from .message_generator import MessageGenerator, MessageType
except ImportError:
    # 当作为脚本直接运行时使用绝对导入
    from config import MockConfig
    from message_generator import MessageGenerator, MessageType

# 简单的 logger 设置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("MockNapcatAdapter")


class MockNapcatServer:
    """Mock Napcat WebSocket 服务器

    AI agent 使用示例：
    >>> server = MockNapcatServer(config=MockConfig())
    >>> await server.start()  # 启动服务器
    >>> await server.stop()   # 停止服务器
    """

    def __init__(self, config: Optional[MockConfig] = None):
        """初始化 Mock 服务器

        Args:
            config: 配置对象，如果为 None 则使用默认配置
        """
        self.config = config or MockConfig()

        # 验证配置
        if not self.config.validate():
            raise ValueError("配置无效")

        # WebSocket 服务器实例
        self.server: Optional[websockets.WebSocketServer] = None
        self.running = False

        # 消息生成器
        self.message_generator = MessageGenerator(self.config)

        # API 响应池（模拟 Napcat 的响应池）
        self.response_pool: Dict[str, asyncio.Future] = {}

        # 连接统计
        self.stats = {
            "connections": 0,
            "messages_sent": 0,
            "messages_received": 0,
            "api_calls": 0,
        }

        # 当前连接（简化为单连接）
        self.current_connection: Optional[websockets.WebSocketServerProtocol] = None

    async def _handle_connection(
        self, websocket: websockets.WebSocketServerProtocol
    ) -> None:
        """处理 WebSocket 连接

        Args:
            websocket: WebSocket 连接对象
        """
        self.stats["connections"] += 1
        self.current_connection = websocket

        client_info = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"🔗 客户端连接: {client_info}")

        try:
            # 发送生命周期事件（模拟 Napcat）
            await self._send_meta_event(websocket, "connect")

            # 如果启用自动发送，启动消息发送任务
            sender_task = None
            if self.config.auto_send:
                sender_task = asyncio.create_task(self._auto_send_messages(websocket))

            # 接收和处理消息
            async for raw_message in websocket:
                await self._handle_message(websocket, raw_message)

        except websockets.ConnectionClosed:
            logger.info(f"🔌 客户端断开: {client_info}")
        except Exception as e:
            logger.error(f"❌ 处理连接时出错: {e}", exc_info=True)
        finally:
            # 取消发送任务
            if sender_task and not sender_task.done():
                sender_task.cancel()
                try:
                    await sender_task
                except asyncio.CancelledError:
                    pass

            self.current_connection = None

    async def _handle_message(
        self, websocket: websockets.WebSocketServerProtocol, raw_message: str
    ) -> None:
        """处理接收到的消息

        Args:
            websocket: WebSocket 连接对象
            raw_message: 原始消息字符串
        """
        self.stats["messages_received"] += 1

        try:
            message = json.loads(raw_message)
            logger.debug(
                f"📥 收到消息: {json.dumps(message, ensure_ascii=False)[:200]}"
            )

            # 检查是否是 API 调用（包含 action 字段）
            if "action" in message:
                await self._handle_api_call(websocket, message)
            else:
                logger.debug(f"📝 收到非 API 消息: {message.get('type', 'unknown')}")

        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON 解析失败: {e}")
        except Exception as e:
            logger.error(f"❌ 处理消息时出错: {e}", exc_info=True)

    async def _handle_api_call(
        self, websocket: websockets.WebSocketServerProtocol, message: Dict[str, Any]
    ) -> None:
        """处理 API 调用

        Args:
            websocket: WebSocket 连接对象
            message: API 调用消息
        """
        action = message.get("action")
        params = message.get("params", {})
        echo = message.get("echo")

        self.stats["api_calls"] += 1
        logger.info(f"🔧 API 调用: {action} (echo={echo})")

        # 模拟 API 响应
        response = self._create_api_response(action, params, echo)

        try:
            await websocket.send(json.dumps(response, ensure_ascii=False))
            logger.debug(f"📤 发送响应: {echo}")
        except Exception as e:
            logger.error(f"❌ 发送响应失败: {e}")

    def _create_api_response(
        self, action: str, params: Dict[str, Any], echo: Any
    ) -> Dict[str, Any]:
        """创建 API 响应

        Args:
            action: API 动作名称
            params: API 参数
            echo: 响应标识符

        Returns:
            API 响应字典
        """
        # 基础响应结构
        response = {
            "status": "ok",
            "retcode": 0,
            "data": {},
            "echo": echo,
            "msg": "",
        }

        # 根据不同的 action 返回模拟数据
        if action == "get_login_info":
            response["data"] = {
                "user_id": self.config.self_id,
                "nickname": "MockBot",
            }
        elif action == "send_group_msg":
            response["data"] = {
                "message_id": int(time.time() * 1000),
            }
        elif action == "send_private_msg":
            response["data"] = {
                "message_id": int(time.time() * 1000),
            }
        elif action == "get_group_info":
            response["data"] = {
                "group_id": params.get("group_id", self.config.group_id),
                "group_name": "Mock Group",
                "member_count": 100,
            }
        elif action == "get_group_member_list":
            response["data"] = [
                {"user_id": 1111111111, "nickname": "User1"},
                {"user_id": 2222222222, "nickname": "User2"},
            ]
        elif action == "get_friend_list":
            response["data"] = [
                {"user_id": 3333333333, "nickname": "Friend1"},
                {"user_id": 4444444444, "nickname": "Friend2"},
            ]
        else:
            # 未知 API 调用，返回成功响应
            response["data"] = {"success": True}

        return response

    async def _auto_send_messages(
        self, websocket: websockets.WebSocketServerProtocol
    ) -> None:
        """自动发送测试消息

        Args:
            websocket: WebSocket 连接对象
        """
        count = 0
        max_count = self.config.message_count

        while self.running and count < max_count:
            try:
                # 生成并发送消息
                message = self.message_generator.generate_message()
                await websocket.send(json.dumps(message, ensure_ascii=False))

                self.stats["messages_sent"] += 1
                count += 1

                logger.info(
                    f"📤 发送消息 [{count}/{max_count}]: {message['post_type']}"
                )

                # 延迟
                if self.config.random_delay:
                    import random

                    delay = self.config.message_delay * random.uniform(0.5, 1.5)
                else:
                    delay = self.config.message_delay

                await asyncio.sleep(delay)

            except asyncio.CancelledError:
                logger.info("⏸️  消息发送任务已取消")
                break
            except Exception as e:
                logger.error(f"❌ 发送消息时出错: {e}", exc_info=True)
                break

        logger.info(f"✅ 消息发送完成，总共发送 {count} 条消息")

    async def _send_meta_event(
        self, websocket: websockets.WebSocketServerProtocol, event_type: str
    ) -> None:
        """发送元事件

        Args:
            websocket: WebSocket 连接对象
            event_type: 事件类型
        """
        meta_event = {
            "post_type": "meta_event",
            "meta_event_type": event_type,
            "time": int(time.time()),
        }

        try:
            await websocket.send(json.dumps(meta_event, ensure_ascii=False))
            logger.debug(f"📤 发送元事件: {event_type}")
        except Exception as e:
            logger.error(f"❌ 发送元事件失败: {e}")

    async def start(self) -> None:
        """启动 Mock 服务器"""
        if self.running:
            logger.warning("⚠️  服务器已经在运行")
            return

        self.running = True

        # 启动 WebSocket 服务器
        self.server = await websockets.serve(
            self._handle_connection,
            self.config.host,
            self.config.port,
            max_size=2**26,  # 64MB
            logger=None,
        )

        logger.info(
            f"✅ Mock Napcat Adapter 启动成功!"
            f" 监听: ws://{self.config.host}:{self.config.port}"
        )
        logger.info(f"📋 配置: {self.config}")

    async def stop(self) -> None:
        """停止 Mock 服务器"""
        if not self.running:
            return

        logger.info("🛑 正在停止 Mock Napcat Adapter...")
        self.running = False

        # 关闭 WebSocket 服务器
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

        logger.info("✅ Mock Napcat Adapter 已停止")

    async def send_custom_message(self, message: Dict[str, Any]) -> None:
        """发送自定义消息（外部调用接口）

        Args:
            message: 要发送的消息字典
        """
        if not self.current_connection:
            logger.warning("⚠️  没有活跃的连接，无法发送消息")
            return

        try:
            await self.current_connection.send(json.dumps(message, ensure_ascii=False))
            self.stats["messages_sent"] += 1
            logger.info(f"📤 发送自定义消息: {message.get('post_type', 'unknown')}")
        except Exception as e:
            logger.error(f"❌ 发送自定义消息失败: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息

        Returns:
            统计信息字典
        """
        return {
            **self.stats,
            "running": self.running,
            "connected": self.current_connection is not None,
        }
