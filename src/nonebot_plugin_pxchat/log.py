import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler

LOG_FILE = "/root/nonebot/bot1/pxchat.log"


def _write_separator(_logger: logging.Logger, label: str):
    """在日志文件中写入启动/关闭标识分隔行"""
    for handler in _logger.handlers:
        if isinstance(handler, (TimedRotatingFileHandler, logging.FileHandler)):
            try:
                with open(handler.baseFilename if hasattr(handler, 'baseFilename') else LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(f"\n{'=' * 10} {label} {'=' * 10}\n\n")
            except Exception:
                pass


def _clean_old_logs():
    """清理超过24小时的日志文件"""
    log_dir = os.path.dirname(LOG_FILE)
    if not log_dir:
        return
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
        return

    now = time.time()
    for filename in os.listdir(log_dir):
        if filename.startswith("pxchat.log"):
            filepath = os.path.join(log_dir, filename)
            if os.path.isfile(filepath):
                file_mtime = os.path.getmtime(filepath)
                if now - file_mtime > 86400:  # 24小时
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass


def setup_logger() -> logging.Logger:
    """初始化pxchat专用日志记录器，输出到文件并保留24小时"""
    _logger = logging.getLogger("pxchat")
    _logger.setLevel(logging.DEBUG)

    if not _logger.handlers:
        try:
            log_dir = os.path.dirname(LOG_FILE)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

            # 文件handler：每24小时轮转，不保留备份
            file_handler = TimedRotatingFileHandler(
                LOG_FILE,
                when='H',
                interval=24,
                backupCount=0,
                encoding='utf-8'
            )
            file_handler.suffix = "%Y-%m-%d_%H-%M-%S"
            file_handler.setLevel(logging.DEBUG)

            formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(formatter)
            _logger.addHandler(file_handler)

            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            _logger.addHandler(console_handler)

            _clean_old_logs()
        except Exception as e:
            # 无法创建文件日志时回退到纯控制台
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                '%(asctime)s - pxchat - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            console_handler.setFormatter(formatter)
            _logger.addHandler(console_handler)
            _logger.warning(f"无法创建日志文件 {LOG_FILE}，使用控制台输出: {e}")

    _logger.propagate = False

    # 写入启动标识
    _write_separator(_logger, "PXCHAT START")
    _logger.info("pxchat 插件启动")

    return _logger


def log_shutdown(_logger: logging.Logger):
    """写入关闭标识"""
    _logger.info("pxchat 插件关闭")
    _write_separator(_logger, "PXCHAT STOP")


# 全局日志实例
logger = setup_logger()
