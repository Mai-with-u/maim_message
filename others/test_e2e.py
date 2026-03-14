"""简化的端到端测试"""

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


def construct_message(platform):
    user_info = UserInfo(
        platform=platform,
        user_id="12348765",
        user_nickname="maimai",
        user_cardname="mai god",
    )
    group_info = GroupInfo(
        platform=platform,
        group_id="12345678",
        group_name="aaabbb",
    )
    format_info = FormatInfo(
        content_format=["text", "image", "emoji", "at", "reply", "voice"],
        accept_format=["text", "image", "emoji", "reply"],
    )
    message_info = BaseMessageInfo(
        platform=platform,
        message_id="12345678",
        time=1234567,
        group_info=group_info,
        user_info=user_info,
        format_info=format_info,
    )
    message_segment = Seg(
        "seglist",
        [
            Seg("text", "Hello, this is a test message"),
            Seg("voice", "audio_base64_data"),
            Seg("at", "123456789"),
        ],
    )
    return MessageBase(
        message_info=message_info,
        message_segment=message_segment,
        raw_message="test raw message",
    )


received_messages = []


async def message_handler(message):
    received_messages.append(message)
    print(f"\n收到回复消息:")
    print(f"   Platform: {message.get('message_info', {}).get('platform')}")
    seg = message.get("message_segment", {})
    print(f"   Segment type: {seg.get('type')}")
    if seg.get("type") == "seglist":
        for item in seg.get("data", []):
            data_str = str(item.get("data"))
            print(
                f"      - {item.get('type')}: {data_str[:50] if len(data_str) > 50 else data_str}"
            )


route_config = RouteConfig(
    route_config={
        "qq123": TargetConfig(
            url="ws://127.0.0.1:8090/ws",
            token=None,
        ),
    }
)

router = Router(route_config)


async def main():
    router.register_class_handler(message_handler)

    try:
        router_task = asyncio.create_task(router.run())
        await asyncio.sleep(2)

        print("=" * 50)
        print("测试 1: 发送消息")
        print("=" * 50)
        msg = construct_message("qq123")
        await router.send_message(msg)
        print(f"已发送消息到 qq123")

        await asyncio.sleep(2)

        print("\n" + "=" * 50)
        print("测试结果")
        print("=" * 50)
        print(f"收到消息数量: {len(received_messages)}")
        if received_messages:
            print("✅ 连接、解析、回复测试: 成功")
        else:
            print("❌ 警告: 未收到回复消息")

    finally:
        print("\n正在关闭连接...")
        await router.stop()
        print("测试完成")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
