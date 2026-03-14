import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from maim_message import (
    BaseMessageInfo,
    UserInfo,
    GroupInfo,
    FormatInfo,
    TemplateInfo,
    MessageBase,
    Seg,
    Router,
    RouteConfig,
    TargetConfig,
)


def test_router_creation():
    route_config = RouteConfig(
        route_config={
            "qq123": TargetConfig(
                url="ws://127.0.0.1:18010/ws",
                token=None,
            ),
        }
    )
    router = Router(route_config)
    assert router is not None


def test_router_multiple_platforms():
    route_config = RouteConfig(
        route_config={
            "qq123": TargetConfig(
                url="ws://127.0.0.1:18011/ws",
                token=None,
            ),
            "qq321": TargetConfig(
                url="ws://127.0.0.1:18011/ws",
                token=None,
            ),
        }
    )
    router = Router(route_config)
    assert router is not None


def test_message_construction():
    user_info = UserInfo(
        platform="test_platform",
        user_id="12348765",
        user_nickname="maimai",
        user_cardname="mai god",
    )

    group_info = GroupInfo(
        platform="test_platform",
        group_id="12345678",
        group_name="aaabbb",
    )

    message_info = BaseMessageInfo(
        platform="test_platform",
        message_id="12345678",
        time=1234567,
        group_info=group_info,
        user_info=user_info,
    )

    message_segment = Seg(
        "seglist",
        [
            Seg("text", "test message"),
        ],
    )

    message = MessageBase(
        message_info=message_info,
        message_segment=message_segment,
    )
    assert message.message_info.platform == "test_platform"
