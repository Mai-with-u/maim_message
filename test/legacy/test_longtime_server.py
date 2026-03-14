import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from maim_message import MessageServer


def test_longtime_server_creation():
    server = MessageServer(host="localhost", port=18050, mode="ws")
    assert server.host == "localhost"
    assert server.port == 18050
