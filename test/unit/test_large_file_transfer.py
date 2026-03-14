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
async def test_large_file_transfer():
    """Test large file transfer (50MB+)"""
    server = WebSocketServer(host="localhost", port=18095, max_message_size=104_857_600)
    server_task = asyncio.create_task(server.start())

    for _ in range(20):
        await asyncio.sleep(0.5)
        if is_port_open("localhost", 18095):
            break

    received_data = []

    async def handle_message(message):
        received_data.append(message)

    server.process_message = handle_message

    client = WebSocketClient()
    client.max_message_size = 104_857_600
    await client.configure(
        url="http://localhost:18095",
        platform="test_platform",
        max_message_size=104_857_600,
    )
    await client.connect()

    large_data = "x" * (50 * 1024 * 1024)
    test_message = {"data": large_data, "size": len(large_data)}
    await client.send_message("server", test_message)

    await asyncio.sleep(3)

    assert len(received_data) > 0
    assert received_data[0].get("size") == 50 * 1024 * 1024

    await client.stop()
    await server.stop()

    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass
