"""极简进程内 TTL 缓存：单容器多 worker 下各自缓存，适合读多写少聚合接口。"""

import threading
import time
from typing import Any, Callable, Optional

_CACHE: dict[str, tuple[float, Any]] = {}
_LOCK = threading.Lock()
DEFAULT_TTL = 15.0


def cache_enabled() -> bool:
    import os
    return os.getenv("AGVPM_ENABLE_CACHE") == "1"


def cache_get(key: str) -> Optional[Any]:
    with _LOCK:
        item = _CACHE.get(key)
        if item is None:
            return None
        expire_at, value = item
        if time.monotonic() > expire_at:
            _CACHE.pop(key, None)
            return None
        return value


def cache_set(key: str, value: Any, ttl: float = DEFAULT_TTL) -> None:
    with _LOCK:
        _CACHE[key] = (time.monotonic() + ttl, value)
        # 简单防膨胀：超过 500 条时清理过期项
        if len(_CACHE) > 500:
            now = time.monotonic()
            for k, (expire_at, _) in list(_CACHE.items()):
                if now > expire_at:
                    _CACHE.pop(k, None)


def cache_clear(prefix: str = "") -> None:
    with _LOCK:
        if not prefix:
            _CACHE.clear()
        else:
            for key in list(_CACHE):
                if key.startswith(prefix):
                    _CACHE.pop(key, None)


def cached(ttl: float = DEFAULT_TTL):
    """装饰器：按参数生成 key，避免重复聚合计算。"""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args, **kwargs) -> Any:
            key_parts = [func.__name__]
            for arg in args:
                key_parts.append(str(getattr(arg, "id", arg)))
            for k, v in sorted(kwargs.items()):
                key_parts.append(f"{k}={getattr(v, 'id', v)}")
            key = ":".join(key_parts)
            hit = cache_get(key)
            if hit is not None:
                return hit
            value = func(*args, **kwargs)
            cache_set(key, value, ttl)
            return value
        return wrapper
    return decorator
