# Mock Napcat Adapter

用于测试 `maim_message` 和 `MaiMBot` 连接的模拟适配器。

## 📋 概述

这个子项目实现了一个 WebSocket 服务器，模拟 Napcat Adapter 的行为，用于：

- **测试 maim_message 库的连接机制**
- **验证 MaiMBot 的消息处理**
- **调试连接问题而无需真实的 QQ 账号**
- **自动化测试支持**

## 🎯 设计目标

### AI Agent 友好
- ✅ 清晰的配置接口（属性访问和修改）
- ✅ 程序化控制 API
- ✅ 详细的日志输出
- ✅ 简单的命令行接口

### 最小依赖
- ✅ 仅依赖标准库和 `websockets`
- ✅ 无需额外数据库或外部服务
- ✅ 可独立运行

### 灵活配置
- ✅ 支持命令行参数
- ✅ 支持 TOML 配置文件
- ✅ 运行时动态修改配置

## 🚀 快速开始

### 方法 1: 使用默认配置

```bash
cd /home/tcmofashi/chatbot/maim_message/others/mock_napcat_adapter
python -m mock_napcat_adapter
```

服务器将在 `ws://127.0.0.1:3000` 启动，并自动发送 10 条测试消息。

### 方法 2: 使用配置文件

```bash
# 1. 复制示例配置
cp config.example.toml config.toml

# 2. 修改配置（可选）
vim config.toml

# 3. 启动服务器
python -m mock_napcat_adapter --config config.toml
```

### 方法 3: 使用命令行参数

```bash
python -m mock_napcat_adapter \
  --host 0.0.0.0 \
  --port 8095 \
  --message-delay 1.0 \
  --message-count 20 \
  --auto-stop
```

### 方法 4: 编程方式（推荐给 AI Agent）

```python
import asyncio
from mock_napcat_adapter import MockNapcatServer, MockConfig

async def main():
    # 创建配置
    config = MockConfig()
    config.host = "127.0.0.1"
    config.port = 8095
    config.message_delay = 1.0
    config.message_count = 20

    # 创建并启动服务器
    server = MockNapcatServer(config)
    await server.start()

    # 等待连接
    print("服务器正在运行，按 Ctrl+C 停止...")

    try:
        while server.running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await server.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

## 📖 使用示例

### 测试与 maim_message 的连接

```python
import asyncio
from maim_message.client import WebSocketClient, create_client_config
from mock_napcat_adapter import MockNapcatServer, MockConfig

async def test_connection():
    # 1. 启动 Mock Napcat Adapter
    mock_config = MockConfig()
    mock_config.port = 8095
    mock_server = MockNapcatServer(mock_config)

    await mock_server.start()

    # 2. 创建 MaiMBot 客户端
    client_config = create_client_config(
        url="ws://127.0.0.1:8095/",
        api_key="test_api_key",
        platform="qq",
    )
    client = WebSocketClient(client_config)

    # 3. 连接并接收消息
    message_count = 0
    async def on_message(message):
        nonlocal message_count
        message_count += 1
        print(f"收到消息 {message_count}: {message}")
        if message_count >= 5:
            # 停止测试
            await client.stop()
            await mock_server.stop()

    client_config.on_message = on_message

    await client.start()
    await client.connect()

    # 4. 等待消息
    await asyncio.sleep(30)

asyncio.run(test_connection())
```

### 动态修改配置

```python
import asyncio
from mock_napcat_adapter import MockNapcatServer, MockConfig

async def dynamic_config():
    server = MockNapcatServer(MockConfig())
    await server.start()

    # 运行 10 秒后修改配置
    await asyncio.sleep(10)

    # 修改消息发送延迟
    server.config.message_delay = 0.5  # 更快的消息发送

    # 修改消息数量
    server.config.message_count = 50

    print("配置已更新!")

    # 继续运行...
    await asyncio.sleep(30)
    await server.stop()

asyncio.run(dynamic_config())
```

### 发送自定义消息

```python
import asyncio
from mock_napcat_adapter import MockNapcatServer, MockConfig

async def send_custom():
    server = MockNapcatServer(MockConfig())
    server.config.auto_send = False  # 禁用自动发送
    await server.start()

    # 等待客户端连接
    await asyncio.sleep(2)

    # 发送自定义消息
    custom_message = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 123456,
        "user_id": 789012,
        "message": [{"type": "text", "data": {"text": "自定义消息"}}],
    }

    await server.send_custom_message(custom_message)

    await asyncio.sleep(2)
    await server.stop()

