import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from maim_message import MessageServer


@pytest.mark.skip(reason="TCP mode not supported with Socket.IO implementation")
def test_tcp_server_creation():
    server = MessageServer(host="localhost", port=18070, mode="tcp")
    assert server.mode == "tcp"
