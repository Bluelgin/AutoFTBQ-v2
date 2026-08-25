"""Persistent diagnostics for UI callbacks and background workers."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import threading


LOGGER_NAME = "autoftbq.v2"


def configure_logging(root_dir: str) -> tuple[logging.Logger, str]:
    log_dir = os.path.join(root_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "autoftbq_v2.log")
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    if not any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
        handler = RotatingFileHandler(
            log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s"
        ))
        logger.addHandler(handler)
    logger.propagate = False
    return logger, log_path


def install_exception_hooks(logger: logging.Logger) -> None:
    previous_sys_hook = sys.excepthook

    def sys_hook(exc_type, exc_value, exc_traceback):
        logger.critical("Unhandled application exception", exc_info=(exc_type, exc_value, exc_traceback))
        previous_sys_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = sys_hook

    previous_thread_hook = getattr(threading, "excepthook", None)

    def thread_hook(args):
        logger.critical(
            "Unhandled thread exception in %s",
            getattr(args.thread, "name", "unknown"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        if previous_thread_hook:
            previous_thread_hook(args)

    if previous_thread_hook:
        threading.excepthook = thread_hook
