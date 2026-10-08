from __future__ import annotations

import os
import queue
import signal
import threading
import time
from collections.abc import Callable
from pathlib import Path
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
        configured_limit = max_concurrent_jobs or int(os.getenv("ASTK_MAX_CONCURRENT_JOBS", "3"))
        self.max_concurrent_jobs = max(1, configured_limit)
        self.workers = min(max(1, configured_workers), self.max_concurrent_jobs)
        self.pending: queue.Queue[str] = queue.Queue()
        self._active = 0
        self._active_lock = threading.Lock()
        # Single-flight guard: never enqueue the same job_id twice at the same
        # time. Without it a re-submitted or recovered job can start a second
        # worker whose startup cleanup (shutil.rmtree(output/analysis),
        # shutil.rmtree(native)) deletes a sibling execution's in-progress
        # files and crashes it with
        # "FileNotFoundError: .../output/analysis/native/tpm".
        self._inflight: set[str] = set()
        self._inflight_lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        for index in range(self.workers):
            thread = threading.Thread(target=self._work, name=f"astk-worker-{index + 1}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def submit(self, job_id: str) -> bool:
        with self._inflight_lock:
            if job_id in self._inflight:
                return False
            self._inflight.add(job_id)
        self.pending.put(job_id)
        return True

    def stats(self) -> dict[str, int]:
        with self._active_lock:
            active = self._active
        with self._inflight_lock:
            inflight = len(self._inflight)
        return {
            "workers": self.workers,
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "running": active,
            "queued": self.pending.qsize(),
            "inflight": inflight,
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
                with self._inflight_lock:
                    self._inflight.discard(job_id)
                self.pending.task_done()


# --------------------------------------------------------------------------- #
# Orphaned-runner cleanup (Linux /proc based)
# --------------------------------------------------------------------------- #

def _read_proc(pid: int, leaf: str) -> str:
    try:
        return Path("/proc", str(pid), leaf).read_text("utf-8", "replace")
    except OSError:
        return ""


def _proc_ppid(pid: int) -> int | None:
    for line in _read_proc(pid, "status").splitlines():
        if line.startswith("PPid:"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _job_process_pids(job_dir: Path) -> list[int]:
    """Return this process's *descendant* pids that belong to a job directory.

    Used on startup to find an orphaned runner left behind when the previous
    service process was killed mid-job. The external runner is launched as
    ``bash run-astk-job.sh <job_dir>`` which then runs
    ``python3 -m backend.execute_suppa <job_dir>``; both carry the resolved
    job directory on their command line. We start from those roots and expand
    to all descendants so SUPPA2 grandchildren are cleaned up too.

    Linux-only; returns [] on platforms without /proc.
    """
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    try:
        target = str(job_dir.resolve())
    except OSError:
        target = str(job_dir)
    self_pid = os.getpid()

    children: dict[int, list[int]] = {}
    roots: list[int] = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        ppid = _proc_ppid(pid)
        if ppid is not None:
            children.setdefault(ppid, []).append(pid)
        if pid == self_pid:
            continue
        cmdline = _read_proc(pid, "cmdline").replace("\x00", " ")
        cwd = ""
        try:
            cwd = os.readlink(entry / "cwd")
        except OSError:
            cwd = ""
        if target in cmdline or cwd == target:
            roots.append(pid)

    found: set[int] = set(roots)
    stack = list(roots)
    while stack:
        parent = stack.pop()
        for child in children.get(parent, []):
            if child not in found:
                found.add(child)
                stack.append(child)
    found.discard(self_pid)
    return sorted(found)


def _terminate_job_processes(job_dir: Path, grace: float = 4.0) -> list[int]:
    """Terminate orphaned runner processes for a job dir (SIGTERM, then SIGKILL)."""
    pids = _job_process_pids(job_dir)
    if not pids:
        return []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + grace
    remaining = pids
    while time.time() < deadline:
        remaining = [pid for pid in pids if _pid_alive(pid)]
        if not remaining:
            break
        time.sleep(0.2)
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return pids


# --------------------------------------------------------------------------- #
# Startup recovery
# --------------------------------------------------------------------------- #

def recover_pending_jobs(store: Any, job_queue: JobQueue) -> list[str]:
    """Requeue jobs left behind by the previous service process.

    A job still marked "running" means the previous service process was
    interrupted mid-run (e.g. a redeploy restarted the backend). Instead of
    failing such jobs, we terminate any orphaned runner still holding the job
    directory and requeue the job so it restarts cleanly. Restarting is safe
    because run_job wipes and regenerates output/analysis for the job.

    A guard counter (recover_attempts) bounds repeated interruptions so a job
    that keeps crashing the service cannot loop forever; after
    ASTK_MAX_RECOVERY_ATTEMPTS (default 3) the job is marked failed with a
    clear message so the user can resubmit.

    Environment:
      ASTK_RECOVER_RUNNING=requeue|1|true  (default) -> requeue after cleanup
      ASTK_RECOVER_RUNNING=0|false|no|fail           -> old behavior (fail)
      ASTK_MAX_RECOVERY_ATTEMPTS=N (default 3)
    """
    recovered: list[str] = []
    mode = os.getenv("ASTK_RECOVER_RUNNING", "requeue").strip().lower()
    requeue_running = mode not in {"0", "false", "no", "fail", "off"}
    max_attempts = max(1, int(os.getenv("ASTK_MAX_RECOVERY_ATTEMPTS", "3")))

    for directory in sorted(store.root.iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        job = store.read(directory.name)
        if job is None or job.get("status") not in {"queued", "running"}:
            continue

        if job.get("status") == "running":
            if not requeue_running:
                # Opt-in legacy behavior: never auto-restart a running job.
                store.update(
                    directory.name,
                    status="failed",
                    stage="Interrupted by service restart; please resubmit",
                    error="Interrupted by service restart; please resubmit",
                )
                continue

            attempts = int(job.get("recover_attempts") or 0)
            if attempts >= max_attempts:
                store.update(
                    directory.name,
                    status="failed",
                    stage=f"Interrupted {attempts} times by service restarts; please resubmit",
                    error=f"Interrupted {attempts} times by service restarts; please resubmit",
                )
                continue

            killed = _terminate_job_processes(directory)
            if killed:
                print(f"Recovery: terminated {len(killed)} orphan process(es) for {directory.name}")
            store.update(
                directory.name,
                status="queued",
                stage="Queued after service restart",
                progress=0,
                error=None,
                recover_attempts=attempts + 1,
            )

        submitted = job_queue.submit(directory.name)
        if submitted is not False:
            recovered.append(directory.name)
    return recovered
