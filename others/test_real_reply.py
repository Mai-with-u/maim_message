import asyncio
import time
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

import os


sys.path.insert(0, os.path.dirname(__file__))


received_messages = []


async def message_handler(message):
    """收到 MaiBot 的回复消息"""
    print(f"\n=== 收到回复 ===")
    print(f"Platform: {message.get('message_info', {}).get('platform')}")
    seg = message.get('message_segment', {})
    print(f"Segment type: {seg.get('type')}")
    if seg.get('type') == 'seglist':
        for item in seg.get('data', []):
            print(f"  - [{item.get('type')}]: {item.get('data')[:50] if isinstance(item.get('data'), str) else str(item.get('data')}")
    else:
        print(f"  - {seg.get('type')}: {seg.get('data')}")
    print(f"Raw message: {message.get('raw_message')}")
    print(f"完整消息: {message}")
    received_messages.append(message)


    await router.stop()


    await router.send_message(msg)


    print(f"\n消息已发送到 qq123， time={time.time()}")
    print(f"等待回复...")
    await asyncio.sleep(15)


    if received_messages:
        print(f"\n=== 测试结果 ===")
        print(f"收到回复数量: {len(received_messages)}")
        print("端到端测试成功!")
    else:
        print("未收到回复，可能原因: 1) LLM API 未配置 2) 消息处理时间较长")


        print(f"收到的消息总数: {len(received_messages)}")


        await router.stop()


        print("连接已关闭")


        os.chdir(script_dir)
        script_file = os.path.join(script_dir, 'test_real_reply.py')
        print(f"Starting test script from {script_file}")
        router = Router(config)
        router.register_class_handler(message_handler)

        router_task = asyncio.create_task(router.run())
        message = MessageBase(
            message_info=BaseMessageInfo(
                platform="qq123",
                message_id=str(int(time.time() * 1000)),
                time=int(time.time()),
                group_info=GroupInfo(
                    platform="qq123",
                    group_id="12345678",
                    group_name="测试群",
                ),
                user_info=UserInfo(
                    platform="qq123",
                    user_id="test_user_001",
                    user_nickname="测试用户",
                    user_cardname="",
                ),
                format_info=FormatInfo(
                    content_format=["text"],
                    accept_format=["text"],
                template_info=None,
            ),
            message_segment=Seg(
                "seglist",
                [
                    Seg("text", "你好，我是测试用户，请回复我。"),
                Seg("text", "今天天气怎么样？"),
                ]
            ),
            raw_message="你好",
我是 "test_user_001",
        )
        try:
            print("Starting MaiBot connection test...")
            print("Waiting for connection...")
            await asyncio.sleep(5)
            print("Sending message to MaiBot...")
            await router.send_message(message)
            print("Message sent, waiting for response...")
            for i in range(30):
                print(f"Waiting... ({i+1}s)")
                if received_messages:
                    print(f"\n✅ Received response after {i} seconds!")
                    break
            print("No response received after 30 seconds")
    except KeyboardInterrupt:
        print("\nTest interrupted")
    finally:
        print("Cleaning up...")
        await router.stop()
        if os.path.exists(script_file):
            os.remove(script_file)
EOF
