from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from backend.cleanup import cleanup_expired_jobs
    from backend.job_queue import JobQueue, recover_pending_jobs
    from backend.multipart import MultipartError, parse_multipart_stream
    from backend.runner import run_job
    from backend.store import JobStore
else:
    from .cleanup import cleanup_expired_jobs
    from .job_queue import JobQueue, recover_pending_jobs
    from .multipart import MultipartError, parse_multipart_stream
    from .runner import run_job
    from .store import JobStore


ROOT = Path(__file__).resolve().parent.parent
STORE = JobStore(ROOT / "data" / "jobs")
PUBLIC_FILES = {
    "/": ROOT / "index.html",
    "/index.html": ROOT / "index.html",
    "/app.js": ROOT / "app.js",
    "/styles.css": ROOT / "styles.css",
    "/responsive.css": ROOT / "responsive.css",
    "/github-pages.css": ROOT / "github-pages.css",
    "/sample-groups.css": ROOT / "sample-groups.css",
    "/templates/samples.csv": ROOT / "templates" / "samples.csv",
}
MAX_UPLOAD_BYTES = int(os.getenv("ASTK_MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))
RETENTION_DAYS = float(os.getenv("ASTK_RETENTION_DAYS", "7"))
CLEANUP_INTERVAL = max(60, int(os.getenv("ASTK_CLEANUP_INTERVAL", "3600")))
TRUST_PROXY = os.getenv("ASTK_TRUST_PROXY", "0").lower() in {"1", "true", "yes"}
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
    with tempfile.TemporaryDirectory() as temporary:
        fields, stored_files = parse_multipart_stream(
            io.BytesIO(body),
            len(body),
            content_type,
            Path(temporary),
            MAX_UPLOAD_BYTES,
        )
        files = [
            (safe_filename(filename), path.read_bytes())
            for filename, path in stored_files
        ]
    return fields, files


def validate_analysis_files(files: list[tuple[str, object]]) -> None:
    names = [name.lower() for name, _ in files]
    archives = [name for name in names if name.endswith(".zip")]
    sample_sheets = [name for name in names if name.endswith(".csv")]
    if len(archives) != 1 or len(sample_sheets) != 1 or len(files) != 2:
        raise ValueError("Upload exactly one ZIP data package and one CSV sample table")


def resolve_public_file(request_path: str) -> Path | None:
    return PUBLIC_FILES.get(request_path)


class ASTKHandler(SimpleHTTPRequestHandler):
    server_version = "ASTKStudio/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] [{self.client_address_label()}] {format % args}")

    def send_json(self, payload: object, status: int = 200, *, include_body: bool = True) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        if include_body:
            self.wfile.write(data)

    def client_address_label(self) -> str:
        if TRUST_PROXY:
            forwarded = self.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",", 1)[0].strip()
        return self.client_address[0]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json(
                {
                    "status": "ok",
                    "execution_mode": os.getenv("ASTK_EXECUTION_MODE", "demo"),
                    "engine_mode": os.getenv("ASTK_ENGINE", "auto"),
                    "queue": JOB_QUEUE.stats(),
                }
            )
            return
        if parsed.path == "/api/templates/samples.csv":
            self.send_download(ROOT / "templates" / "samples.csv", filename="samples.csv")
            return
        file_match = re.fullmatch(r"/api/jobs/([A-Za-z0-9-]+)/files/(.+)", parsed.path)
        if file_match:
            job_root = STORE.job_dir(file_match.group(1)).resolve()
            path = (job_root / unquote(file_match.group(2))).resolve()
            if job_root not in path.parents or not path.is_file():
                self.send_json({"error": "File not found"}, 404)
            else:
                self.send_file(path)
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
        public_file = resolve_public_file(parsed.path)
        if public_file and public_file.is_file():
            self.send_file(public_file, cache_control="public, max-age=300")
            return
        self.send_json({"error": "Not found"}, 404)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        public_file = resolve_public_file(parsed.path)
        if not public_file or not public_file.is_file():
            self.send_json({"error": "Not found"}, 404, include_body=False)
            return
        self.send_file(public_file, cache_control="public, max-age=300", include_body=False)

    def do_POST(self) -> None:
        if self.path != "/api/jobs":
            self.send_json({"error": "Not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json({"error": "Invalid Content-Length"}, 400)
            return
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self.send_json({"error": "Invalid or oversized request"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        content_type = self.headers.get("Content-Type", "")
        incoming_dir: Path | None = None
        job_id: str | None = None
        try:
            if content_type.startswith("multipart/form-data"):
                incoming_dir = Path(tempfile.mkdtemp(prefix=".upload-", dir=STORE.root))
                fields, stored_files = parse_multipart_stream(
                    self.rfile,
                    length,
                    content_type,
                    incoming_dir,
                    MAX_UPLOAD_BYTES,
                )
                config = json.loads(fields.get("config", "{}"))
                files = [(safe_filename(name), path) for name, path in stored_files]
            else:
                body = self.rfile.read(length)
                config = json.loads(body.decode("utf-8"))
                files = []
            if not isinstance(config, dict):
                raise ValueError("config must be a JSON object")
            if os.getenv("ASTK_EXECUTION_MODE", "demo").lower() == "command":
                validate_analysis_files(files)
            job_id = make_job_id()
            config["files"] = [name for name, _ in files] or config.get("files", [])
            if not files:
                config["demo"] = True
            job = STORE.create(job_id, config)
            input_dir = STORE.job_dir(job_id) / "input"
            for filename, source in files:
                if not isinstance(source, Path):
                    raise ValueError("Unexpected upload payload")
                target = input_dir / filename
                if target.exists():
                    raise ValueError(f"Duplicate uploaded filename: {filename}")
                shutil.move(str(source), str(target))
            JOB_QUEUE.submit(job_id)
            self.send_json(job, HTTPStatus.ACCEPTED)
        except (MultipartError, UnicodeDecodeError, ValueError, json.JSONDecodeError, OSError) as exc:
            if job_id:
                shutil.rmtree(STORE.job_dir(job_id), ignore_errors=True)
            self.send_json({"error": f"Invalid request: {exc}"}, 400)
        finally:
            if incoming_dir and incoming_dir.exists():
                shutil.rmtree(incoming_dir, ignore_errors=True)

    def send_download(self, path: Path, filename: str | None = None) -> None:
        if not path.exists():
            self.send_json({"error": "Report is not ready"}, 404)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename or path.name}"')
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                self.wfile.write(chunk)

    def send_file(
        self,
        path: Path,
        *,
        cache_control: str = "private, max-age=300",
        include_body: bool = True,
    ) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not include_body:
            return
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                self.wfile.write(chunk)


def main() -> None:
    host = os.getenv("ASTK_HOST", "127.0.0.1")
    port = int(os.getenv("ASTK_PORT", "4173"))
    if os.getenv("ASTK_RECOVER_JOBS", "1").lower() in {"1", "true", "yes"}:
        recovered = recover_pending_jobs(STORE, JOB_QUEUE)
        if recovered:
            print(f"Recovered {len(recovered)} pending job(s): {', '.join(recovered)}")
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