asyncio.run(send_custom())
```

## ⚙️ 配置选项

### 服务器配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `host` | str | `127.0.0.1` | 监听主机地址 |
| `port` | int | `3000` | 监听端口 |
| `token` | str | `""` | WebSocket 认证 token（空表示不启用） |

### 消息配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `message_delay` | float | `2.0` | 消息发送间隔（秒） |
| `message_count` | int | `10` | 测试消息数量（0 表示无限） |
| `auto_send` | bool | `true` | 是否自动发送消息 |
| `random_delay` | bool | `true` | 是否使用随机延迟 |
| `enable_message` | bool | `true` | 启用私聊/群聊消息 |
| `enable_notice` | bool | `true` | 启用通知事件 |
| `enable_meta_event` | bool | `true` | 启用元事件 |

### 用户信息

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `self_id` | int | `1234567890` | 模拟的机器人 QQ 号 |
| `group_id` | int | `987654321` | 模拟的群号 |
| `user_id` | int | `1111111111` | 模拟的用户 QQ 号 |

## 📦 支持的消息类型

### Message 类型
- ✅ `private` - 私聊消息
- ✅ `group` - 群聊消息

### Notice 类型
- ✅ `friend_recall` - 好友消息撤回
- ✅ `group_recall` - 群消息撤回
- ✅ `poke` - 戳一戳
- ✅ `group_ban` - 群禁言/解禁
- ✅ `group_increase` - 群成员增加
- ✅ `group_decrease` - 群成员减少

### Meta Event 类型
- ✅ `lifecycle` - 生命周期事件（连接）
- ✅ `heartbeat` - 心跳事件

## 🔌 API 调用支持

Mock Adapter 支持模拟以下 Napcat API 调用：

### 操作类
- `send_group_msg` - 发送群消息
- `send_private_msg` - 发送私聊消息
- `set_group_ban` - 群禁言
- `set_group_kick` - 踢出群成员

### 查询类
- `get_login_info` - 获取登录信息
- `get_group_info` - 获取群信息
- `get_group_member_list` - 获取群成员列表
- `get_friend_list` - 获取好友列表
- `get_group_member_info` - 获取群成员信息

所有 API 调用都会返回模拟的成功响应。

## 🛠️ 命令行参数

```bash
python -m mock_napcat_adapter [OPTIONS]

选项:
  --host TEXT              监听主机地址 (默认: 127.0.0.1)
  --port INTEGER           监听端口 (默认: 3000)
  --token TEXT            WebSocket 认证 token
  --config PATH           配置文件路径 (TOML 格式)
  --message-delay FLOAT    消息发送间隔（秒） (默认: 2.0)
  --message-count INTEGER  测试消息数量 (默认: 10, 0 表示无限)
  --no-auto-send          禁用自动发送消息
  --auto-stop             在消息发送完成后自动停止
  --self-id INTEGER       模拟的机器人 QQ 号 (默认: 1234567890)
  --group-id INTEGER      模拟的群号 (默认: 987654321)
  --user-id INTEGER      模拟的用户 QQ 号 (默认: 1111111111)
  --log-level TEXT       日志级别 (默认: INFO)
```

## 📊 统计信息

```python
server = MockNapcatServer()
# ... 运行服务器 ...
stats = server.get_stats()

print(f"连接数: {stats['connections']}")
print(f"发送消息数: {stats['messages_sent']}")
print(f"接收消息数: {stats['messages_received']}")
print(f"API 调用数: {stats['api_calls']}")
print(f"服务器运行中: {stats['running']}")
print(f"当前连接: {stats['connected']}")
```

## 🔍 调试技巧

### 启用详细日志

```bash
python -m mock_napcat_adapter --log-level DEBUG
```

### 仅监听连接，不发送消息

```bash
python -m mock_napcat_adapter --no-auto-send
```

### 发送固定数量的消息后自动停止

```bash
python -m mock_napcat_adapter --message-count 5 --auto-stop
```

## 🐛 常见问题

### 端口已被占用

```bash
# 错误: ❌ 端口 3000 已被占用
# 解决方法: 使用其他端口
python -m mock_napcat_adapter --port 3001
```

### 连接超时

确保客户端连接的地址和端口与 Mock Adapter 配置一致：

```python
# Mock Adapter 监听: ws://127.0.0.1:3000
# 客户端连接: ws://127.0.0.1:3000
```

### 没有收到消息

1. 检查 `auto_send` 是否启用
2. 检查日志级别（使用 `--log-level DEBUG`）
3. 确认客户端正确订阅了 WebSocket 消息

## 📚 参考资源

- [maim_message 文档](../../README.md)
- [MaiBot-Napcat-Adapter](../../../MaiBot-Napcat-Adapter/)
- [Napcat API 文档](https://napneko.github.io/)

## 📝 许可证

本子项目遵循主项目的许可证。
