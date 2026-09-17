from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path


ACTIVE_STATUSES = {"queued", "running"}


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def cleanup_expired_jobs(
    root: Path,
    retention_days: float,
    now: datetime | None = None,
) -> list[str]:
    if retention_days <= 0 or not root.exists():
        return []

    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current_time - timedelta(days=retention_days)
    removed: list[str] = []

    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        job_path = directory / "job.json"
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if job.get("pinned") or job.get("status") in ACTIVE_STATUSES:
            continue
        timestamp = parse_timestamp(job.get("updated_at")) or parse_timestamp(job.get("created_at"))
        if timestamp is None or timestamp >= cutoff:
            continue
        shutil.rmtree(directory)
        removed.append(directory.name)

    return removed
