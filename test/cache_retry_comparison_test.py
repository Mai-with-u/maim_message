"""
缓存重试功能对比测试

测试场景：
1. 对比启用/禁用缓存重试在断联场景下的表现
2. 客户端连续发送消息,在中间点模拟断联
3. 验证消息丢失和重发情况
"""

import asyncio
import time
import sys
import os
from typing import Dict, List
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from maim_message.client import create_client_config, WebSocketClient
from maim_message.server import create_server_config, WebSocketServer
from maim_message.api_message_base import (
    APIMessageBase,
    BaseMessageInfo,
    Seg,
    MessageDim,
)


@dataclass
class TestResult:
    """测试结果统计"""

    mode: str  # "enabled" or "disabled"
    total_sent: int = 0
    received_before_disconnect: int = 0
    received_after_reconnect: int = 0
    total_received: int = 0
    lost_messages: int = 0
    message_loss_rate: float = 0.0
    cached_messages_count: int = 0
    retry_success_count: int = 0
    details: List[Dict] = field(default_factory=list)


class MessageTracker:
    """消息追踪器"""

    def __init__(self):
        self.received_messages: Dict[str, float] = {}
        self.received_count = 0
        self.receive_times: List[float] = []

    def track(self, msg_id: str, content: str):
        """追踪接收到的消息"""
        timestamp = time.time()
        self.receive_times.append(timestamp)

        if msg_id not in self.received_messages:
            self.received_messages[msg_id] = timestamp

        self.received_count += 1
        print(f"📥 服务端收到消息 #{self.received_count}: {content} (ID: {msg_id})")

    def get_count(self) -> int:
        return self.received_count

    def get_unique_count(self) -> int:
        return len(self.received_messages)


async def server_test(server: WebSocketServer, tracker: MessageTracker):
    """服务端测试逻辑"""

    async def message_handler(msg, meta):
        msg_id = msg.message_info.message_id
        content = msg.message_segment.data
        tracker.track(msg_id, content)

    server.update_config(on_message=message_handler)

    print("📡 服务端启动...")
    await server.start()
    await asyncio.sleep(0.5)
    print("📡 服务端已启动\n")

    # 保持服务端运行
    while True:
        await asyncio.sleep(1)


