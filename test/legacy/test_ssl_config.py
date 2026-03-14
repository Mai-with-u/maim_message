import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from maim_message import MessageServer


def test_ssl_config_creation():
    server = MessageServer(
        host="localhost",
        port=18090,
        mode="ws",
        ssl_certfile="/path/to/server.crt",
        ssl_keyfile="/path/to/server.key",
    )
    assert server.host == "localhost"
    assert server.port == 18090


def test_ssl_config_with_ca():
    server = MessageServer(
        host="0.0.0.0",
        port=18091,
        mode="ws",
        ssl_certfile="/path/to/server.crt",
        ssl_keyfile="/path/to/server.key",
    )
    assert server.host == "0.0.0.0"
    assert server.port == 18091


def test_non_ssl_config():
    server = MessageServer(
        host="localhost",
        port=18092,
        mode="ws",
    )
    assert server.host == "localhost"
    assert server.port == 18092


def test_message_creation_with_ssl():
    from maim_message import BaseMessageInfo, Seg, MessageBase

    message_info = BaseMessageInfo(
        platform="ssl_test",
        message_id="ssl_msg_1",
        time=1234567,
    )
    message_segment = Seg("seglist", [Seg("text", "SSL test message")])
    message = MessageBase(
        message_info=message_info,
        message_segment=message_segment,
    )
    assert message.message_info.platform == "ssl_test"
