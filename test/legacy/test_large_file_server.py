import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from maim_message import MessageServer


def test_large_file_server_creation():
    server = MessageServer(host="localhost", port=18030, mode="ws")
    assert server.host == "localhost"
    assert server.port == 18030