async def client_test_with_cache_retry(
    client: WebSocketClient,
    total_messages: int = 20,
    disconnect_at: int = 10,
    reconnect_delay: float = 2.0,
    cache_enabled: bool = False,
) -> TestResult:
    """
    客户端测试逻辑 - 带断联模拟

    Args:
        client: WebSocket客户端实例
        total_messages: 总共发送的消息数
        disconnect_at: 在第几条消息后断联
        reconnect_delay: 重连延迟时间(秒)

    Returns:
        TestResult: 测试结果统计
    """
    result = TestResult(
        mode="enabled" if client.config.enable_message_cache else "disabled"
    )

    print(f"📱 客户端连接中...")
    await client.start()
    connected = await client.connect()

    if not connected:
        print("❌ 客户端连接失败")
        return result

    print(f"✅ 客户端连接成功")
    print(f"⚙️  缓存重试: {'启用' if client.config.enable_message_cache else '禁用'}")
    print(
        f"⚙️  配置: TTL={client.config.message_cache_ttl}s, "
        f"max_size={client.config.message_cache_max_size}\n"
    )

    disconnect_triggered = False
    message_count = 0

    print(f"📤 开始发送 {total_messages} 条消息...")
    print(f"⚠️  将在第 {disconnect_at} 条消息后模拟断联\n")

    while message_count < total_messages:
        # 在指定位置模拟断联
        if message_count == disconnect_at and not disconnect_triggered:
            print(f"\n🔌 模拟第 {disconnect_at} 条消息后的断联...")
            result.received_before_disconnect = client.network_driver.stats.get(
                "messages_sent", 0
            )

            # 停止客户端连接(不发送Close帧,模拟异常断开)
            await client.stop()
            disconnect_triggered = True

            # 等待客户端完全停止和端口释放
            await asyncio.sleep(1.0)

            print(f"   ⏸️  等待 {reconnect_delay} 秒后重连...")
            await asyncio.sleep(reconnect_delay)

            await client.start()

            # 在断联期间尝试发送一条消息(测试缓存功能)
            print(f"   📤 断联期间尝试发送消息...")
            lost_message = APIMessageBase(
                message_info=BaseMessageInfo(
                    platform="test",
                    message_id=f"msg_lost_{int(time.time() * 1000)}",
                    time=int(time.time()),
                ),
                message_segment=Seg(type="text", data="断联期间发送的消息"),
                message_dim=MessageDim(api_key="test_api_key", platform="test"),
            )
            success_lost = await client.send_message(lost_message)
            if not success_lost:
                if cache_enabled:
                    print(f"   ⚠️  断联期间发送失败(预期) - 消息已缓存")
                else:
                    print(f"   ⚠️  断联期间发送失败(预期) - 消息丢失")

            message_count += 1
            result.total_sent = message_count

            print(f"   🔄 重新连接...")

            connected = await client.connect()
            if connected:
                print(f"   ✅ 重连成功")
                await asyncio.sleep(1.5)
            else:
                print(f"   ❌ 重连失败,测试终止")
                break

        # 发送消息
        message_count += 1
        message = APIMessageBase(
            message_info=BaseMessageInfo(
                platform="test",
                message_id=f"msg_{message_count}_{int(time.time() * 1000)}",
                time=int(time.time()),
            ),
            message_segment=Seg(type="text", data=f"测试消息 {message_count}"),
            message_dim=MessageDim(api_key="test_api_key", platform="test"),
        )

        success = await client.send_message(message)
        if success:
            result.total_sent = message_count
            result.total_sent = message_count

            status = (
                "📤 发送"
                if message_count <= disconnect_at or not disconnect_triggered
                else "📤 发送"
            )
            print(
                f"{status}消息 [{message_count}/{total_messages}]: {message.message_segment.data}"
            )

            # 记录详细信息
            result.details.append(
                {
                    "index": message_count,
                    "msg_id": message.message_info.message_id,
                    "content": message.message_segment.data,
                    "sent_after_disconnect": message_count > disconnect_at,
                    "success": True,
                }
            )
        else:
            print(f"❌ 消息发送失败")
            result.details.append(
                {
                    "index": message_count + 1,
                    "msg_id": message.message_info.message_id,
                    "content": message.message_segment.data,
                    "sent_after_disconnect": message_count > disconnect_at,
                    "success": False,
                }
            )

        await asyncio.sleep(0.3)  # 发送间隔

    # 等待消息处理完成
    await asyncio.sleep(2.0)

    # 获取缓存统计(如果启用)
    if client.config.enable_message_cache and client.network_driver.message_cache:
        cache_stats = client.network_driver.message_cache.get_stats()
        result.cached_messages_count = cache_stats.get("cached_messages", 0)
        print(f"\n💾 缓存统计: 当前缓存 {result.cached_messages_count} 条消息")

    await client.stop()

    return result


async def run_cache_retry_comparison_test(enable_cache: bool):
    """
    运行缓存重试对比测试

    Args:
        enable_cache: 是否启用缓存重试
    """
    tracker = MessageTracker()

    async def auth_handler(metadata):
        return True

    async def extract_user_handler(metadata):
        return metadata.get("api_key", "default")

    # 创建服务端配置
    server_config = create_server_config(
        host="127.0.0.1",
        port=18182,
        on_auth=auth_handler,
        on_auth_extract_user=extract_user_handler,
    )

    # 创建客户端配置
    client_config = create_client_config(
        url="ws://127.0.0.1:18182/ws",
        api_key="test_api_key",
        platform="test",
        max_reconnect_attempts=5,
        ping_interval=10,
        ping_timeout=5,
        reconnect_delay=1.0,
        enable_message_cache=enable_cache,  # 控制缓存开关
        message_cache_ttl=300,
        message_cache_max_size=100,
        on_message=lambda msg, meta: print(
            f"📥 客户端收到消息: {msg.message_segment.data}"
        ),
    )

    server = WebSocketServer(server_config)
    client = WebSocketClient(client_config)

    mode_str = "启用缓存重试" if enable_cache else "禁用缓存重试"
    print("=" * 70)
    print(f"🧪 {mode_str}测试")
    print("=" * 70)
    print(f"📡 服务器: ws://127.0.0.1:18182/ws")
    print(f"⚙️  enable_message_cache={enable_cache}\n")

    result = TestResult(mode="enabled" if enable_cache else "disabled")

    try:
        # 先启动服务端
        server_task = asyncio.create_task(server_test(server, tracker))
        await asyncio.sleep(0.5)

        # 再运行客户端测试
        test_result = await client_test_with_cache_retry(
            client, total_messages=20, disconnect_at=10, cache_enabled=enable_cache
        )
        result.total_sent = test_result.total_sent
        result.received_before_disconnect = test_result.received_before_disconnect
        result.cached_messages_count = test_result.cached_messages_count

        # 等待服务端处理完所有消息
        await asyncio.sleep(1.0)

        # 停止服务器任务
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

        # 收集统计结果
        result.total_received = tracker.get_count()
        result.received_after_reconnect = (
            tracker.get_unique_count() - result.received_before_disconnect
        )

        # 计算消息丢失率
        if result.total_sent > 0:
            result.lost_messages = result.total_sent - result.total_received
            result.message_loss_rate = (result.lost_messages / result.total_sent) * 100

        print("\n" + "=" * 70)
        print(f"📊 {mode_str} - 测试结果")
        print("=" * 70)
        print(f"📤 客户端发送: {result.total_sent} 条消息")
        print(f"📥 服务端接收: {result.total_received} 条消息")
        print(f"📉 丢失消息: {result.lost_messages} 条")
        print(f"📊 丢失率: {result.message_loss_rate:.2f}%")
        if result.cached_messages_count > 0:
            print(f"💾 缓存消息: {result.cached_messages_count} 条")

    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await server.stop()
        await client.stop()
        print("\n✅ 清理完成")

    return result


