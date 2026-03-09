from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock

from app.utils import clamp01, utc_now_iso


@dataclass
class ProgressState:
    action: str = ""
    label: str = ""
    message: str = "Idle."
    unit: str = "items"
    status: str = "idle"
    current: int = 0
    total: int = 0
    percent: float = 0.0
    active: bool = False
    updated_at: str = ""


class ProgressTracker:
    def __init__(self) -> None:
        self._lock = Lock()
        self._state = ProgressState(updated_at=utc_now_iso())

    def begin(self, *, action: str, label: str, unit: str, total: int = 0, message: str = "") -> None:
        with self._lock:
            safe_total = max(0, int(total))
            self._state = ProgressState(
                action=action,
                label=label,
                message=message or f"Starting {label.lower()}...",
                unit=unit,
                status="running",
                current=0,
                total=safe_total,
                percent=0.0,
                active=True,
                updated_at=utc_now_iso(),
            )

    def update(self, *, current: int, total: int | None = None, message: str | None = None) -> None:
        with self._lock:
            if total is not None:
                self._state.total = max(0, int(total))
            self._state.current = max(0, int(current))
            if message is not None:
                self._state.message = message
            self._state.percent = self._compute_percent(self._state.current, self._state.total)
            self._state.updated_at = utc_now_iso()

    def finish(self, *, message: str, current: int | None = None, total: int | None = None) -> None:
        with self._lock:
            if total is not None:
                self._state.total = max(0, int(total))
            if current is not None:
                self._state.current = max(0, int(current))
            elif self._state.total > 0:
                self._state.current = self._state.total
            self._state.message = message
            self._state.status = "success"
            self._state.active = False
            self._state.percent = self._compute_percent(
                self._state.current,
                self._state.total,
                finished=(self._state.total == 0 or self._state.current >= self._state.total),
            )
            self._state.updated_at = utc_now_iso()

    def fail(self, *, message: str) -> None:
        with self._lock:
            self._state.message = message
            self._state.status = "error"
            self._state.active = False
            self._state.updated_at = utc_now_iso()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return asdict(self._state)

    @staticmethod
    def _compute_percent(current: int, total: int, *, finished: bool = False) -> float:
        if finished:
            return 1.0
        if total <= 0:
            return 0.0
        return clamp01(current / total)


progress_tracker = ProgressTracker()
