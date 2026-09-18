from __future__ import annotations

import os
import queue
import threading
from collections.abc import Callable
from typing import Any


class JobQueue:
    def __init__(self, worker: Callable[[str], None], workers: int | None = None) -> None:
        self.worker = worker
        self.workers = workers or int(os.getenv("ASTK_WORKERS", "1"))
        self.pending: queue.Queue[str] = queue.Queue()
        self._threads: list[threading.Thread] = []
        for index in range(self.workers):
            thread = threading.Thread(target=self._work, name=f"astk-worker-{index + 1}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def submit(self, job_id: str) -> None:
        self.pending.put(job_id)

    def stats(self) -> dict[str, int]:
        return {"workers": self.workers, "queued": self.pending.qsize()}

    def _work(self) -> None:
        while True:
            job_id = self.pending.get()
            try:
                self.worker(job_id)
            finally:
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
