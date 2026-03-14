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
async def test_message_exchange():
    """Test message send and receive between client and server"""
    server = WebSocketServer(host="localhost", port=18092)
    server_task = asyncio.create_task(server.start())

    for _ in range(20):
        await asyncio.sleep(0.5)
        if is_port_open("localhost", 18092):
            break

    received_messages = []

    async def handle_message(message):
        received_messages.append(message)

    server.process_message = handle_message

    client = WebSocketClient()
    await client.configure(url="http://localhost:18092", platform="test_platform")
    await client.connect()

    test_message = {"text": "hello", "type": "test"}
    await client.send_message("server", test_message)

    await asyncio.sleep(1)

    assert len(received_messages) > 0

    await client.stop()
    await server.stop()

    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass
