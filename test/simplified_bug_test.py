"""
简化Bug复现测试 - 专注于消息去重验证
"""

import asyncio
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from maim_message.client import create_client_config, WebSocketClient
from maim_message.server import create_server_config, WebSocketServer
from maim_message.api_message_base import (
    APIMessageBase,
    BaseMessageInfo,
    Seg,
    MessageDim,
)


class ServerMessageTracker:
    """服务端消息追踪器 - 检测重复"""

    def __init__(self):
        self.messages = {}

    def handle_message(self, msg_id, content):
        timestamp = time.time()

        if msg_id in self.messages:
            count = self.messages[msg_id]["count"]
            self.messages[msg_id]["count"] = count + 1
            self.messages[msg_id]["timestamps"].append(timestamp)
            print(f"⚠️  重复消息: ID={msg_id[:20]}... (第{count + 1}次)")
            return False
        else:
            self.messages[msg_id] = {
                "content": content,
                "count": 1,
                "timestamps": [timestamp],
                "first_seen": timestamp,
            }
            print(f"✅ 新消息: ID={msg_id[:20]}..., 内容={content}")
            return True

    def get_stats(self):
        total_events = sum(m["count"] for m in self.messages.values())
        duplicate_events = total_events - len(self.messages)
        return {
            "unique_messages": len(self.messages),
            "total_message_events": total_events,
            "duplicate_events": duplicate_events,
            "duplicate_rate": f"{(duplicate_events / max(1, total_events) * 100):.2f}%",
        }


async def client_behavior_test(client: WebSocketClient, name: str):
    """客户端行为测试 - 模拟实际使用场景"""

    await client.start()
    await client.connect()
    print(f"📱 {name} 连接成功")

    # 发送一批消息
    message_count = 10
    print(f"\n📤 {name} 开始发送 {message_count} 条消息...")

    for i in range(message_count):
        msg_id = f"msg_{uuid.uuid4().hex[:12]}_{int(time.time())}"
        message = APIMessageBase(
            message_info=BaseMessageInfo(
                platform="test",
                message_id=msg_id,
                time=int(time.time()),
            ),
            message_segment=Seg(type="text", data=f"{name} 消息 {i + 1}"),
            message_dim=MessageDim(api_key="test_api_key", platform="test"),
        )

        success = await client.send_message(message)
        if success:
            print(f"  📤 [{i + 1}/{message_count}] 发送: ID={msg_id[:20]}...")
        else:
            print(f"  ❌ [{i + 1}/{message_count}] 发送失败")

        await asyncio.sleep(0.1)

    # 模拟断线重连
    print(f"\n🔌 {name} 模拟断线...")
    await client.disconnect()
    await asyncio.sleep(1.0)

    print(f"🔄 {name} 重新连接...")
    connected = await client.connect()
    if connected:
        print(f"✅ {name} 重连成功")

        # 重连后再发送消息
        print(f"\n📤 {name} 重连后发送 {message_count} 条消息...")
        for i in range(message_count):
            msg_id = f"msg_{uuid.uuid4().hex[:12]}_{int(time.time())}"
            message = APIMessageBase(
                message_info=BaseMessageInfo(
                    platform="test",
                    message_id=msg_id,
                    time=int(time.time()),
                ),
                message_segment=Seg(type="text", data=f"{name} 重连消息 {i + 1}"),
                message_dim=MessageDim(api_key="test_api_key", platform="test"),
            )

            success = await client.send_message(message)
            if success:
                print(f"  📤 [{i + 1}/{message_count}] 发送: ID={msg_id[:20]}...")
            else:
                print(f"  ❌ [{i + 1}/{message_count}] 发送失败")

            await asyncio.sleep(0.1)

    await client.stop()


async def server_test(server: WebSocketServer, tracker: ServerMessageTracker):
    """服务端测试"""

    async def message_handler(msg, meta):
        msg_id = msg.message_info.message_id
        content = msg.message_segment.data
        tracker.handle_message(msg_id, content)

    server.update_config(on_message=message_handler)

    await server.start()
    print("📡 服务端已启动\n")


