from __future__ import annotations

from threading import Lock, Thread
from typing import Callable


class JobRunner:
    def __init__(self) -> None:
        self._lock = Lock()
        self._active = False

    def start(self, fn: Callable[[], None]) -> bool:
        with self._lock:
            if self._active:
                return False
            self._active = True

        def run() -> None:
            try:
                fn()
            finally:
                with self._lock:
                    self._active = False

        Thread(target=run, daemon=True).start()
        return True

    def is_active(self) -> bool:
        with self._lock:
            return self._active


job_runner = JobRunner()
