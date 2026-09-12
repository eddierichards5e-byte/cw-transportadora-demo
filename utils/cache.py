from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Hashable, Optional, Tuple


class TTLCache:
    """Cache em memória com expiração simples e invalidação por namespace."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: Dict[Tuple[str, Hashable], Tuple[float, Any]] = {}

    def get(self, namespace: str, key: Hashable) -> Optional[Any]:
        now = time.monotonic()
        with self._lock:
            item = self._data.get((namespace, key))
            if not item:
                return None

            expires_at, value = item
            if expires_at < now:
                self._data.pop((namespace, key), None)
                return None

            return value

    def set(self, namespace: str, key: Hashable, value: Any, ttl_seconds: float) -> Any:
        expires_at = time.monotonic() + max(0.0, ttl_seconds)
        with self._lock:
            self._data[(namespace, key)] = (expires_at, value)
        return value

    def get_or_set(
        self,
        namespace: str,
        key: Hashable,
        factory: Callable[[], Any],
        ttl_seconds: float,
    ) -> Any:
        cached = self.get(namespace, key)
        if cached is not None:
            return cached

        value = factory()
        return self.set(namespace, key, value, ttl_seconds)

    def invalidate_namespace(self, namespace: str) -> None:
        with self._lock:
            keys = [key for key in self._data if key[0] == namespace]
            for key in keys:
                self._data.pop(key, None)

    def invalidate(self, namespace: str, key: Hashable) -> None:
        with self._lock:
            self._data.pop((namespace, key), None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


runtime_cache = TTLCache()