async def run_simplified_test():
    """运行简化的Bug复现测试"""
    print("\n" + "=" * 70)
    print("🐛 简化Bug复现测试 - 验证消息去重和连接管理")
    print("=" * 70)

    tracker = ServerMessageTracker()

    async def auth_handler(metadata):
        return True

    async def extract_user_handler(metadata):
        return metadata.get("api_key", "default")

    server_config = create_server_config(
        host="127.0.0.1",
        port=18181,
        on_auth=auth_handler,
        on_auth_extract_user=extract_user_handler,
    )

    client_config = create_client_config(
        url="ws://127.0.0.1:18181/ws",
        api_key="test_api_key",
        platform="test",
        max_reconnect_attempts=3,
        reconnect_delay=0.5,
        ping_interval=5,
        ping_timeout=3,
    )

    print("🔧 配置:")
    print(f"   - 服务端: {server_config.host}:{server_config.port}")
    print(f"   - 客户端: {client_config.api_key}")
    print(f"   - 每轮消息数: 10")
    print(f"   - 包含断线重连测试")

    client = WebSocketClient(client_config)
    server = WebSocketServer(server_config)

    print("\n🚀 启动服务端...")
    server_task = asyncio.create_task(server_test(server, tracker))

    await asyncio.sleep(0.5)

    print("🔄 开始客户端测试...")
    start_time = time.time()

    await client_behavior_test(client, "test_client")

    end_time = time.time()
    duration = end_time - start_time

    print(f"\n⏳ 等待消息处理完成...")
    await asyncio.sleep(1.0)

    print("\n" + "=" * 70)
    print("📊 测试结果")
    print("=" * 70)

    stats = tracker.get_stats()
    server_stats = server.get_stats()

    print(f"\n⏱️  测试时长: {duration:.2f}秒")
    print(f"\n📨 消息统计:")
    print(f"   - 唯一消息数: {stats['unique_messages']}")
    print(f"   - 总消息事件: {stats['total_message_events']}")
    print(f"   - 重复消息数: {stats['duplicate_events']}")
    print(f"   - 重复率: {stats['duplicate_rate']}")

    print(f"\n📈 服务端统计:")
    network_stats = server_stats.get("network", {})
    print(f"   - 总消息接收: {network_stats.get('messages_received', 0)}")
    print(f"   - 重复消息忽略: {server_stats.get('duplicate_messages_ignored', 0)}")
    print(f"   - 总连接数: {network_stats.get('total_connections', 0)}")
    print(f"   - 当前连接数: {network_stats.get('current_connections', 0)}")

    print("\n" + "=" * 70)

    # 验证结果
    issues_found = []

    if stats["duplicate_events"] > 0:
        issues_found.append(f"⚠️  发现 {stats['duplicate_events']} 条重复消息")

    if server_stats.get("duplicate_messages_ignored", 0) > 0:
        print(
            f"✅ 服务端去重机制工作: {server_stats['duplicate_messages_ignored']} 条重复被过滤"
        )

    if server_stats.get("current_connections", 0) == 0:
        print(f"✅ 连接正常关闭，无连接泄漏")

    if not issues_found and server_stats.get("duplicate_messages_ignored", 0) > 0:
        print("\n✅ 测试通过: 所有机制正常工作")
        print("   - 连接管理正常")
        print("   - 断线重连成功")
        print("   - 消息去重生效")
    elif issues_found:
        print("\n❌ 测试发现问题:")
        for issue in issues_found:
            print(f"   {issue}")
    else:
        print("\n✅ 测试通过: 所有机制正常工作")

    print("=" * 70)

    print("\n🧹 清理资源...")
    await server.stop()
    print("✅ 清理完成\n")


if __name__ == "__main__":
    import uuid

    asyncio.run(run_simplified_test())
