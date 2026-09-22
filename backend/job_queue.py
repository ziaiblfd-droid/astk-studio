from __future__ import annotations

import os
import queue
import threading
from collections.abc import Callable
from typing import Any


class JobQueue:
    def __init__(
        self,
        worker: Callable[[str], None],
        workers: int | None = None,
        max_concurrent_jobs: int | None = None,
    ) -> None:
        self.worker = worker
        configured_workers = workers or int(os.getenv("ASTK_WORKERS", "1"))
        configured_limit = max_concurrent_jobs or int(os.getenv("ASTK_MAX_CONCURRENT_JOBS", "10"))
        self.max_concurrent_jobs = max(1, configured_limit)
        self.workers = min(max(1, configured_workers), self.max_concurrent_jobs)
        self.pending: queue.Queue[str] = queue.Queue()
        self._active = 0
        self._active_lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        for index in range(self.workers):
            thread = threading.Thread(target=self._work, name=f"astk-worker-{index + 1}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def submit(self, job_id: str) -> None:
        self.pending.put(job_id)

    def stats(self) -> dict[str, int]:
        with self._active_lock:
            active = self._active
        return {
            "workers": self.workers,
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "running": active,
            "queued": self.pending.qsize(),
        }

    def _work(self) -> None:
        while True:
            job_id = self.pending.get()
            with self._active_lock:
                self._active += 1
            try:
                self.worker(job_id)
            finally:
                with self._active_lock:
                    self._active -= 1
                self.pending.task_done()


def recover_pending_jobs(store: Any, job_queue: JobQueue) -> list[str]:
    recovered: list[str] = []
    for directory in sorted(store.root.iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        job = store.read(directory.name)
        if job is None or job.get("status") not in {"queued", "running"}:
            continue
        if job.get("status") == "running":
            store.update(
                directory.name,
                status="queued",
                stage="Queued after service restart",
                progress=0,
                error=None,
            )
        job_queue.submit(directory.name)
        recovered.append(directory.name)
    return recovered
