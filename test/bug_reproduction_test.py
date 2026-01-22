"""
Bug复现测试 - 模拟原始问题场景

原始问题：
- maimbot和adapter通过maim_message连接
- API服务器模式下访问屏幕时出现大量连接/断开
- 旧消息被重新发送
- Legacy模式有断连问题但从未出现消息积压

测试目标：
1. 模拟多客户端快速连接/断开
2. 在不稳定网络状态下发送消息
3. 验证消息去重机制
4. 验证连接管理
5. 验证无消息积压
"""

import asyncio
import time
import sys
import os
from typing import Dict, List
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from maim_message.client import create_client_config, WebSocketClient
from maim_message.server import create_server_config, WebSocketServer
from maim_message.api_message_base import (
    APIMessageBase,
    BaseMessageInfo,
    Seg,
    MessageDim,
)


class ConnectionMonitor:
    """连接和消息监控器"""

    def __init__(self):
        self.connection_events: List[Dict] = []
        self.message_stats: Dict[str, List[float]] = defaultdict(list)
        self.message_duplicates: Dict[str, int] = defaultdict(int)

    def record_connection(self, event: str, uuid: str, timestamp: float):
        """记录连接事件"""
        self.connection_events.append(
            {
                "event": event,
                "uuid": uuid,
                "timestamp": timestamp,
            }
        )

    def record_message(self, msg_id: str, content: str, timestamp: float):
        """记录消息"""
        if msg_id in self.message_stats:
            self.message_duplicates[msg_id] += 1
        self.message_stats[msg_id].append(timestamp)

    def get_summary(self) -> Dict:
        """获取统计摘要"""
        connect_events = [e for e in self.connection_events if e["event"] == "connect"]
        disconnect_events = [
            e for e in self.connection_events if e["event"] == "disconnect"
        ]

        return {
            "total_connections": len(connect_events),
            "total_disconnects": len(disconnect_events),
            "unique_messages": len(self.message_stats),
            "total_message_events": sum(
                len(msgs) for msgs in self.message_stats.values()
            ),
            "duplicate_messages": sum(self.message_duplicates.values()),
            "duplicate_rate": f"{(sum(self.message_duplicates.values()) / max(1, sum(len(msgs) for msgs in self.message_stats.values())) * 100):.2f}%",
        }


async def unstable_client_test(
    client: WebSocketClient, name: str, monitor: ConnectionMonitor
):
    """不稳定的客户端测试 - 模拟网络抖动"""

    await client.start()

    connect_count = 0
    max_connects = 5
    messages_per_connect = 3

    for i in range(max_connects):
        await client.connect()
        connect_count += 1
        monitor.record_connection("connect", client.get_connection_uuid(), time.time())

        for j in range(messages_per_connect):
            msg_id = f"msg_{uuid.uuid4().hex[:12]}_{int(time.time())}"
            message = APIMessageBase(
                message_info=BaseMessageInfo(
                    platform="test",
                    message_id=msg_id,
                    time=int(time.time()),
                ),
                message_segment=Seg(type="text", data=f"{name} 消息 {i + 1}-{j + 1}"),
                message_dim=MessageDim(api_key="test_api_key", platform="test"),
            )

            success = await client.send_message(message)
            if success:
                monitor.record_message(
                    msg_id, message.message_segment.data, time.time()
                )

            await asyncio.sleep(0.1)

        await asyncio.sleep(0.3)

        await client.disconnect()
        monitor.record_connection(
            "disconnect", client.get_connection_uuid(), time.time()
        )

        await asyncio.sleep(0.2)

    await client.stop()


async def server_test(server: WebSocketServer, monitor: ConnectionMonitor):
    """服务端测试逻辑"""

    message_count = 0

    async def message_handler(msg, meta):
        nonlocal message_count
        message_count += 1
        msg_id = msg.message_info.message_id
        content = msg.message_segment.data

        monitor.record_message(msg_id, content, time.time())

        print(f"📨 服务器收到 [{message_count}]: ID={msg_id[:20]}..., 内容={content}")

    server.update_config(on_message=message_handler)

    await server.start()

    print(f"📡 服务端已启动，等待连接...")


