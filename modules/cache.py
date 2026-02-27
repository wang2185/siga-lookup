"""조회 결과 TTL 캐시 (스레드 안전)."""

import hashlib
import json
from threading import Lock

from cachetools import TTLCache


class LookupCache:
    def __init__(self, maxsize: int = 2000, ttl: int = 604800):
        self._cache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = Lock()

    def _make_key(self, property_type: str, address: dict, year: str) -> str:
        addr_copy = {k: v for k, v in address.items() if k != "_raw"}
        raw = json.dumps(
            {"type": property_type, "addr": addr_copy, "year": year},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, property_type: str, address: dict, year: str):
        key = self._make_key(property_type, address, year)
        with self._lock:
            return self._cache.get(key)

    def set(self, property_type: str, address: dict, year: str, result):
        key = self._make_key(property_type, address, year)
        with self._lock:
            self._cache[key] = result
