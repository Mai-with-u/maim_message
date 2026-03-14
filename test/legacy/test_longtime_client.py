import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from maim_message import Router, RouteConfig, TargetConfig


def test_longtime_client_creation():
    route_config = RouteConfig(
        route_config={
            "longtime-test": TargetConfig(
                url="ws://127.0.0.1:18060/ws",
                token=None,
            )
        }
    )
    router = Router(route_config)
    assert router is not None
