"""Per-service circuit breaker.

After N consecutive failures against a service within the same session, short-
circuit remaining calls to that service straight to fallback — one bad API
shouldn't cascade into 10 failed requests and 10x timeout delays. State lives
on the session object; resets on next session.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_THRESHOLD = 2


@dataclass
class CircuitBreaker:
    threshold: int = DEFAULT_THRESHOLD
    _failures: dict[str, int] = field(default_factory=dict)
    _open: set[str] = field(default_factory=set)

    def is_open(self, service: str) -> bool:
        return service in self._open

    def record_failure(self, service: str) -> None:
        n = self._failures.get(service, 0) + 1
        self._failures[service] = n
        if n >= self.threshold:
            self._open.add(service)

    def record_success(self, service: str) -> None:
        self._failures[service] = 0
        self._open.discard(service)
