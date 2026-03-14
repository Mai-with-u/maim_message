import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from maim_message import Router, RouteConfig, TargetConfig


@pytest.mark.skip(reason="TCP mode not supported with Socket.IO implementation")
def test_tcp_client_creation():
    route_config = RouteConfig(
        route_config={
            "platform1": TargetConfig(
                url="tcp://127.0.0.1:18080",
                token="test_token_1",
                ssl_verify=None,
            ),
        }
    )
    router = Router(route_config)
    assert router is not None
