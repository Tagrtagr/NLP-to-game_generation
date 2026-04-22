from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

PhaseName = Literal["design", "assets", "synthesize", "build", "qa"]
Status = Literal["start", "progress", "done", "error"]


class Event(BaseModel):
    phase: PhaseName
    step: str
    status: Status
    detail: str = ""
    payload: dict[str, Any] | None = None

    def sse(self) -> str:
        import json

        return f"data: {json.dumps(self.model_dump(exclude_none=True))}\n\n"