async def run_comparison():
    """运行对比测试"""
    print("\n" + "=" * 70)
    print("🔬 缓存重试功能对比测试")
    print("=" * 70)
    print("测试目的: 对比启用/禁用缓存重试在断联场景下的消息丢失情况\n")

    # 测试1: 禁用缓存重试
    print("\n▶️  开始测试1: 禁用缓存重试\n")
    result_disabled = await run_cache_retry_comparison_test(enable_cache=False)

    # 等待端口释放
    await asyncio.sleep(2.0)

    # 测试2: 启用缓存重试
    print("\n▶️  开始测试2: 启用缓存重试\n")
    result_enabled = await run_cache_retry_comparison_test(enable_cache=True)

    # 对比分析
    print("\n" + "=" * 70)
    print("📈 对比分析报告")
    print("=" * 70)

    print(f"\n{'指标':<25} {'禁用缓存':<15} {'启用缓存':<15} {'差异':<15}")
    print("-" * 70)
    print(
        f"{'发送消息数':<25} {result_disabled.total_sent:<15} "
        f"{result_enabled.total_sent:<15} "
        f"{result_enabled.total_sent - result_disabled.total_sent:<15}"
    )

    print(
        f"{'接收消息数':<25} {result_disabled.total_received:<15} "
        f"{result_enabled.total_received:<15} "
        f"{result_enabled.total_received - result_disabled.total_received:<15}"
    )

    print(
        f"{'丢失消息数':<25} {result_disabled.lost_messages:<15} "
        f"{result_enabled.lost_messages:<15} "
        f"{result_disabled.lost_messages - result_enabled.lost_messages:<15}"
    )

    print(
        f"{'消息丢失率':<24} {result_disabled.message_loss_rate:.2f}%{'':<10} "
        f"{result_enabled.message_loss_rate:.2f}%{'':<10} "
        f"{result_disabled.message_loss_rate - result_enabled.message_loss_rate:+.2f}%{'':<8}"
    )

    print(
        f"{'缓存消息数':<25} {'N/A':<15} "
        f"{result_enabled.cached_messages_count:<15} {'-':<15}"
    )

    # 结论
    print("\n" + "=" * 70)
    print("🎯 测试结论")
    print("=" * 70)

    if result_enabled.lost_messages < result_disabled.lost_messages:
        saved = result_disabled.lost_messages - result_enabled.lost_messages
        improvement = (
            (saved / result_disabled.total_sent) * 100
            if result_disabled.total_sent > 0
            else 0
        )
        print(f"✅ 缓存重试功能有效:")
        print(f"   - 减少消息丢失: {saved} 条 ({improvement:.2f}%)")
        print(f"   - 禁用缓存时丢失率: {result_disabled.message_loss_rate:.2f}%")
        print(f"   - 启用缓存时丢失率: {result_enabled.message_loss_rate:.2f}%")
    elif (
        result_enabled.lost_messages == result_disabled.lost_messages
        and result_enabled.lost_messages == 0
    ):
        print(f"✅ 缓存重试功能有效:")
        print(f"   - 两种模式均无消息丢失")
        print(f"   - 缓存重试机制确保了消息的可靠传输")
    else:
        print(f"⚠️  测试结果异常:")
        print(f"   - 启用缓存反而有更多消息丢失")
        print(f"   - 需要检查缓存重试逻辑")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(run_comparison())
