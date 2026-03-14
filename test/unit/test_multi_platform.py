import asyncio
import pytest
import socket

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from maim_message.ws_connection import WebSocketServer, WebSocketClient


def is_port_open(host, port, timeout=1):
    """Check if a port is open"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


@pytest.mark.asyncio
async def test_multi_platform():
    """Test multi-platform support with multiple clients"""
    server = WebSocketServer(host="localhost", port=18093)
    server_task = asyncio.create_task(server.start())

    for _ in range(20):
        await asyncio.sleep(0.5)
        if is_port_open("localhost", 18093):
            break

    platforms = ["platform1", "platform2", "platform3"]
    clients = []

    for platform in platforms:
        client = WebSocketClient()
        await client.configure(url="http://localhost:18093", platform=platform)
        await client.connect()
        clients.append(client)

    await asyncio.sleep(1)

    for i, client in enumerate(clients):
        assert client.is_connected() is True
        assert client.platform == platforms[i]

    for client in clients:
        await client.stop()

    await server.stop()

    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass
