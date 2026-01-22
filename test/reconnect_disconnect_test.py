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


async def server_test(server: WebSocketServer):
    print("服务器端：启动中...")
    await server.start()
    await asyncio.sleep(0.5)
    print("服务器端：已启动")


async def client_test(client: WebSocketClient):
    print("客户端：连接中...")
    await client.start()
    connected = await client.connect()

    if not connected:
        print("客户端：连接失败")
        return

    print("客户端：连接成功，开始测试...")

    message_count = 0
    disconnect_count = 0
    test_duration = 60
    start_time = time.time()
    disconnect_times = []

    while time.time() - start_time < test_duration:
        if client.connected:
            message = APIMessageBase(
                message_info=BaseMessageInfo(
                    platform="test",
                    message_id=f"test_{int(time.time() * 1000)}",
                    time=int(time.time()),
                ),
                message_segment=Seg(type="text", data=f"测试消息 {message_count}"),
                message_dim=MessageDim(api_key="test_api_key", platform="test"),
            )

            success = await client.send_message(message)
            if success:
                message_count += 1
                print(f"客户端：消息发送成功 [{message_count}]")
            else:
                print("客户端：消息发送失败")

            await asyncio.sleep(1)
        else:
            disconnect_count += 1
            disconnect_time = time.time()
            disconnect_times.append(disconnect_time)
            print(f"客户端：已断开连接 [{disconnect_count}]")

            for i in range(30):
                if client.connected:
                    print(
                        f"客户端：重新连接成功 (耗时 {time.time() - disconnect_time:.1f}s)"
                    )
                    break
                await asyncio.sleep(1)

            if not client.connected:
                print(f"客户端：重连超时")
                break

    elapsed = time.time() - start_time
    print(f"\n=== 测试完成 ===")
    print(f"测试时长: {elapsed:.1f} 秒")
    print(f"发送消息数: {message_count}")
    print(f"断开连接次数: {disconnect_count}")
    print(
        f"平均消息发送间隔: {elapsed / message_count:.1f} 秒"
        if message_count > 0
        else "未发送消息"
    )

    if disconnect_times:
        print(f"断开间隔分析:")
        for i in range(1, len(disconnect_times)):
            interval = disconnect_times[i] - disconnect_times[i - 1]
            print(f"  断开 {i} -> {i + 1}: {interval:.1f} 秒")

    await client.stop()


async def run_test():
    async def auth_handler(metadata):
        return True

    async def extract_user_handler(metadata):
        return metadata.get("api_key", "default")

    async def message_handler(msg, meta):
        print(f"服务器：收到消息 - {msg.message_segment.data}")

    server_config = create_server_config(
        host="127.0.0.1",
        port=18180,
        on_auth=auth_handler,
        on_auth_extract_user=extract_user_handler,
        on_message=message_handler,
    )

    client_config = create_client_config(
        url="ws://127.0.0.1:18180/ws",
        api_key="test_api_key",
        platform="test",
        max_reconnect_attempts=0,
        ping_interval=20,
        ping_timeout=10,
        reconnect_delay=2.0,
        on_message=lambda msg, meta: print(
            f"客户端：收到消息 - {msg.message_segment.data}"
        ),
    )

    server = WebSocketServer(server_config)
    client = WebSocketClient(client_config)

    print("开始连接稳定性测试...")
    print("服务器: ws://127.0.0.1:18180/ws")
    print(
        f"配置: max_reconnect_attempts={client_config.max_reconnect_attempts}, ping_interval={client_config.ping_interval}s, ping_timeout={client_config.ping_timeout}s"
    )
    print("-" * 50)

    try:
        await asyncio.gather(server_test(server), client_test(client))
    except KeyboardInterrupt:
        print("\n用户中断测试")
    finally:
        await server.stop()
        await client.stop()


if __name__ == "__main__":
    asyncio.run(run_test())
