"""조회 결과 TTL 캐시."""

import hashlib
import json

from cachetools import TTLCache


class LookupCache:
    def __init__(self, maxsize: int = 500, ttl: int = 86400):
        self._cache = TTLCache(maxsize=maxsize, ttl=ttl)

    def _make_key(self, property_type: str, address: dict, year: str) -> str:
        addr_copy = {k: v for k, v in address.items() if k != "_raw"}
        raw = json.dumps(
            {"type": property_type, "addr": addr_copy, "year": year},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, property_type: str, address: dict, year: str):
        key = self._make_key(property_type, address, year)
        return self._cache.get(key)

    def set(self, property_type: str, address: dict, year: str, result):
        key = self._make_key(property_type, address, year)
        self._cache[key] = result
