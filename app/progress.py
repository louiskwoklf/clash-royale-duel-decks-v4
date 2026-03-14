from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Condition

from app.utils import clamp01, utc_now_iso


class StopRequested(RuntimeError):
    pass


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
    stoppable: bool = False
    updated_at: str = ""


class ProgressTracker:
    def __init__(self) -> None:
        self._condition = Condition()
        self._state = ProgressState(updated_at=utc_now_iso())
        self._version = 0

    def begin(
        self,
        *,
        action: str,
        label: str,
        unit: str,
        current: int = 0,
        total: int = 0,
        message: str = "",
        stoppable: bool = False,
    ) -> None:
        with self._condition:
            safe_total = max(0, int(total))
            safe_current = max(0, int(current))
            if safe_total > 0:
                safe_current = min(safe_current, safe_total)
            self._state = ProgressState(
                action=action,
                label=label,
                message=message or f"Starting {label.lower()}...",
                unit=unit,
                status="running",
                current=safe_current,
                total=safe_total,
                percent=self._compute_percent(safe_current, safe_total),
                active=True,
                stoppable=stoppable,
                updated_at="",
            )
            self._publish()

    def update(self, *, current: int, total: int | None = None, message: str | None = None) -> None:
        with self._condition:
            if total is not None:
                self._state.total = max(0, int(total))
            self._state.current = max(0, int(current))
            if message is not None:
                self._state.message = message
            self._state.percent = self._compute_percent(self._state.current, self._state.total)
            self._publish()

    def finish(self, *, message: str, current: int | None = None, total: int | None = None) -> None:
        with self._condition:
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
            self._publish()

    def fail(self, *, message: str) -> None:
        with self._condition:
            self._state.message = message
            self._state.status = "error"
            self._state.active = False
            self._publish()

    def request_stop(self) -> bool:
        with self._condition:
            if not self._state.active or not self._state.stoppable:
                return False
            if self._state.status == "stopping":
                return True
            if self._state.status != "running":
                return False
            self._state.status = "stopping"
            self._publish()
            return True

    def raise_if_stopped(self) -> None:
        with self._condition:
            if self._state.active and self._state.stoppable and self._state.status == "stopping":
                raise StopRequested()

    def stop(self, *, message: str, current: int | None = None, total: int | None = None) -> None:
        with self._condition:
            if total is not None:
                self._state.total = max(0, int(total))
            if current is not None:
                self._state.current = max(0, int(current))
            self._state.message = message
            self._state.status = "stopped"
            self._state.active = False
            self._state.percent = self._compute_percent(self._state.current, self._state.total)
            self._publish()

    def snapshot(self) -> dict[str, object]:
        with self._condition:
            return asdict(self._state)

    def wait_for_update(self, after_version: int, timeout: float | None = None) -> tuple[int, dict[str, object]] | None:
        with self._condition:
            if after_version < 0 or self._version < after_version:
                return self._version, asdict(self._state)
            if self._version <= after_version:
                notified = self._condition.wait(timeout=timeout)
                if not notified and self._version <= after_version:
                    return None
            return self._version, asdict(self._state)

    def _publish(self) -> None:
        self._version += 1
        self._state.updated_at = utc_now_iso()
        self._condition.notify_all()

    @staticmethod
    def _compute_percent(current: int, total: int, *, finished: bool = False) -> float:
        if finished:
            return 1.0
        if total <= 0:
            return 0.0
        return clamp01(current / total)


progress_tracker = ProgressTracker()
