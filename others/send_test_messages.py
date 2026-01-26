#!/usr/bin/env python3
"""发送测试消息到 Mock Napcat Adapter"""

import asyncio
import json
import websockets
from pathlib import Path

# 添加 mock_napcat_adapter 到路径
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "mock_napcat_adapter"))

from config import MockConfig

# 测试消息配置
TEST_MESSAGES = [
    # 1. meta_event - 心跳
    {
        "time": 1706000000,
        "self_id": 123456789,
        "post_type": "meta_event",
        "meta_event_type": "heartbeat",
        "interval": 5000,
        "status": {"online": True, "good": True},
    },
    # 2. notice - 群成员增加
    {
        "time": 1706000001,
        "self_id": 123456789,
        "post_type": "notice",
        "notice_type": "group_increase",
        "group_id": 987654321,
        "user_id": 111222333,
        "operator_id": 123456789,
        "sub_type": "approve",
    },
    # 3. message - 群消息
    {
        "time": 1706000002,
        "self_id": 123456789,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": 1,
        "group_id": 987654321,
        "user_id": 111222333,
        "sender": {
            "user_id": 111222333,
            "nickname": "测试用户",
            "card": "",
            "sex": "unknown",
            "age": 0,
            "area": "",
            "level": "",
            "role": "member",
            "title": "",
        },
        "message": [{"type": "text", "data": {"text": "小千你好，这是一条测试消息"}}],
        "raw_message": "小千你好，这是一条测试消息",
        "font": 0,
        "sender": {
            "user_id": 111222333,
            "nickname": "测试用户",
            "card": "",
            "sex": "unknown",
            "age": 0,
            "area": "",
            "level": "",
            "role": "member",
            "title": "",
        },
        "message_id": 1,
        "time": 1706000002,
    },
    # 4. message - 私聊消息
    {
        "time": 1706000003,
        "self_id": 123456789,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": 2,
        "user_id": 444555666,
        "message": [{"type": "text", "data": {"text": "测试私聊消息"}}],
        "raw_message": "测试私聊消息",
        "font": 0,
        "sender": {
            "user_id": 444555666,
            "nickname": "私聊用户",
            "sex": "unknown",
            "age": 0,
        },
        "time": 1706000003,
    },
]


async def send_test_messages():
    """发送测试消息到 Mock Adapter"""
    config = MockConfig()
    uri = f"ws://{config.host}:{config.port}"

    print(f"📡 连接到 Mock Adapter: {uri}")

    try:
        async with websockets.connect(uri) as websocket:
            print(f"✅ 连接成功")

            # 发送测试消息
            for i, msg in enumerate(TEST_MESSAGES, 1):
                print(f"\n📤 发送消息 {i}/{len(TEST_MESSAGES)}: {msg['post_type']}")
                print(f"   内容: {json.dumps(msg, ensure_ascii=False, indent=2)}")

                await websocket.send(json.dumps(msg))
                print(f"   ✅ 消息已发送")

                # 等待一段时间再发送下一条
                await asyncio.sleep(1)

            # 等待一段时间让消息处理完成
            print(f"\n⏳ 等待消息处理...")
            await asyncio.sleep(5)

            print(f"\n✅ 所有测试消息已发送完成")

    except Exception as e:
        print(f"❌ 错误: {e}")


if __name__ == "__main__":
    asyncio.run(send_test_messages())
