"""
新版 WebSocket 客户端测试脚本
用于测试 MaiBot 8090 端口的新版 WebSocketServer (websockets 协议)
"""
import asyncio
import time
from maim_message.client import WebSocketClient, ClientConfig
from maim_message.message import (
    APIMessageBase,
    BaseMessageInfo,
    Seg,
    MessageDim,
    GroupInfo,
    UserInfo,
)


received_messages = []


async def message_handler(message: APIMessageBase, metadata: dict):
    """收到消息的回调函数"""
    received_messages.append(message)
    print(f"\n=== 收到回复 ===")
    print(f"Platform: {message.message_info.platform}")
    print(f"消息维度: {message.dim}")
    seg = message.message_segment
    print(f"Segment type: {seg.type}")
    if seg.type == "seglist":
        for item in seg.data:
            data_str = str(item.data)[:100] if item.data else ""
            print(f"  - [{item.type}]: {data_str}")
    else:
        print(f"  - {seg.type}: {str(seg.data)[:100]}")
    print(f"Metadata: {metadata}")


async def main():
    print("=" * 60)
    print("新版 WebSocket 客户端测试")
    print("目标: ws://127.0.0.1:8090/ws")
    print("=" * 60)
    
    config = ClientConfig(
        url="ws://127.0.0.1:8090/ws",
        api_key="test_key",
        platform="test_platform",
        on_message=message_handler,
    )
    
    client = WebSocketClient(config)
    
    try:
        print("\n[1] 连接到服务器...")
        await client.connect()
        print("连接成功!")
        
        print("\n[2] 构造测试消息...")
        message = APIMessageBase(
            dim=MessageDim.PRIVATE,
            message_info=BaseMessageInfo(
                platform="test_platform",
                message_id=str(int(time.time() * 1000)),
                message_id_list=[str(int(time.time() * 1000))],
                group_info=GroupInfo(
                    platform="test_platform",
                    group_id="test_group_123",
                ),
                user_info=UserInfo(
                    platform="test_platform",
                    user_id="test_user_001",
                ),
                sender_info=None,
                receiver_info=None,
            ),
            message_segment=Seg(
                type="seglist",
                data=[
                    Seg(type="text", data="你好，这是来自新版客户端的测试消息。"),
                    Seg(type="text", data="请回复我。"),
                ],
            ),
        )
        
        print(f"消息构造完成:")
        print(f"  Platform: {message.message_info.platform}")
        print(f"  Segments: {len(message.message_segment.data)} 个")
        
        print("\n[3] 发送消息...")
        success = await client.send_message(message)
        print(f"发送结果: {'成功' if success else '失败'}")
        
        print("\n[4] 等待回复 (15秒)...")
        for i in range(15):
            await asyncio.sleep(1)
            if received_messages:
                print(f"\n✅ 收到 {len(received_messages)} 条回复!")
                break
            print(f"等待中... {i+1}s", end="\r")
        
        if not received_messages:
            print("\n\n❌ 未收到回复")
            print("可能原因:")
            print("  1. LLM API 未配置 (model_config.toml 中的 api_key 是占位符)")
            print("  2. 消息处理需要更长时间")
            print("  3. MaiBot 内部错误")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n[5] 断开连接...")
        await client.disconnect()
        print("测试完成")


if __name__ == "__main__":
    asyncio.run(main())
