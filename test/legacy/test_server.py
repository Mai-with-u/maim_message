import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from maim_message import MessageServer, MessageClient


def test_message_server_creation():
    server = MessageServer(host="localhost", port=18000, mode="ws")
    assert server.host == "localhost"
    assert server.port == 18000
    assert server.mode == "ws"


def test_message_client_creation():
    client = MessageClient(mode="ws")
    assert client.mode == "ws"


def test_message_server_token():
    server = MessageServer(host="localhost", port=18001, mode="ws", enable_token=True)
    server.add_valid_token("test_token")
    assert "test_token" in server.connection.valid_tokens


def test_message_server_broadcast():
    server = MessageServer(host="localhost", port=18002, mode="ws")
    assert hasattr(server, "broadcast_message")
