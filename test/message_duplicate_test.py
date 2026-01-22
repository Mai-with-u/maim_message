"""
复现连接断联导致旧消息重新发送的问题

测试场景：
1. 客户端和服务端建立连接
2. 客户端连续发送多条消息
3. 模拟网络抖动/断联
4. 重连后检查是否出现旧消息重新发送
5. 验证消息去重机制是否工作
"""

import asyncio
import time
import sys
import os
from collections import defaultdict
from typing import Dict, Set, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from maim_message.client import create_client_config, WebSocketClient
from maim_message.server import create_server_config, WebSocketServer
from maim_message.api_message_base import (
    APIMessageBase,
    BaseMessageInfo,
    Seg,
    MessageDim,
)


class MessageTracker:
    """消息追踪器 - 检测重复消息"""

    def __init__(self):
        self.received_messages: Dict[str, int] = defaultdict(int)
        self.message_timestamps: Dict[str, float] = {}
        self.duplicates: List[Dict] = []
        self.total_received = 0

    def track_message(self, msg_id: str, timestamp: float, content: str):
        """追踪消息，返回是否为重复"""
        self.total_received += 1

        if msg_id not in self.message_timestamps:
            self.message_timestamps[msg_id] = timestamp
            self.received_messages[msg_id] = 1
            return False, None

        self.received_messages[msg_id] += 1
        first_seen = self.message_timestamps[msg_id]
        time_gap = timestamp - first_seen

        duplicate_info = {
            "msg_id": msg_id,
            "content": content,
            "count": self.received_messages[msg_id],
            "first_seen": first_seen,
            "duplicate_seen": timestamp,
            "time_gap_seconds": time_gap,
        }
        self.duplicates.append(duplicate_info)
        return True, duplicate_info

    def get_summary(self) -> Dict:
        """获取统计摘要"""
        unique_messages = len(self.received_messages)
        duplicate_count = sum(self.received_messages.values()) - unique_messages

        return {
            "total_received": self.total_received,
            "unique_messages": unique_messages,
            "duplicate_count": duplicate_count,
            "duplicate_rate": f"{(duplicate_count / self.total_received * 100):.2f}%"
            if self.total_received > 0
            else "0%",
            "duplicate_details": self.duplicates,
        }


async def server_test(server: WebSocketServer, tracker: MessageTracker):
    """服务端测试逻辑"""
    print("\n📡 服务端启动...")

    async def message_handler(msg, meta):
        """处理收到的消息"""
        msg_id = msg.message_info.message_id
        timestamp = time.time()
        content = msg.message_segment.data

        is_duplicate, info = tracker.track_message(msg_id, timestamp, content)

        if is_duplicate and info:
            print(
                f"⚠️  检测到重复消息: ID={msg_id}, "
                f"第{info['count']}次接收, "
                f"时间间隔={info['time_gap_seconds']:.2f}s, "
                f"内容={content}"
            )
        else:
            print(f"✅ 收到新消息: ID={msg_id}, 内容={content}")

    server.update_config(on_message=message_handler)

    await server.start()
    await asyncio.sleep(0.5)
    print("📡 服务端已启动")


