"""
高频断连测试脚本 - 模拟实际断连场景

测试场景：
1. 启动服务器和客户端（Router）
2. 持续高频发送消息（每秒多条）
3. 随机断开服务器（模拟网络故障）
4. 观察客户端重连和消息恢复
5. 分析日志统计成功率

使用方法：
    cd /home/tcmofashi/chatbot/maim_message
    python others/test_high_freq_reconnect.py

输出说明：
    - [INFO] 普通信息
    - [SEND] 消息发送
    - [RECV] 消息接收
    - [DISC] 断开连接
    - [RECO] 重新连接
    - [STAT] 统计信息
"""

import sys
import os
import asyncio
import logging
import time
import random
import socket
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from maim_message.ws_connection import WebSocketServer, WebSocketClient
from maim_message.router import Router, RouteConfig, TargetConfig
from maim_message import (
    BaseMessageInfo,
    UserInfo,
    GroupInfo,
    FormatInfo,
    MessageBase,
    Seg,
)


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d - %(levelname)5s - %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# 设置 maim_message 日志级别
logging.getLogger("maim_message").setLevel(logging.INFO)

# 创建测试专用的 logger
test_logger = logging.getLogger("HighFreqTest")


def log(tag: str, msg: str):
    """带标签的日志输出"""
    print(f"[{tag:4s}] {datetime.now().strftime('%H:%M:%S.%f')[:-3]} {msg}", flush=True)


@dataclass
class TestStats:
    """测试统计"""

    total_sent: int = 0
    total_received: int = 0
    send_success: int = 0
    send_failed: int = 0
    disconnect_events: int = 0
    reconnect_events: int = 0
    server_starts: int = 0
    server_stops: int = 0

    # 时间记录
    start_time: float = field(default_factory=time.time)
    last_disconnect: Optional[float] = None
    last_reconnect: Optional[float] = None

    def elapsed(self) -> float:
        return time.time() - self.start_time

    def send_rate(self) -> float:
        elapsed = self.elapsed()
        return self.send_success / elapsed if elapsed > 0 else 0

    def summary(self) -> str:
        elapsed = self.elapsed()
        return f"""
{"=" * 60}
                    测试结果统计
{"=" * 60}
运行时间: {elapsed:.1f} 秒

消息统计:
  - 发送总数: {self.total_sent}
  - 发送成功: {self.send_success}
  - 发送失败: {self.send_failed}
  - 收到消息: {self.total_received}
  - 成功率: {(self.send_success / max(self.total_sent, 1) * 100):.1f}%
  - 发送速率: {self.send_rate():.1f} 条/秒

连接统计:
  - 断开次数: {self.disconnect_events}
  - 重连次数: {self.reconnect_events}
  - 服务器重启: {self.server_starts} 次启动 / {self.server_stops} 次停止

{"=" * 60}
"""


