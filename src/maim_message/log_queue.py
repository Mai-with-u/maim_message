"""线程安全的日志队列系统

用于在工作线程中使用自定义 logger，通过队列传递日志消息到主线程协程中处理。
解决 loguru logger 在跨线程使用时的线程安全问题。
"""

import asyncio
import inspect
import queue
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class LogLevel(Enum):
    TRACE = 0
    DEBUG = 10
    INFO = 20
    SUCCESS = 25
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


@dataclass
class LogMessage:
    level: LogLevel
    message: str
    exception: Optional[Exception] = None
    extra: Optional[Dict[str, Any]] = None
    filename: Optional[str] = None
    function: Optional[str] = None
    line: Optional[int] = None
    timestamp: Optional[float] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

    @classmethod
    def from_frame(
        cls,
        level: LogLevel,
        message: str,
        exception: Optional[Exception] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        frame = inspect.currentframe()
        if frame:
            frame = frame.f_back
            if frame:
                frame = frame.f_back

        if frame:
            filename = frame.f_code.co_filename
            function = frame.f_code.co_name
            line = frame.f_lineno
        else:
            filename = None
            function = None
            line = None

        return cls(
            level=level,
            message=message,
            exception=exception,
            extra=extra,
            filename=filename,
            function=function,
            line=line,
        )


class LoggerProxy:
    """日志代理 - 在工作线程中使用，将日志调用转换为消息放入队列

    使用方法：
        proxy = LoggerProxy(log_queue, "WorkerThread")
        proxy.info("这是一条日志")
        proxy.error("发生错误", exception=e)
    """

    def __init__(
        self,
        log_queue: "queue.Queue[LogMessage]",
        logger_name: str = "maim_message_worker",
    ):
        self._queue = log_queue
        self._logger_name = logger_name

    def _log(
        self,
        level: LogLevel,
        message: str,
        exception: Optional[Exception] = None,
        **kwargs,
    ) -> None:
        try:
            extra = kwargs if kwargs else None
            log_msg = LogMessage.from_frame(
                level=level,
                message=message,
                exception=exception,
                extra=extra,
            )
            self._queue.put_nowait(log_msg)
        except Exception as e:
            print(
                f"[{self._logger_name}] Failed to queue log: {e} | {message}",
                file=sys.stderr,
            )

    def trace(self, message: str, **kwargs) -> None:
        self._log(LogLevel.TRACE, message, **kwargs)

    def debug(self, message: str, **kwargs) -> None:
        self._log(LogLevel.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        self._log(LogLevel.INFO, message, **kwargs)

    def success(self, message: str, **kwargs) -> None:
        self._log(LogLevel.SUCCESS, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        self._log(LogLevel.WARNING, message, **kwargs)

    def error(
        self, message: str, exception: Optional[Exception] = None, **kwargs
    ) -> None:
        self._log(LogLevel.ERROR, message, exception=exception, **kwargs)

    def critical(
        self, message: str, exception: Optional[Exception] = None, **kwargs
    ) -> None:
        self._log(LogLevel.CRITICAL, message, exception=exception, **kwargs)

    def exception(self, message: str, **kwargs) -> None:
        exc_type, exc_value, exc_tb = sys.exc_info()

        exc_arg = kwargs.pop("exception", None)

        if exc_arg is not None:
            self._log(LogLevel.ERROR, message, exc_arg, **kwargs)
        elif exc_value and isinstance(exc_value, Exception):
            self._log(LogLevel.ERROR, message, exc_value, **kwargs)
        else:
            self._log(LogLevel.ERROR, message, **kwargs)

    def bind(self, **kwargs) -> "LoggerProxy":
        return _BoundLoggerProxy(self, kwargs)


class _BoundLoggerProxy(LoggerProxy):
    def __init__(self, parent_proxy: LoggerProxy, bound_extra: Dict[str, Any]):
        self._queue = parent_proxy._queue
        self._logger_name = parent_proxy._logger_name
        self._bound_extra = bound_extra

    def _log(
        self,
        level: LogLevel,
        message: str,
        exception: Optional[Exception] = None,
        **kwargs,
    ) -> None:
        merged_extra = {}
        if self._bound_extra:
            merged_extra.update(self._bound_extra)
        if kwargs:
            merged_extra.update(kwargs)

        try:
            log_msg = LogMessage.from_frame(
                level=level,
                message=message,
                exception=exception,
                extra=merged_extra,
            )
            self._queue.put_nowait(log_msg)
        except Exception as e:
            print(
                f"[{self._logger_name}] Failed to queue log: {e} | {message}",
                file=sys.stderr,
            )


class LogQueueProcessor:
    """日志队列处理器 - 在主线程协程中运行，从队列取出并实际记录日志

    使用方法：
        processor = LogQueueProcessor(log_queue, custom_logger)
        await processor.start()
        # ... 处理其他任务 ...
        await processor.stop()
    """

    # loguru 级别映射
    LEVEL_MAP = {
        LogLevel.TRACE: "TRACE",
        LogLevel.DEBUG: "DEBUG",
        LogLevel.INFO: "INFO",
        LogLevel.SUCCESS: "SUCCESS",
        LogLevel.WARNING: "WARNING",
        LogLevel.ERROR: "ERROR",
        LogLevel.CRITICAL: "CRITICAL",
    }

    def __init__(
        self,
        log_queue: "queue.Queue[LogMessage]",
        real_logger: Any,  # loguru logger
        batch_size: int = 10,
        batch_timeout: float = 0.1,
    ):
        self._queue = log_queue
        self._real_logger = real_logger
        self._batch_size = batch_size
        self._batch_timeout = batch_timeout
        self._running = False
        self._processor_task: Optional[asyncio.Task] = None

    async def _process_log_message(self, log_msg: LogMessage) -> None:
        """处理单个日志消息"""
        try:
            # 检测 logger 类型：loguru 或 structlog/stdlib logging
            logger_type = type(self._real_logger).__module__

            # 转换级别到标准logging级别
            level_map_std = {
                LogLevel.TRACE: 5,  # logging.NOTSET + 5
                LogLevel.DEBUG: logging.DEBUG,
                LogLevel.INFO: logging.INFO,
                LogLevel.SUCCESS: logging.INFO,
                LogLevel.WARNING: logging.WARNING,
                LogLevel.ERROR: logging.ERROR,
                LogLevel.CRITICAL: logging.CRITICAL,
            }

            # 构建位置信息（如果存在）
            extra_info = {}
            if log_msg.extra:
                extra_info.update(log_msg.extra)

            # 处理 loguru logger
            if logger_type == "loguru" or logger_type.startswith("loguru."):
                level_str = self.LEVEL_MAP.get(log_msg.level, "INFO")

                # 使用 loguru 的 bind/opt 方法设置额外信息
                if extra_info:
                    logger = self._real_logger.bind(**extra_info)
                else:
                    logger = self._real_logger

                # 记录日志
                if log_msg.exception:
                    logger.log(level_str, f"{log_msg.message}", exc_info=True)
                else:
                    logger.log(level_str, log_msg.message)

            # 处理 structlog/stdlib logger
            else:
                level_std = level_map_std.get(log_msg.level, logging.INFO)

                # 使用标准 logging API
                if extra_info:
                    # structlog logger 支持 .bind() 或直接传 kwargs
                    if hasattr(self._real_logger, "bind"):
                        logger = self._real_logger.bind(**extra_info)
                        logger.log(level_std, log_msg.message)
                    else:
                        # 标准 stdlib logger
                        self._real_logger.log(
                            level_std, log_msg.message, extra=extra_info
                        )
                else:
                    # 没有 extra_info，直接记录
                    self._real_logger.log(level_std, log_msg.message)

        except Exception as e:
            # 处理失败时不影响主流程，只打印到 stderr
            print(
                f"[LogQueueProcessor] Failed to process log: {e} | {log_msg.message}",
                file=sys.stderr,
            )

    async def _process_batch(self) -> None:
        batch = []

        try:
            first_msg = await asyncio.to_thread(self._queue.get)
            batch.append(first_msg)

            while len(batch) < self._batch_size:
                try:
                    msg = self._queue.get_nowait()
                    batch.append(msg)
                except queue.Empty:
                    break

        except asyncio.CancelledError:
            return
        except Exception:
            pass

        if batch:
            for log_msg in batch:
                await self._process_log_message(log_msg)

    async def _processor_loop(self) -> None:
        """处理器循环"""
        self._running = True
        print(f"[LogQueueProcessor DEBUG] Processor loop started", file=sys.stderr)
        loop_count = 0
        while self._running:
            try:
                loop_count += 1
                print(
                    f"[LogQueueProcessor DEBUG] Loop iteration {loop_count}, queue size: {self._queue.qsize()}",
                    file=sys.stderr,
                )
                await self._process_batch()
            except asyncio.CancelledError:
                print(
                    f"[LogQueueProcessor DEBUG] Processor loop cancelled",
                    file=sys.stderr,
                )
                break

    async def start(self) -> None:
        """启动日志处理器"""
        if self._running:
            return
        self._processor_task = asyncio.create_task(self._processor_loop())

    async def stop(self) -> None:
        """停止日志处理器"""
        self._running = False
        if self._processor_task:
            # 取消任务
            self._processor_task.cancel()
            try:
                await asyncio.wait_for(self._processor_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

            self._processor_task = None

        # 处理队列中剩余的消息
        await self._drain_queue()

    async def _drain_queue(self) -> None:
        """清空队列中的剩余消息"""
        while not self._queue.empty():
            try:
                msg = self._queue.get_nowait()
                await self._process_log_message(msg)
            except queue.Empty:
                break
            except Exception as e:
                print(f"[LogQueueProcessor] Error draining queue: {e}", file=sys.stderr)

    def is_running(self) -> bool:
        """检查处理器是否在运行"""
        return self._running


def create_log_queue(maxsize: int = 1000) -> "queue.Queue[LogMessage]":
    """创建日志队列

    Args:
        maxsize: 队列最大大小，默认 1000

    Returns:
        日志队列实例
    """
    return queue.Queue(maxsize=maxsize)
