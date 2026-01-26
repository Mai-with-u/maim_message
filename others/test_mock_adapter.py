"""测试 Mock Napcat Adapter - 验证独立运行能力

这个测试验证 mock_napcat_adapter 可以独立运行并与 maim_message 集成。
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "mock_napcat_adapter"))

from mock_napcat_adapter import MockNapcatServer, MockConfig
import websockets


async def test_mock_adapter():
    """测试 Mock Adapter 的基本功能"""
    print("🧪 开始测试 Mock Napcat Adapter\n")

    # 1. 创建配置
    config = MockConfig()
    config.port = 3000
    config.message_delay = 0.5
    config.message_count = 5

    # 2. 启动 Mock Adapter
    server = MockNapcatServer(config)
    await server.start()

    print("✅ Mock Adapter 启动成功\n")

    # 3. 创建 WebSocket 客户端连接
    client_message_count = 0
    received_messages = []

    async def connect_client():
        nonlocal client_message_count, received_messages

        try:
            async with websockets.connect("ws://127.0.0.1:3000") as ws:
                print("🔗 客户端连接成功\n")

                # 接收消息
                async for raw_message in ws:
                    message = json.loads(raw_message)
                    received_messages.append(message)
                    client_message_count += 1
                    post_type = message.get("post_type", "unknown")
                    print(f"📥 收到消息 [{client_message_count}]: {post_type}")

                    if client_message_count >= 5:
                        print("\n✅ 收到足够的消息，关闭客户端")
                        break

        except Exception as e:
            print(f"❌ 客户端错误: {e}")

    # 4. 启动客户端
    client_task = asyncio.create_task(connect_client())

    # 5. 等待客户端完成
    try:
        await asyncio.wait_for(client_task, timeout=10)
    except asyncio.TimeoutError:
        print("⏱️  客户端超时")

    # 6. 停止服务器
    print("\n🛑 正在停止服务器...")
    await server.stop()

    # 7. 打印统计信息
    print("\n📊 测试结果:")
    print(f"   收到消息数: {client_message_count}")
    print(f"   消息类型分布:")
    for msg in received_messages:
        post_type = msg.get("post_type")
        print(f"      - {post_type}")

    # 8. 验证测试
    stats = server.get_stats()
    print(f"\n📈 服务器统计:")
    print(f"   连接数: {stats['connections']}")
    print(f"   发送消息: {stats['messages_sent']}")
    print(f"   接收消息: {stats['messages_received']}")

    # 测试判断
    if client_message_count >= 5:
        print("\n✅ 测试通过! Mock Adapter 工作正常")
        return True
    else:
        print(f"\n⚠️  测试未完全通过，只收到 {client_message_count}/5 条消息")
        return False


if __name__ == "__main__":
    try:
        result = asyncio.run(test_mock_adapter())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n⚠️  测试被中断")
        sys.exit(1)
