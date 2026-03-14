"""测试与 MaiBot 的消息收发"""

import asyncio
import json
from datetime import datetime
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


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def construct_simple_text_message(platform: str, text: str = "你好，麦麦"):
    """构造简单的文本消息"""
    user_info = UserInfo(
        platform=platform,
        user_id="test_user_001",
        user_nickname="测试用户",
    )

    group_info = GroupInfo(
        platform=platform,
        group_id="test_group_001",
        group_name="测试群组",
    )

    format_info = FormatInfo(
        content_format=["text"],
        accept_format=["text", "image", "emoji"],
    )

    message_info = BaseMessageInfo(
        platform=platform,
        message_id="test_msg_001",
        time=int(datetime.now().timestamp()),
        group_info=group_info,
        user_info=user_info,
        format_info=format_info,
        additional_config={
            "at_bot": True,  # 强制标记为 @ 机器人
            "is_mentioned": 1.0,  # 提升回复概率
        },
    )

    message_segment = Seg("text", text)

    return MessageBase(
        message_info=message_info,
        message_segment=message_segment,
    )


received_messages = []


async def message_handler(message):
    """消息处理函数 - 记录收到的所有消息"""
    global received_messages
    log("收到消息!")
    try:
        if hasattr(message, "to_dict"):
            msg_dict = message.to_dict()
        elif isinstance(message, dict):
            msg_dict = message
        else:
            msg_dict = {"raw": str(message)}

        received_messages.append(msg_dict)
        log(json.dumps(msg_dict, ensure_ascii=False, indent=2)[:500])
    except Exception as e:
        log(f"解析消息失败: {e}")
        log(f"原始消息: {message}")


# 配置路由 - 连接 MaiBot Legacy Server (8000 端口)
route_config = RouteConfig(
    route_config={
        "test_platform": TargetConfig(
            url="ws://127.0.0.1:8000/ws",
            token=None,
        ),
    }
)

router = Router(route_config)


async def main():
    log("=" * 50)
    log("开始测试 maim_message 与 MaiBot 通信")
    log("=" * 50)

    # 注册消息处理器
    router.register_class_handler(message_handler)

    try:
        log("启动路由器...")
        router_task = asyncio.create_task(router.run())

        # 等待连接建立
        await asyncio.sleep(3)
        log("连接已建立")

        # 发送多条测试消息
        test_messages = [
            ("test_platform", "@麦麦 你好"),  # 明确 @ 麦麦
            ("test_platform", "@麦麦 今天天气怎么样？"),
        ]

        for platform, text in test_messages:
            log(f"发送消息: {text}")
            try:
                msg = construct_simple_text_message(platform, text)
                msg_dict = msg.to_dict()
                log(f"消息内容: {json.dumps(msg_dict, ensure_ascii=False)[:500]}")
                result = await router.send_message(msg)
                log(f"发送结果: {result}")
            except Exception as e:
                import traceback

                log(f"发送失败: {e}")
                traceback.print_exc()
            except Exception as e:
                log(f"发送失败: {e}")

            # 等待回复
            await asyncio.sleep(5)

        # 等待更多消息
        log("等待回复...")
        await asyncio.sleep(10)

        log(f"共收到 {len(received_messages)} 条消息")

    finally:
        log("正在关闭连接...")
        await router.stop()
        log("测试结束")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
