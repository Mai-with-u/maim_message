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
async def test_token_authentication():
    """Test token authentication - both valid and invalid tokens"""
    server = WebSocketServer(host="localhost", port=18096, enable_token=True)
    server.add_valid_token("valid_token_123")

    server_task = asyncio.create_task(server.start())

    for _ in range(20):
        await asyncio.sleep(0.5)
        if is_port_open("localhost", 18096):
            break

    client_valid = WebSocketClient()
    await client_valid.configure(
        url="http://localhost:18096", platform="test_platform", token="valid_token_123"
    )
    connected_valid = await client_valid.connect()
    assert connected_valid is True
    assert client_valid.is_connected() is True

    await client_valid.stop()

    client_invalid = WebSocketClient()
    await client_invalid.configure(
        url="http://localhost:18096", platform="test_platform", token="invalid_token"
    )
    connected_invalid = await client_invalid.connect()
    assert connected_invalid is False

    await server.stop()

    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass
