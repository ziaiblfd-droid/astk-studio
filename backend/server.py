from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from backend.cleanup import cleanup_expired_jobs
    from backend.job_queue import JobQueue
    from backend.runner import run_job
    from backend.store import JobStore
else:
    from .cleanup import cleanup_expired_jobs
    from .job_queue import JobQueue
    from .runner import run_job
    from .store import JobStore


ROOT = Path(__file__).resolve().parent.parent
STORE = JobStore(ROOT / "data" / "jobs")
MAX_UPLOAD_BYTES = int(os.getenv("ASTK_MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))
RETENTION_DAYS = float(os.getenv("ASTK_RETENTION_DAYS", "7"))
CLEANUP_INTERVAL = max(60, int(os.getenv("ASTK_CLEANUP_INTERVAL", "3600")))
JOB_QUEUE = JobQueue(lambda job_id: run_job(STORE, job_id))


def cleanup_loop() -> None:
    while True:
        try:
            removed = cleanup_expired_jobs(STORE.root, RETENTION_DAYS)
            if removed:
                print(f"Removed {len(removed)} expired job(s): {', '.join(removed)}")
        except Exception as exc:
            print(f"Job cleanup failed: {exc}", file=sys.stderr)
        time.sleep(CLEANUP_INTERVAL)


def make_job_id() -> str:
    stamp = datetime.now().strftime("%y%m%d-%H%M%S")
    return f"ASTK-{stamp}-{secrets.token_hex(2).upper()}"


def safe_filename(value: str) -> str:
    name = Path(value).name.replace("\x00", "")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name) or "upload.bin"


def parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], list[tuple[str, bytes]]]:
    match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type)
    if not match:
        raise ValueError("Missing multipart boundary")
    boundary = (match.group(1) or match.group(2)).encode("ascii")
    fields: dict[str, str] = {}
    files: list[tuple[str, bytes]] = []
    for part in body.split(b"--" + boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--" or b"\r\n\r\n" not in part:
            continue
        header_bytes, payload = part.split(b"\r\n\r\n", 1)
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        headers = header_bytes.decode("utf-8", errors="replace")
        name_match = re.search(r'name="([^"]+)"', headers)
        filename_match = re.search(r'filename="([^"]*)"', headers)
        if not name_match:
            continue
        if filename_match and filename_match.group(1):
            files.append((safe_filename(filename_match.group(1)), payload))
        else:
            fields[name_match.group(1)] = payload.decode("utf-8", errors="replace")
    return fields, files


class ASTKHandler(SimpleHTTPRequestHandler):
    server_version = "ASTKStudio/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def send_json(self, payload: object, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"status": "ok", "execution_mode": os.getenv("ASTK_EXECUTION_MODE", "demo"), "queue": JOB_QUEUE.stats()})
            return
        if parsed.path == "/api/templates/samples.csv":
            self.send_download(ROOT / "templates" / "samples.csv", filename="samples.csv")
            return
        job_match = re.fullmatch(r"/api/jobs/([A-Za-z0-9-]+)", parsed.path)
        if job_match:
            job = STORE.read(job_match.group(1))
            self.send_json(job if job else {"error": "Job not found"}, 200 if job else 404)
            return
        results_match = re.fullmatch(r"/api/jobs/([A-Za-z0-9-]+)/results", parsed.path)
        if results_match:
            path = STORE.job_dir(results_match.group(1)) / "output" / "results.json"
            if not path.exists():
                self.send_json({"error": "Results are not ready"}, 404)
            else:
                self.send_json(json.loads(path.read_text(encoding="utf-8")))
            return
        download_match = re.fullmatch(r"/api/jobs/([A-Za-z0-9-]+)/download", parsed.path)
        if download_match:
            self.send_download(STORE.job_dir(download_match.group(1)) / "astk-report.zip")
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path != "/api/jobs":
            self.send_json({"error": "Not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self.send_json({"error": "Invalid or oversized request"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        try:
            if content_type.startswith("multipart/form-data"):
                fields, files = parse_multipart(body, content_type)
                config = json.loads(fields.get("config", "{}"))
            else:
                config = json.loads(body.decode("utf-8"))
                files = []
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": f"Invalid request: {exc}"}, 400)
            return
        job_id = make_job_id()
        config["files"] = [name for name, _ in files] or config.get("files", [])
        if not files:
            config["demo"] = True
        job = STORE.create(job_id, config)
        input_dir = STORE.job_dir(job_id) / "input"
        for filename, payload in files:
            (input_dir / filename).write_bytes(payload)
        JOB_QUEUE.submit(job_id)
        self.send_json(job, HTTPStatus.ACCEPTED)

    def send_download(self, path: Path, filename: str | None = None) -> None:
        if not path.exists():
            self.send_json({"error": "Report is not ready"}, 404)
            return
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename or path.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    host = os.getenv("ASTK_HOST", "127.0.0.1")
    port = int(os.getenv("ASTK_PORT", "4173"))
    server = ThreadingHTTPServer((host, port), ASTKHandler)
    cleanup_thread = threading.Thread(target=cleanup_loop, name="astk-cleanup", daemon=True)
    cleanup_thread.start()
    print(f"ASTK Studio running at http://{host}:{port}")
    print(f"Execution mode: {os.getenv('ASTK_EXECUTION_MODE', 'demo')}")
    print(f"Job retention: {RETENTION_DAYS:g} day(s)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
