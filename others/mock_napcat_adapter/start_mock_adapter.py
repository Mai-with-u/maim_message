"""快速启动脚本 - Mock Napcat Adapter

简化的启动脚本，用于快速启动 Mock 服务器进行测试。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 添加父目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

# 直接导入模块，避免包名冲突
from config import MockConfig
from mock_server import MockNapcatServer


async def quick_start():
    """快速启动 Mock 服务器"""
    print("🚀 正在启动 Mock Napcat Adapter...")

    # 使用默认配置
    config = MockConfig()

    print(f"📋 配置:")
    print(f"   监听地址: {config.host}:{config.port}")
    print(f"   消息数量: {config.message_count}")
    print(f"   消息延迟: {config.message_delay} 秒")
    print(f"   自动发送: {config.auto_send}")
    print()

    # 创建服务器
    server = MockNapcatServer(config)

    try:
        # 启动服务器
        await server.start()

        print("\n✅ 服务器已启动!")
        print("💡 提示:")
        print("   - 连接地址: ws://{0}:{1}".format(config.host, config.port))
        print("   - 按 Ctrl+C 停止服务器")
        print("   - 查看日志了解消息发送情况")
        print()

        # 持续运行
        while server.running:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n\n⚠️  收到停止信号")
    finally:
        print("🛑 正在停止服务器...")
        await server.stop()
        print("✅ 服务器已停止")

        # 打印统计信息
        stats = server.get_stats()
        print("\n📊 统计信息:")
        print(f"   连接数: {stats['connections']}")
        print(f"   发送消息: {stats['messages_sent']}")
        print(f"   接收消息: {stats['messages_received']}")
        print(f"   API 调用: {stats['api_calls']}")


if __name__ == "__main__":
    asyncio.run(quick_start())