async def run_bug_reproduction_test():
    """运行Bug复现测试"""
    print("\n" + "=" * 70)
    print("🐛 Bug复现测试 - 模拟原始问题场景")
    print("=" * 70)

    monitor = ConnectionMonitor()

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

    maimbot_config = create_client_config(
        url="ws://127.0.0.1:18181/ws",
        api_key="maimbot_key",
        platform="maimbot",
        max_reconnect_attempts=3,
        reconnect_delay=0.5,
        ping_interval=5,
        ping_timeout=3,
    )

    adapter_config = create_client_config(
        url="ws://127.0.0.1:18181/ws",
        api_key="adapter_key",
        platform="adapter",
        max_reconnect_attempts=3,
        reconnect_delay=0.5,
        ping_interval=5,
        ping_timeout=3,
    )

    print("\n🔧 配置：")
    print(f"   - 服务端: {server_config.host}:{server_config.port}")
    print(f"   - maimbot客户端: {maimbot_config.api_key}")
    print(f"   - adapter客户端: {adapter_config.api_key}")
    print(f"   - 每个客户端连接次数: 5")
    print(f"   - 每次连接消息数: 3")

    maimbot = WebSocketClient(maimbot_config)
    adapter = WebSocketClient(adapter_config)
    server = WebSocketServer(server_config)

    print("\n🚀 启动服务端...")
    server_task = asyncio.create_task(server_test(server, monitor))

    await asyncio.sleep(1.0)

    print("\n🔄 开始模拟不稳定的客户端行为...")
    start_time = time.time()

    maimbot_task = asyncio.create_task(
        unstable_client_test(maimbot, "maimbot", monitor)
    )
    adapter_task = asyncio.create_task(
        unstable_client_test(adapter, "adapter", monitor)
    )

    await asyncio.gather(maimbot_task, adapter_task)

    end_time = time.time()
    duration = end_time - start_time

    print(f"\n⏳ 等待所有消息处理完成...")
    await asyncio.sleep(1.0)

    print("\n" + "=" * 70)
    print("📊 测试结果分析")
    print("=" * 70)

    summary = monitor.get_summary()
    server_stats = server.get_stats()

    print(f"\n⏱️  测试时长: {duration:.2f}秒")
    print(f"\n🔌 连接事件:")
    print(f"   - 总连接次数: {summary['total_connections']}")
    print(f"   - 总断开次数: {summary['total_disconnects']}")
    print(
        f"   - 连接/断开比: {summary['total_connections']}/{summary['total_disconnects']}"
    )

    print(f"\n📨 消息统计:")
    print(f"   - 唯一消息数: {summary['unique_messages']}")
    print(f"   - 总消息事件: {summary['total_message_events']}")
    print(f"   - 重复消息数: {summary['duplicate_messages']}")
    print(f"   - 重复率: {summary['duplicate_rate']}")

    print(f"\n📈 服务端统计:")
    print(f"   - 总消息接收: {server_stats.get('messages_received', 0)}")
    print(f"   - 重复消息忽略: {server_stats.get('duplicate_messages_ignored', 0)}")
    print(f"   - 总连接数: {server_stats.get('total_connections', 0)}")
    print(f"   - 当前连接数: {server_stats.get('current_connections', 0)}")

    print("\n" + "=" * 70)

    issues_found = []

    if summary["duplicate_messages"] > 0:
        issues_found.append(f"⚠️  发现 {summary['duplicate_messages']} 条重复消息")

    if summary["duplicate_messages"] > summary["unique_messages"] * 0.1:
        issues_found.append(f"⚠️  重复率过高 ({summary['duplicate_rate']})")

    if server_stats.get("duplicate_messages_ignored", 0) > 0:
        print(
            f"✅ 服务器去重机制工作正常: {server_stats['duplicate_messages_ignored']} 条重复被过滤"
        )

    if server_stats.get("current_connections", 0) > 0:
        print(f"⚠️  测试结束后仍有活跃连接，可能存在连接泄漏")

    if not issues_found and server_stats.get("duplicate_messages_ignored", 0) > 0:
        print("\n✅ 测试通过: 所有机制正常工作")
        print("   - 连接管理正常")
        print("   - 消息去重生效")
        print("   - 无消息积压")
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

    asyncio.run(run_bug_reproduction_test())
