import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from functools import wraps


_LOGGER_NAME = "manga_downloader"
_TELEMETRY_ENABLED = False
_metrics_lock = threading.Lock()
_metrics = {
    "counters": {},
    "durations": {},
}


def set_telemetry_enabled(enabled: bool):
    global _TELEMETRY_ENABLED
    _TELEMETRY_ENABLED = bool(enabled)


def telemetry_enabled() -> bool:
    return _TELEMETRY_ENABLED


def get_logger():
    return logging.getLogger(_LOGGER_NAME)


def init_logging(series_name: str = "session"):
    if not telemetry_enabled():
        return get_logger()

    logger = get_logger()
    if logger.handlers:
        return logger

    logs_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(logs_dir, exist_ok=True)

    safe_series = "_".join(str(series_name).split()).lower() if series_name else "session"
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(logs_dir, f"{safe_series}_{run_id}.log")

    level_name = os.getenv("MANGA_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False

    logger.info("logging_initialized path=%s level=%s", log_path, level_name)
    return logger


def log_event(event: str, **fields):
    if not telemetry_enabled():
        return

    logger = get_logger()
    if fields:
        kv = " ".join(f"{k}={v}" for k, v in fields.items())
        logger.info("%s %s", event, kv)
    else:
        logger.info("%s", event)


def increment_counter(name: str, value: int = 1):
    if not telemetry_enabled():
        return

    with _metrics_lock:
        _metrics["counters"][name] = _metrics["counters"].get(name, 0) + value


def record_duration(name: str, seconds: float):
    if not telemetry_enabled():
        return

    with _metrics_lock:
        stat = _metrics["durations"].setdefault(
            name,
            {"count": 0, "total": 0.0, "max": 0.0, "min": None},
        )
        stat["count"] += 1
        stat["total"] += seconds
        stat["max"] = max(stat["max"], seconds)
        stat["min"] = seconds if stat["min"] is None else min(stat["min"], seconds)


@contextmanager
def timed_block(name: str, **fields):
    if not telemetry_enabled():
        yield
        return

    start = time.perf_counter()
    if fields:
        log_event(f"{name}_start", **fields)
    else:
        log_event(f"{name}_start")

    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        record_duration(name, elapsed)
        if fields:
            log_event(f"{name}_end", duration_s=f"{elapsed:.4f}", **fields)
        else:
            log_event(f"{name}_end", duration_s=f"{elapsed:.4f}")


def timed_function(name: str = None):
    def decorator(func):
        metric_name = name or func.__name__

        @wraps(func)
        def wrapper(*args, **kwargs):
            with timed_block(metric_name):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def log_metrics_snapshot(prefix: str = "metrics_snapshot"):
    if not telemetry_enabled():
        return

    logger = get_logger()
    with _metrics_lock:
        counters_copy = dict(_metrics["counters"])
        durations_copy = {k: dict(v) for k, v in _metrics["durations"].items()}

    logger.info("%s counters=%s", prefix, counters_copy)

    for name, stat in durations_copy.items():
        avg = stat["total"] / stat["count"] if stat["count"] else 0.0
        logger.info(
            "%s duration metric=%s count=%s total_s=%.4f avg_s=%.4f min_s=%.4f max_s=%.4f",
            prefix,
            name,
            stat["count"],
            stat["total"],
            avg,
            stat["min"] if stat["min"] is not None else 0.0,
            stat["max"],
        )
