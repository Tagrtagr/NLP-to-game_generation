"""Per-session background pipeline + event queue.

Decouples pipeline lifecycle from SSE connection. The POST /api/generate
endpoint starts a session and returns immediately-streamed events drained
from a queue; a GET /api/stream/{sid} endpoint lets a reconnecting client
resume the same stream. A disconnect no longer cancels the pipeline.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field

from .events import Event
from .pipeline import run_pipeline


@dataclass
class Session:
    sid: str
    task: asyncio.Task | None = None
    history: deque[tuple[str, str]] = field(default_factory=lambda: deque(maxlen=2000))
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    done: bool = False

    def publish(self, event: str, data: str) -> None:
        self.history.append((event, data))
        for q in self.subscribers:
            q.put_nowait((event, data))


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def start(self, sid: str, prompt: str) -> Session:
        sess = Session(sid=sid)
        self._sessions[sid] = sess
        sess.task = asyncio.create_task(self._run(sess, prompt))
        return sess

    def get(self, sid: str) -> Session | None:
        return self._sessions.get(sid)

    async def _run(self, sess: Session, prompt: str) -> None:
        sess.publish("session", sess.sid)
        try:
            async for ev in run_pipeline(sess.sid, prompt):
                sess.publish("phase", ev.model_dump_json(exclude_none=True))
        except asyncio.CancelledError:
            sess.publish(
                "phase",
                '{"phase":"design","step":"pipeline","status":"error",'
                '"detail":"cancelled by user"}',
            )
            raise
        except Exception as e:
            sess.publish(
                "phase",
                f'{{"phase":"design","step":"pipeline","status":"error",'
                f'"detail":"unhandled: {type(e).__name__}: {e}"}}',
            )
        finally:
            sess.done = True
            sess.publish("done", sess.sid)

    def cancel(self, sid: str) -> bool:
        sess = self._sessions.get(sid)
        if sess is None or sess.task is None or sess.done:
            return False
        sess.task.cancel()
        return True

    async def stream(self, sid: str) -> "asyncio.Queue | None":
        """Subscribe to a session; replays history then yields live events."""
        sess = self._sessions.get(sid)
        if sess is None:
            return None
        q: asyncio.Queue = asyncio.Queue()
        for ev, data in sess.history:
            q.put_nowait((ev, data))
        if not sess.done:
            sess.subscribers.append(q)
        else:
            q.put_nowait(None)  # sentinel: stream end
        return q


MANAGER = SessionManager()