async def client_test_with_disconnects(client: WebSocketClient):
    """客户端测试逻辑 - 带模拟断联"""
    print("\n📱 客户端连接中...")

    await client.start()
    connected = await client.connect()

    if not connected:
        print("❌ 客户端连接失败")
        return False

    print("✅ 客户端连接成功")

    total_messages = 20
    disconnect_at_message = 10
    reconnect_delay = 2.0

    print(f"\n📤 开始发送 {total_messages} 条消息...")
    print(f"⚠️  将在第 {disconnect_at_message} 条消息后模拟断联\n")

    message_count = 0
    disconnect_triggered = False

    while message_count < total_messages:
        if message_count == disconnect_at_message and not disconnect_triggered:
            print(f"\n🔌 模拟第 {disconnect_at_message} 条消息后的断联...")
            print(f"   断开前消息ID: msg_{int(time.time() * 1000)}")

            await client.stop()

            print(f"   等待 {reconnect_delay} 秒后重连...")
            await asyncio.sleep(reconnect_delay)

            print(f"   重新连接...")
            await client.start()
            await client.connect()
            print(f"   ✅ 重连成功")

            disconnect_triggered = True

        message = APIMessageBase(
            message_info=BaseMessageInfo(
                platform="test",
                message_id=f"msg_{int(time.time() * 1000)}",
                time=int(time.time()),
            ),
            message_segment=Seg(type="text", data=f"测试消息 {message_count + 1}"),
            message_dim=MessageDim(api_key="test_api_key", platform="test"),
        )

        success = await client.send_message(message)
        if success:
            message_count += 1
            print(
                f"📤 发送消息 [{message_count}/{total_messages}]: "
                f"ID={message.message_info.message_id}, "
                f"内容={message.message_segment.data}"
            )
        else:
            print(f"❌ 消息发送失败")

        await asyncio.sleep(0.5)

    print(f"\n✅ 所有消息发送完成，共 {message_count} 条")

    return True


async def run_duplicate_detection_test():
    """运行重复消息检测测试"""
    tracker = MessageTracker()

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
        max_reconnect_attempts=5,
        ping_interval=5,
        ping_timeout=3,
        reconnect_delay=1.0,
        on_message=lambda msg, meta: print(
            f"📥 客户端收到消息: {msg.message_segment.data}"
        ),
    )

    server = WebSocketServer(server_config)
    client = WebSocketClient(client_config)

    print("=" * 70)
    print("🧪 重复消息检测测试")
    print("=" * 70)
    print(f"📡 服务器: ws://127.0.0.1:18181/ws")
    print(
        f"⚙️  客户端配置: ping_interval={client_config.ping_interval}s, "
        f"ping_timeout={client_config.ping_timeout}s, "
        f"reconnect_delay={client_config.reconnect_delay}s"
    )

    try:
        await asyncio.gather(
            server_test(server, tracker), client_test_with_disconnects(client)
        )

        print("\n⏳ 等待消息处理完成...")
        await asyncio.sleep(2.0)

        print("\n" + "=" * 70)
        print("📊 测试结果分析")
        print("=" * 70)

        summary = tracker.get_summary()

        print(f"📈 总接收消息数: {summary['total_received']}")
        print(f"📋 唯一消息数: {summary['unique_messages']}")
        print(f"⚠️  重复消息数: {summary['duplicate_count']}")
        print(f"📊 重复率: {summary['duplicate_rate']}")

        if summary["duplicate_count"] > 0:
            print("\n" + "-" * 70)
            print("🔍 重复消息详情:")
            print("-" * 70)
            for i, dup in enumerate(summary["duplicate_details"], 1):
                print(f"\n  重复 {i}:")
                print(f"    消息ID: {dup['msg_id']}")
                print(f"    接收次数: {dup['count']}")
                print(
                    f"    首次接收: {time.strftime('%H:%M:%S', time.localtime(dup['first_seen']))}"
                )
                print(
                    f"    重复接收: {time.strftime('%H:%M:%S', time.localtime(dup['duplicate_seen']))}"
                )
                print(f"    时间间隔: {dup['time_gap_seconds']:.2f} 秒")
                print(f"    内容: {dup['content']}")

            print("\n" + "=" * 70)
            print("❌ 测试失败: 检测到消息重复！")
            print("=" * 70)
            print("\n💡 可能的原因:")
            print("   1. 重连时消息被重新发送")
            print("   2. 没有消息去重机制")
            print("   3. 消息ID生成策略不够唯一（毫秒时间戳可能重复）")
            print("   4. 服务端未维护已处理消息的集合")
        else:
            print("\n" + "=" * 70)
            print("✅ 测试通过: 未检测到消息重复")
            print("=" * 70)

    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
    finally:
        print("\n🧹 清理资源...")
        await server.stop()
        await client.stop()
        print("✅ 清理完成")


if __name__ == "__main__":
    asyncio.run(run_duplicate_detection_test())
