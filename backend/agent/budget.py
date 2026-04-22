"""Global repair budget.

One counter shared across synthesize + build + QA for a given session. The
plan calls for cap=3 so we can't stack per-phase caps of 2 into a 6-retry
worst case that takes ~5 min and burns ~$5 in API calls.

Each phase calls `try_consume(tag)` before spending a repair. When `used`
reaches `cap`, subsequent calls return False and the phase ships what it
has with an SSE 'limited repair budget reached' note.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RepairBudget:
    cap: int = 3
    used: int = 0
    trace: list[str] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.used)

    def try_consume(self, tag: str) -> bool:
        if self.used >= self.cap:
            return False
        self.used += 1
        self.trace.append(tag)
        return True
