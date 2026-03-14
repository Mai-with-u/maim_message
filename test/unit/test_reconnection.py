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
async def test_reconnection():
    """Test client reconnection after disconnect"""
    server = WebSocketServer(host="localhost", port=18094)
    server_task = asyncio.create_task(server.start())

    for _ in range(20):
        await asyncio.sleep(0.5)
        if is_port_open("localhost", 18094):
            break

    client = WebSocketClient()
    await client.configure(url="http://localhost:18094", platform="test_platform")

    connected1 = await client.connect()
    assert connected1 is True
    assert client.is_connected() is True

    await client.stop()
    assert client.is_connected() is False

    client2 = WebSocketClient()
    await client2.configure(url="http://localhost:18094", platform="test_platform")

    connected2 = await client2.connect()
    assert connected2 is True
    assert client2.is_connected() is True

    await client2.stop()
    await server.stop()

    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass
