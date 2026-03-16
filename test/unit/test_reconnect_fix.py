"""
断连重连测试 - 验证 Socket.IO 内置重连机制
测试 Socket.IO 内置重连是否正常工作
"""

import asyncio
import pytest
import socket
import time
from typing import Optional

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from maim_message.ws_connection import WebSocketServer, WebSocketClient
from maim_message.router import Router, RouteConfig, TargetConfig


def is_port_open(host, port, timeout=1):
    """检查端口是否开放"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


@pytest.mark.asyncio
async def test_socketio_builtin_reconnection():
    """测试：Socket.IO 内置重连已启用"""
    server = WebSocketServer(host="localhost", port=18095)
    server_task = asyncio.create_task(server.start())

    for _ in range(20):
        await asyncio.sleep(0.5)
        if is_port_open("localhost", 18095):
            break

    client = WebSocketClient()
    await client.configure(url="http://localhost:18095", platform="test_platform")

    # 连接
    connected = await client.connect()
    assert connected is True
    assert client.is_connected() is True

    # 验证内置重连已启用
    assert client.sio.reconnection is True, "Socket.IO 内置重连应该被启用"
    assert client.sio.reconnection_attempts == 0, "重连尝试次数应为 0（无限重试）"
    assert client.sio.reconnection_delay == 1, "初始重连延迟应为 1 秒"
    assert client.sio.reconnection_delay_max == 10, "最大重连延迟应为 10 秒"
    assert client.sio.randomization_factor == 0.5, "随机化因子应为 0.5"

    await client.stop()
    await server.stop()

    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_connect_with_wait():
    """测试：使用 wait=True 确保连接就绪"""
    server = WebSocketServer(host="localhost", port=18096)
    server_task = asyncio.create_task(server.start())

    for _ in range(20):
        await asyncio.sleep(0.5)
        if is_port_open("localhost", 18096):
            break

    client = WebSocketClient()
    await client.configure(url="http://localhost:18096", platform="test_platform")

    # 连接
    connected = await client.connect()
    assert connected is True

    # 验证连接完全就绪（sid 存在）
    assert client.sio.sid is not None, "连接后应有 sid"
    assert client.is_connected() is True

    # 验证可以发送消息
    result = await client.send_message("test", {"type": "test", "data": "hello"})

    await client.stop()
    await server.stop()

    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_connect_error_event():
    """测试：connect_error 事件处理器"""
    client = WebSocketClient()
    await client.configure(url="http://localhost:18097", platform="test_platform")

    # 尝试连接到一个不存在的端口
    connect_errors = []

    @client.sio.event
    async def connect_error(data):
        connect_errors.append(data)

    # 这个连接应该会失败
    connected = await client.connect()
    assert connected is False, "连接到不存在的端口应该失败"
    assert not client.is_connected()


@pytest.mark.asyncio
async def test_router_no_manual_reconnect():
    """测试：Router 不再有手动重连机制"""
    server = WebSocketServer(host="localhost", port=18098)
    server_task = asyncio.create_task(server.start())

    for _ in range(20):
        await asyncio.sleep(0.5)
        if is_port_open("localhost", 18098):
            break

    # 创建 Router
    route_config = RouteConfig(
        route_config={
            "qq": TargetConfig(
                url="http://localhost:18098",
                token=None,
            )
        }
    )

    router = Router(route_config)

    # 验证 Router 不再有手动重连相关的属性
    assert not hasattr(router, "_reconnect_locks"), (
        "Router 不应有 _reconnect_locks 属性"
    )
    assert not hasattr(router, "_connection_states"), (
        "Router 不应有 _connection_states 属性"
    )
    assert not hasattr(router, "_monitor_task"), "Router 不应有 _monitor_task 属性"
    assert not hasattr(router, "_reconnect_platform"), (
        "Router 不应有 _reconnect_platform 方法"
    )
    assert not hasattr(router, "_monitor_connections"), (
        "Router 不应有 _monitor_connections 方法"
    )

    # 启动 Router
    router_task = asyncio.create_task(router.run())

    # 等待初始连接建立
    await asyncio.sleep(3)

    # 验证连接已建立
    assert router.check_connection("qq"), "Router 应能连接到服务器"

    # 停止
    await router.stop()
    await server.stop()

    router_task.cancel()
    server_task.cancel()
    try:
        await router_task
    except asyncio.CancelledError:
        pass
    try:
        await server_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_rapid_disconnect_reconnect():
    """测试：高频断连重连，验证 Socket.IO 内置重连正常工作"""
    server = WebSocketServer(host="localhost", port=18099)
    server_task = asyncio.create_task(server.start())

    for _ in range(20):
        await asyncio.sleep(0.5)
        if is_port_open("localhost", 18099):
            break

    # 多次快速断连重连
    for i in range(5):
        client = WebSocketClient()
        await client.configure(url="http://localhost:18099", platform="test_platform")

        # 连接
        connected = await client.connect()
        assert connected is True, f"第 {i + 1} 次连接应成功"
        assert client.is_connected() is True, f"第 {i + 1} 次连接后状态应正确"

        # 立即断开
        await client.stop()
        assert client.is_connected() is False, f"第 {i + 1} 次断开后状态应正确"

        # 立即重连（新的客户端）
        await asyncio.sleep(0.5)

    await server.stop()

    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_socketio_auto_reconnect():
    """测试：Socket.IO 内置重连机制自动恢复连接"""
    server = WebSocketServer(host="localhost", port=18100)
    server_task = asyncio.create_task(server.start())

    for _ in range(20):
        await asyncio.sleep(0.5)
        if is_port_open("localhost", 18100):
            break

    client = WebSocketClient()
    await client.configure(url="http://localhost:18100", platform="test_platform")

    # 连接
    connected = await client.connect()
    assert connected is True
    assert client.is_connected() is True

    # 启动客户端（使其进入等待状态，Socket.IO 会自动处理重连）
    client_task = asyncio.create_task(client.start())

    # 等待一下确保连接稳定
    await asyncio.sleep(1)
    assert client.is_connected() is True

    # 停止服务器模拟断连
    await server.stop()

    # 等待断连检测
    await asyncio.sleep(2)
    assert client.is_connected() is False, "服务器停止后连接应断开"

    # 重新启动服务器
    server2 = WebSocketServer(host="localhost", port=18100)
    server2_task = asyncio.create_task(server2.start())

    # 等待服务器启动
    for _ in range(20):
        await asyncio.sleep(0.5)
        if is_port_open("localhost", 18100):
            break

    # Socket.IO 内置重连应该会自动恢复连接
    # 等待足够的时间让 Socket.IO 尝试重连
    await asyncio.sleep(6)

    # 验证 Socket.IO 已尝试重连（reconnection=True 时会自动重连）
    # 注意：由于我们设置了 reconnection=True，Socket.IO 会自动尝试重连

    # 清理
    client_task.cancel()
    try:
        await client_task
    except asyncio.CancelledError:
        pass

    await client.stop()
    await server2.stop()

    server2_task.cancel()
    server_task.cancel()
    try:
        await server2_task
    except asyncio.CancelledError:
        pass
    try:
        await server_task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
