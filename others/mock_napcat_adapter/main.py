"""Mock Napcat Adapter 主入口点

提供两种使用方式：
1. 命令行模式：python -m mock_napcat_adapter
2. 编程模式：作为模块导入使用
"""

import argparse
import asyncio
import logging
import sys
from typing import Optional

try:
    from .config import MockConfig
    from .mock_server import MockNapcatServer
    from .message_generator import MessageType
except ImportError:
    from config import MockConfig
    from mock_server import MockNapcatServer
    from message_generator import MessageType

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("MockNapcatAdapter")


async def run_server(config: MockConfig, auto_stop: bool = False) -> None:
    """运行 Mock 服务器

    Args:
        config: 配置对象
        auto_stop: 是否在消息发送完成后自动停止
    """
    server = MockNapcatServer(config)

    try:
        await server.start()

        # 如果设置了消息数量且启用了自动停止，等待消息发送完成后停止
        if config.auto_send and config.message_count > 0 and auto_stop:
            logger.info(f"⏱️  将在发送 {config.message_count} 条消息后自动停止...")
            # 等待足够的时间让消息发送完成
            await asyncio.sleep(config.message_count * config.message_delay * 2)
            logger.info("🛑 自动停止触发")
        else:
            # 持续运行，等待 Ctrl+C
            logger.info("✅ 服务器正在运行，按 Ctrl+C 停止")
            try:
                while server.running:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass

    except asyncio.CancelledError:
        logger.info("⏸️  收到停止信号")
    finally:
        await server.stop()


def main() -> None:
    """主函数（命令行入口）"""
    parser = argparse.ArgumentParser(
        description="Mock Napcat Adapter - 用于测试 maim_message 和 MaiMBot 连接"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="监听主机地址 (默认: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3000,
        help="监听端口 (默认: 3000)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default="",
        help="WebSocket 认证 token (默认: 无认证)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="配置文件路径 (TOML 格式)",
    )
    parser.add_argument(
        "--message-delay",
        type=float,
        default=2.0,
        help="消息发送间隔（秒） (默认: 2.0)",
    )
    parser.add_argument(
        "--message-count",
        type=int,
        default=10,
        help="测试消息数量 (默认: 10, 0 表示无限)",
    )
    parser.add_argument(
        "--no-auto-send",
        action="store_true",
        help="禁用自动发送消息",
    )
    parser.add_argument(
        "--auto-stop",
        action="store_true",
        help="在消息发送完成后自动停止",
    )
    parser.add_argument(
        "--self-id",
        type=int,
        default=1234567890,
        help="模拟的机器人 QQ 号 (默认: 1234567890)",
    )
    parser.add_argument(
        "--group-id",
        type=int,
        default=987654321,
        help="模拟的群号 (默认: 987654321)",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=1111111111,
        help="模拟的用户 QQ 号 (默认: 1111111111)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别 (默认: INFO)",
    )

    args = parser.parse_args()

    # 加载配置
    if args.config:
        config = MockConfig(config_file=args.config)
    else:
        config = MockConfig()

    # 应用命令行参数（覆盖配置文件）
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.token is not None:
        config.token = args.token
    if args.message_delay:
        config.message_delay = args.message_delay
    if args.message_count:
        config.message_count = args.message_count
    if args.no_auto_send:
        config.auto_send = False
    if args.self_id:
        config.self_id = args.self_id
    if args.group_id:
        config.group_id = args.group_id
    if args.user_id:
        config.user_id = args.user_id
    if args.log_level:
        config.log_level = args.log_level

    # 设置日志级别
    logging.getLogger("MockNapcatAdapter").setLevel(getattr(logging, config.log_level))

    # 验证配置
    if not config.validate():
        logger.error("❌ 配置无效")
        sys.exit(1)

    # 启动服务器
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(run_server(config, auto_stop=args.auto_stop))
    except KeyboardInterrupt:
        logger.info("⚠️  收到中断信号")
    except OSError as e:
        if e.errno == 10048 or "address already in use" in str(e).lower():
            logger.error(f"❌ 端口 {config.port} 已被占用")
        else:
            logger.error(f"❌ 网络错误: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 未知错误: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("👋 程序退出")
        loop.close()


if __name__ == "__main__":
    main()
