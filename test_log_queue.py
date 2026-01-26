"""测试日志队列系统在工作线程中的使用"""

import asyncio
import queue
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / "src"))

from maim_message.log_queue import (
    LoggerProxy,
    LogQueueProcessor,
    LogLevel,
    create_log_queue,
)
from maim_message.message import APIMessageBase


async def test_log_queue():
    print("=== 开始测试日志队列 ===", flush=True)

    class MockLogger:
        def __init__(self):
            self.logs = []

        def log(self, level, message):
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[MOCK LOGGER][{timestamp}][{level}] {message}", flush=True)
            self.logs.append(
                {"level": level, "message": message, "timestamp": timestamp}
            )

        def opt(self, **kwargs):
            return self

    mock_logger = MockLogger()

    log_queue = create_log_queue(maxsize=100)

    processor = LogQueueProcessor(
        log_queue=log_queue,
        real_logger=mock_logger,
        batch_size=5,
        batch_timeout=0.2,
    )

    await processor.start()
    print("✓ 日志处理器已启动", flush=True)

    proxy = LoggerProxy(log_queue, "MainThread")
    print("✓ LoggerProxy 已创建", flush=True)

    print("\n--- 测试 1: 主线程日志 ---", flush=True)
    proxy.info("主线程 INFO 日志")
    proxy.debug("主线程 DEBUG 日志")
    proxy.warning("主线程 WARNING 日志")
    proxy.error("主线程 ERROR 日志")
    proxy.success("主线程 SUCCESS 日志")

    await asyncio.sleep(0.5)

    print("\n--- 测试 2: 工作线程日志 ---", flush=True)

    def worker_thread_function(log_queue_proxy, stop_event):
        print("[工作线程] 工作线程已启动", flush=True)

        log_queue_proxy.info("工作线程 INFO 日志")
        log_queue_proxy.debug("工作线程 DEBUG 日志")
        log_queue_proxy.warning("工作线程 WARNING 日志")
        log_queue_proxy.error("工作线程 ERROR 日志")
        log_queue_proxy.success("工作线程 SUCCESS 日志")

        try:
            raise ValueError("测试异常")
        except Exception as e:
            log_queue_proxy.exception("捕获到异常", exception=e)

        bound_logger = log_queue_proxy.bind(module_name="WorkerModule")
        bound_logger.info("绑定了额外信息的日志")

        for i in range(5):
            if stop_event.is_set():
                break
            log_queue_proxy.info(f"工作线程循环日志 {i}")
            time.sleep(0.1)

        print("[工作线程] 工作线程即将退出", flush=True)

    import threading

    stop_event = threading.Event()

    worker_thread = threading.Thread(
        target=worker_thread_function, args=(proxy, stop_event), daemon=True
    )
    worker_thread.start()
    print("✓ 工作线程已启动", flush=True)

    await asyncio.sleep(1.0)
    stop_event.set()
    worker_thread.join(timeout=2.0)
    print("✓ 工作线程已退出", flush=True)

    print("\n--- 测试 3: 批量日志 ---", flush=True)
    for i in range(20):
        proxy.info(f"批量日志 {i}")

    await asyncio.sleep(1.0)

    await processor.stop()
    print("✓ 日志处理器已停止", flush=True)

    print(f"\n=== 测试完成 ===", flush=True)
    print(f"总共处理日志: {len(mock_logger.logs)} 条", flush=True)
    print(f"日志类型分布:", flush=True)
    level_count = {}
    for log in mock_logger.logs:
        level = log["level"]
        level_count[level] = level_count.get(level, 0) + 1
    for level, count in sorted(level_count.items()):
        print(f"  - {level}: {count} 条", flush=True)

    expected_logs = 5 + 6 + 1 + 5 + 20
    actual_logs = len(mock_logger.logs)

    if actual_logs >= expected_logs * 0.9:
        print(f"\n✅ 测试通过！处理了 {actual_logs}/{expected_logs} 条日志", flush=True)
        return True
    else:
        print(
            f"\n❌ 测试失败！只处理了 {actual_logs}/{expected_logs} 条日志", flush=True
        )
        return False


async def main():
    success = await test_log_queue()
    if success:
        print("\n所有测试通过！日志队列系统工作正常。", flush=True)
        sys.exit(0)
    else:
        print("\n测试失败！请检查日志队列系统。", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
