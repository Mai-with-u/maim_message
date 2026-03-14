import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from maim_message import MessageServer


@pytest.mark.skip(reason="SSL with Socket.IO requires special configuration")
def test_ssl_websocket():
    pass
