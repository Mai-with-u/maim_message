"""测试与 MaiBot 的消息收发 - 详细调试版"""

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


def construct_simple_text_message(platform: str, text: str = "你好"):
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
        accept_format=["text", "image", "emoji", "reply"],
    )

    message_info = BaseMessageInfo(
        platform=platform,
        message_id="test_msg_" + str(int(datetime.now().timestamp() * 1000)),
        time=int(datetime.now().timestamp()),
        group_info=group_info,
        user_info=user_info,
        format_info=format_info,
        additional_config={
            "at_bot": True,  # 强制标记为 @ 机器人
            "is_mentioned": 1.0,  # 提升回复概率到 100%
        },
    )

    message_segment = Seg("text", text)

    return MessageBase(
        message_info=message_info,
        message_segment=message_segment,
    )


received_messages = []
message_count = 0


async def message_handler(message):
    """消息处理函数 - 记录收到的所有消息"""
    global received_messages, message_count
    message_count += 1
    log(f"收到消息 #{message_count}!")
    try:
        if hasattr(message, "to_dict"):
            msg_dict = message.to_dict()
        elif isinstance(message, dict):
            msg_dict = message
        else:
            msg_dict = {"raw": str(message)}

        received_messages.append(msg_dict)

        # 提取消息文本
        if "message_segment" in msg_dict:
            seg = msg_dict["message_segment"]
            if isinstance(seg, dict) and "data" in seg:
                log(f"消息内容: {seg['data']}")

        log(json.dumps(msg_dict, ensure_ascii=False, indent=2)[:500])
    except Exception as e:
        log(f"解析消息失败: {e}")
        import traceback

        traceback.print_exc()


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
    global received_messages

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
        log(f"当前连接的平台: {list(router.clients.keys())}")

        # 检查连接状态
        for platform, client in router.clients.items():
            log(f"平台 {platform} 连接状态: {client.is_connected()}")

        # 发送多条测试消息
        test_messages = [
            ("test_platform", "@麦麦 你好，请问"),
            ("test_platform", "@麦麦 今天天气怎么样？"),
        ]

        for platform, text in test_messages:
            log(f"发送消息: {text}")
            try:
                msg = construct_simple_text_message(platform, text)
                msg_dict = msg.to_dict()
                log(f"消息 platform: {msg_dict['message_info']['platform']}")
                result = await router.send_message(msg)
                log(f"发送结果: {result}")
            except Exception as e:
                log(f"发送失败: {e}")
                import traceback

                traceback.print_exc()

            # 等待一段时间看是否有回复
            await asyncio.sleep(20)  # 增加等待时间

        # 额外等待
        log("继续等待回复...")
        await asyncio.sleep(30)

        log(f"共收到 {len(received_messages)} 条消息")
        if received_messages:
            for i, msg in enumerate(received_messages):
                log(f"消息 {i + 1}: {json.dumps(msg, ensure_ascii=False)[:200]}")

    finally:
        log("正在关闭连接...")
        await router.stop()
        log("测试结束")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
