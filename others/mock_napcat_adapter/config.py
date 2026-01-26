"""配置管理模块 - AI agent 友好的配置接口

支持：
- 从文件加载配置（TOML 格式）
- 程序化修改配置
- 验证配置有效性
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class MockConfig:
    """Mock Napcat Adapter 配置类

    AI agent 可以通过简单的属性访问修改配置：
    >>> config = MockConfig()
    >>> config.host = "0.0.0.0"
    >>> config.port = 3000
    >>> config.message_delay = 1.0
    """

    def __init__(self, config_file: Optional[str] = None):
        """初始化配置

        Args:
            config_file: 配置文件路径（可选）
        """
        # WebSocket 服务器配置
        self.host = "127.0.0.1"
        self.port = 3000
        self.token = ""  # 空字符串表示不启用 token 验证
        self.path = "/"

        # 消息生成配置
        self.message_delay = 2.0  # 消息发送间隔（秒）
        self.message_count = 10  # 测试消息数量
        self.auto_send = True  # 是否自动发送消息
        self.random_delay = True  # 是否使用随机延迟

        # 支持的消息类型
        self.enable_message = True  # 私聊/群聊消息
        self.enable_notice = True  # 通知消息
        self.enable_meta_event = True  # 元事件

        # 模拟的用户信息
        self.self_id = 1234567890
        self.group_id = 987654321
        self.user_id = 1111111111

        # 日志配置
        self.log_level = "INFO"

        # 如果提供了配置文件，加载它
        if config_file:
            self.load_from_file(config_file)

    def load_from_file(self, config_file: str) -> None:
        """从文件加载配置（TOML 格式）

        Args:
            config_file: 配置文件路径
        """
        try:
            import toml

            if not os.path.exists(config_file):
                print(f"⚠️  配置文件不存在: {config_file}，使用默认配置")
                return

            with open(config_file, "r", encoding="utf-8") as f:
                data = toml.load(f)

            # 读取服务器配置
            if "server" in data:
                server = data["server"]
                self.host = server.get("host", self.host)
                self.port = server.get("port", self.port)
                self.token = server.get("token", self.token)

            # 读取消息配置
            if "messages" in data:
                messages = data["messages"]
                self.message_delay = messages.get("delay", self.message_delay)
                self.message_count = messages.get("count", self.message_count)
                self.auto_send = messages.get("auto_send", self.auto_send)
                self.random_delay = messages.get("random_delay", self.random_delay)
                self.enable_message = messages.get(
                    "enable_message", self.enable_message
                )
                self.enable_notice = messages.get("enable_notice", self.enable_notice)
                self.enable_meta_event = messages.get(
                    "enable_meta_event", self.enable_meta_event
                )

            # 读取用户信息
            if "user" in data:
                user = data["user"]
                self.self_id = user.get("self_id", self.self_id)
                self.group_id = user.get("group_id", self.group_id)
                self.user_id = user.get("user_id", self.user_id)

            print(f"✅ 配置已加载: {config_file}")

        except ImportError:
            print("⚠️  未安装 toml 库，使用默认配置")
        except Exception as e:
            print(f"⚠️  加载配置文件失败: {e}，使用默认配置")

    def save_to_file(self, config_file: str) -> None:
        """保存配置到文件（TOML 格式）

        Args:
            config_file: 配置文件路径
        """
        try:
            import toml

            data = {
                "server": {
                    "host": self.host,
                    "port": self.port,
                    "token": self.token,
                },
                "messages": {
                    "delay": self.message_delay,
                    "count": self.message_count,
                    "auto_send": self.auto_send,
                    "random_delay": self.random_delay,
                    "enable_message": self.enable_message,
                    "enable_notice": self.enable_notice,
                    "enable_meta_event": self.enable_meta_event,
                },
                "user": {
                    "self_id": self.self_id,
                    "group_id": self.group_id,
                    "user_id": self.user_id,
                },
            }

            with open(config_file, "w", encoding="utf-8") as f:
                toml.dump(data, f)

            print(f"✅ 配置已保存: {config_file}")

        except ImportError:
            print("⚠️  未安装 toml 库，无法保存配置")
        except Exception as e:
            print(f"⚠️  保存配置文件失败: {e}")

    def validate(self) -> bool:
        """验证配置有效性

        Returns:
            bool: 配置是否有效
        """
        if not (1 <= self.port <= 65535):
            print(f"❌ 端口号无效: {self.port}")
            return False

        if self.message_delay < 0:
            print(f"❌ 消息延迟无效: {self.message_delay}")
            return False

        if self.message_count < 0:
            print(f"❌ 消息数量无效: {self.message_count}")
            return False

        return True

    def __repr__(self) -> str:
        """配置对象的字符串表示"""
        return (
            f"MockConfig(host={self.host}, port={self.port}, "
            f"token={'***' if self.token else 'None'}, "
            f"message_delay={self.message_delay}, message_count={self.message_count})"
        )
