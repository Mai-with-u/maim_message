import asyncio
import pytest
import socket

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from maim_message.ws_connection import WebSocketServer


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
async def test_server_lifecycle():
    """Test server start and stop"""
    server = WebSocketServer(host="localhost", port=18090)

    server_task = asyncio.create_task(server.start())

    for _ in range(20):
        await asyncio.sleep(0.5)
        if is_port_open("localhost", 18090):
            break

    assert server._running is True

    await server.stop()
    assert server._running is False

    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass
