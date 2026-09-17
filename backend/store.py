from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def create(self, job_id: str, config: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        job = {
            "id": job_id,
            "status": "queued",
            "progress": 0,
            "stage": "Queued",
            "created_at": now,
            "updated_at": now,
            "config": config,
            "stages": [],
            "error": None,
        }
        directory = self.job_dir(job_id)
        (directory / "input").mkdir(parents=True, exist_ok=True)
        (directory / "output").mkdir(parents=True, exist_ok=True)
        self.write(job_id, job)
        return job

    def read(self, job_id: str) -> dict[str, Any] | None:
        path = self.job_dir(job_id) / "job.json"
        if not path.exists():
            return None
        with self._lock:
            return json.loads(path.read_text(encoding="utf-8"))

    def write(self, job_id: str, job: dict[str, Any]) -> None:
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        path = self.job_dir(job_id) / "job.json"
        temporary = path.with_suffix(".json.tmp")
        with self._lock:
            temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)

    def update(self, job_id: str, **changes: Any) -> dict[str, Any]:
        job = self.read(job_id)
        if job is None:
            raise KeyError(job_id)
        job.update(changes)
        self.write(job_id, job)
        return job