class HighFreqReconnectTester:
    """高频断连测试器"""

    def __init__(self, port: int = 18101):
        self.port = port
        self.server: Optional[WebSocketServer] = None
        self.server_task: Optional[asyncio.Task] = None
        self.router: Optional[Router] = None
        self.router_task: Optional[asyncio.Task] = None

        self.stats = TestStats()
        self.running = False
        self.message_counter = 0
        self.received_messages: List[Dict] = []

        # 测试配置
        self.send_interval = 0.1  # 发送间隔（秒）
        self.message_size = 100  # 消息大小（字符）
        self.disconnect_interval = (5, 15)  # 断开间隔范围（秒）
        self.disconnect_duration = (2, 5)  # 断开持续时间（秒）
        self.test_duration = 60  # 总测试时长（秒）

    def is_port_open(self, timeout: float = 1.0) -> bool:
        """检查端口是否开放"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex(("localhost", self.port))
            sock.close()
            return result == 0
        except Exception:
            return False

    async def start_server(self) -> bool:
        """启动服务器"""
        try:
            log("INFO", f"启动服务器在端口 {self.port}...")
            self.server = WebSocketServer(
                host="localhost",
                port=self.port,
                path="/ws",
            )

            # 注册消息处理器
            self.server.register_message_handler(self._on_server_message)

            self.server_task = asyncio.create_task(self.server.start())

            # 等待服务器就绪
            for _ in range(30):
                await asyncio.sleep(0.5)
                if self.is_port_open():
                    self.stats.server_starts += 1
                    log("INFO", "✅ 服务器启动成功")
                    return True

            log("ERR ", "❌ 服务器启动超时")
            return False

        except Exception as e:
            log("ERR ", f"启动服务器失败: {e}")
            return False

    async def stop_server(self):
        """停止服务器"""
        try:
            log("INFO", "停止服务器...")

            if self.server:
                await self.server.stop()
                self.server = None

            if self.server_task and not self.server_task.done():
                self.server_task.cancel()
                try:
                    await self.server_task
                except asyncio.CancelledError:
                    pass
                self.server_task = None

            self.stats.server_stops += 1
            log("INFO", "✅ 服务器已停止")

        except Exception as e:
            log("ERR ", f"停止服务器出错: {e}")

    async def start_router(self) -> bool:
        """启动 Router 客户端"""
        try:
            log("INFO", "启动 Router 客户端...")

            route_config = RouteConfig(
                route_config={
                    "test_platform": TargetConfig(
                        url=f"http://localhost:{self.port}/ws",
                        token=None,
                    )
                }
            )

            self.router = Router(route_config)
            self.router_task = asyncio.create_task(self.router.run())

            # 等待连接建立
            await asyncio.sleep(3)

            if self.router.check_connection("test_platform"):
                log("INFO", "✅ Router 连接成功")
                return True
            else:
                log("WARN", "⚠️ Router 初始连接未完成，将在后台重试")
                return True  # 仍然返回 True，让后台重连机制工作

        except Exception as e:
            log("ERR ", f"启动 Router 失败: {e}")
            return False

    async def stop_router(self):
        """停止 Router"""
        try:
            log("INFO", "停止 Router...")

            if self.router:
                await self.router.stop()
                self.router = None

            if self.router_task and not self.router_task.done():
                self.router_task.cancel()
                try:
                    await self.router_task
                except asyncio.CancelledError:
                    pass
                self.router_task = None

            log("INFO", "✅ Router 已停止")

        except Exception as e:
            log("ERR ", f"停止 Router 出错: {e}")

    async def _on_server_message(self, message: Dict):
        """服务器收到消息"""
        self.stats.total_received += 1
        self.received_messages.append(
            {
                "time": time.time(),
                "data": message,
            }
        )

        # 每10条打印一次
        if self.stats.total_received % 10 == 0:
            log("RECV", f"收到第 {self.stats.total_received} 条消息")

    def create_test_message(self, index: int) -> MessageBase:
        """创建测试消息"""
        user_info = UserInfo(
            platform="test_platform",
            user_id=f"test_user_{index % 10:03d}",
            user_nickname="测试用户",
        )

        group_info = GroupInfo(
            platform="test_platform",
            group_id="test_group_001",
            group_name="测试群组",
        )

        format_info = FormatInfo(
            content_format=["text"],
            accept_format=["text"],
        )

        message_info = BaseMessageInfo(
            platform="test_platform",
            message_id=f"test_msg_{int(time.time() * 1000)}_{index}",
            time=int(time.time()),
            group_info=group_info,
            user_info=user_info,
            format_info=format_info,
        )

        # 生成指定大小的文本
        text = f"Message {index}: " + "X" * (self.message_size - 20)
        message_segment = Seg("text", text)

        return MessageBase(
            message_info=message_info,
            message_segment=message_segment,
        )

    async def message_sender(self):
        """消息发送循环"""
        log("INFO", f"启动消息发送循环 (间隔: {self.send_interval}s)")

        while self.running:
            try:
                if self.router and self.router.check_connection("test_platform"):
                    self.message_counter += 1
                    self.stats.total_sent += 1

                    try:
                        message = self.create_test_message(self.message_counter)
                        result = await self.router.send_message(message)

                        if result:
                            self.stats.send_success += 1
                            if self.message_counter % 10 == 0:
                                log("SEND", f"成功发送第 {self.message_counter} 条消息")
                        else:
                            self.stats.send_failed += 1
                            log("SEND", f"发送失败 #{self.message_counter}")

                    except Exception as e:
                        self.stats.send_failed += 1
                        log("ERR ", f"发送异常 #{self.message_counter}: {e}")

                await asyncio.sleep(self.send_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log("ERR ", f"发送循环异常: {e}")
                await asyncio.sleep(self.send_interval)

        log("INFO", "消息发送循环已停止")

    async def disconnect_simulator(self):
        """断开模拟器 - 随机断开服务器"""
        log("INFO", "启动断开模拟器")

        while self.running:
            try:
                # 随机等待
                wait_time = random.uniform(*self.disconnect_interval)
                log("INFO", f"{wait_time:.1f} 秒后将断开服务器...")
                await asyncio.sleep(wait_time)

                if not self.running:
                    break

                # 断开服务器
                log("DISC", "⚡ 模拟网络故障：停止服务器")
                self.stats.disconnect_events += 1
                self.stats.last_disconnect = time.time()
                await self.stop_server()

                # 等待一段时间
                duration = random.uniform(*self.disconnect_duration)
                log("DISC", f"服务器已停止，等待 {duration:.1f} 秒后恢复...")
                await asyncio.sleep(duration)

                if not self.running:
                    break

                # 重新启动服务器
                log("RECO", "🔄 恢复网络：重新启动服务器")
                success = await self.start_server()

                if success:
                    self.stats.reconnect_events += 1
                    self.stats.last_reconnect = time.time()
                    reconnect_time = (
                        self.stats.last_reconnect - self.stats.last_disconnect
                    )
                    log("RECO", f"✅ 服务器已恢复，断开时长: {reconnect_time:.1f}s")
                else:
                    log("ERR ", "❌ 服务器恢复失败")

            except asyncio.CancelledError:
                break
            except Exception as e:
                log("ERR ", f"断开模拟器异常: {e}")
                await asyncio.sleep(1)

        log("INFO", "断开模拟器已停止")

    async def status_reporter(self):
        """状态报告器 - 定期打印状态"""
        while self.running:
            try:
                await asyncio.sleep(10)  # 每10秒报告一次

                if not self.running:
                    break

                connected = (
                    self.router.check_connection("test_platform")
                    if self.router
                    else False
                )
                log(
                    "STAT",
                    f"连接: {'✅' if connected else '❌'} | "
                    f"发送: {self.stats.send_success}/{self.stats.total_sent} | "
                    f"接收: {self.stats.total_received} | "
                    f"断开: {self.stats.disconnect_events} | "
                    f"速率: {self.stats.send_rate():.1f}条/s",
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                log("ERR ", f"状态报告异常: {e}")

    async def run_test(self):
        """运行完整测试"""
        log("INFO", f"{'=' * 60}")
        log("INFO", "     高频断连测试")
        log("INFO", f"{'=' * 60}")
        log("INFO", f"测试配置:")
        log("INFO", f"  - 端口: {self.port}")
        log("INFO", f"  - 发送间隔: {self.send_interval}s")
        log("INFO", f"  - 消息大小: {self.message_size} 字符")
        log(
            "INFO",
            f"  - 断开间隔: {self.disconnect_interval[0]}-{self.disconnect_interval[1]}s",
        )
        log(
            "INFO",
            f"  - 断开时长: {self.disconnect_duration[0]}-{self.disconnect_duration[1]}s",
        )
        log("INFO", f"  - 测试时长: {self.test_duration}s")
        log("INFO", f"{'=' * 60}")

        self.running = True

        # 1. 启动服务器
        if not await self.start_server():
            log("ERR ", "测试中止：无法启动服务器")
            return

        # 2. 启动 Router
        if not await self.start_router():
            log("ERR ", "测试中止：无法启动 Router")
            await self.stop_server()
            return

        # 3. 启动各个任务
        tasks = [
            asyncio.create_task(self.message_sender()),
            asyncio.create_task(self.disconnect_simulator()),
            asyncio.create_task(self.status_reporter()),
        ]

        # 4. 等待测试时长
        log("INFO", f"测试运行中，持续 {self.test_duration} 秒...")
        await asyncio.sleep(self.test_duration)

        # 5. 停止测试
        log("INFO", "测试时间到，正在停止...")
        self.running = False

        # 取消所有任务
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)

        # 6. 清理
        await self.stop_router()
        await self.stop_server()

        # 7. 打印统计
        print(self.stats.summary())


async def main():
    """主函数"""
    tester = HighFreqReconnectTester(port=18101)

    try:
        await tester.run_test()
    except KeyboardInterrupt:
        log("INFO", "测试被用户中断")
        tester.running = False
        await tester.stop_router()
        await tester.stop_server()
        print(tester.stats.summary())
    except Exception as e:
        log("ERR ", f"测试异常: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
