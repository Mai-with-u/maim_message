import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from maim_message import MessageServer, MessageClient


def test_message_server_send_method():
    server = MessageServer(host="localhost", port=18020, mode="ws")
    assert hasattr(server, "send_message")


def test_message_client_send_method():
    client = MessageClient(mode="ws")
    assert hasattr(client, "send_message")


def test_server_broadcast():
    server = MessageServer(host="localhost", port=18021, mode="ws")
    assert hasattr(server, "broadcast_message")


def test_client_is_connected():
    client = MessageClient(mode="ws")
    assert hasattr(client, "is_connected")
