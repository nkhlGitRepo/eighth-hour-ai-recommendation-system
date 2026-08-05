"""Structured logging for debugging and operations."""

import logging
import json
from enum import IntEnum


class LogLevel(IntEnum):
    DEBUG = 0
    INFO = 1
    WARN = 2
    ERROR = 3


class Logger:
    def __init__(self, min_level=LogLevel.INFO):
        self.min_level = min_level
        self.logger = logging.getLogger("ai_engine")

        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(levelname)s: %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        self.logger.setLevel(logging.DEBUG)

    def _log(self, level, level_name, message, data=None):
        if level < self.min_level:
            return

        if data:
            msg = f"{message} {json.dumps(data)}"
        else:
            msg = message

        if level == LogLevel.DEBUG:
            self.logger.debug(msg)
        elif level == LogLevel.INFO:
            self.logger.info(msg)
        elif level == LogLevel.WARN:
            self.logger.warning(msg)
        elif level == LogLevel.ERROR:
            self.logger.error(msg)

    def debug(self, message, data=None):
        self._log(LogLevel.DEBUG, "DEBUG", message, data)

    def info(self, message, data=None):
        self._log(LogLevel.INFO, "INFO", message, data)

    def warn(self, message, data=None):
        self._log(LogLevel.WARN, "WARN", message, data)

    def error(self, message, error=None, data=None):
        error_data = {}
        if isinstance(error, Exception):
            error_data = {
                "error_name": error.__class__.__name__,
                "error_message": str(error),
            }

        combined_data = {**error_data, **(data or {})}
        self._log(LogLevel.ERROR, "ERROR", message, combined_data if combined_data else None)


logger = Logger(LogLevel.INFO)
