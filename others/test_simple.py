import asyncio
from maim_message import (
    BaseMessageInfo,
    UserInfo,
    GroupInfo,
    FormatInfo,
    MessageBase,
    Seg,
    Router,
    RouteConfig,
    TargetConfig,
)


received_messages = []


async def message_handler(message):
    received_messages.append(message)
    print(f"收到消息: {message}")
    await router.stop()


if __name__ == "__main__":
    print("发送简单测试消息并查看回复")
    await asyncio.sleep(8)
    print(f"Received {len(received_messages)} messages, len(received_messages))
    for msg in received_messages:
                print(f"  - {msg}")
