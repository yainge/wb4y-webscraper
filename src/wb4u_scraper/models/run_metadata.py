from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid


@dataclass
class RunMetadata:
    run_id: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
    )
    started_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at_utc: str | None = None
    status: str = "running"  # running | completed | failed
    record_count: int = 0
    error_message: str | None = None

    def mark_complete(self, record_count: int = 0) -> None:
        self.finished_at_utc = datetime.now(timezone.utc).isoformat()
        self.status = "completed"
        self.record_count = record_count

    def mark_failed(self, error: str) -> None:
        self.finished_at_utc = datetime.now(timezone.utc).isoformat()
        self.status = "failed"
        self.error_message = error


def create_run_metadata() -> RunMetadata:
    return RunMetadata()
