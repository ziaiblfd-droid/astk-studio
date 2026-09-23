from __future__ import annotations

import json
import math
import re
import secrets
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO


class UploadError(ValueError):
    pass


class UploadStore:
    ID_PATTERN = re.compile(r"UPL-[A-Za-z0-9-]+")

    def __init__(
        self,
        root: Path,
        *,
        max_upload_bytes: int,
        chunk_size: int,
        retention_seconds: int = 86400,
        max_sessions: int = 20,
    ) -> None:
        self.root = root
        self.max_upload_bytes = max_upload_bytes
        self.chunk_size = chunk_size
        self.retention_seconds = retention_seconds
        self.max_sessions = max_sessions
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def safe_filename(value: object) -> str:
        name = Path(str(value or "")).name.replace("\x00", "")
        return re.sub(r"[^A-Za-z0-9._-]+", "_", name) or "upload.bin"

    def _session_dir(self, upload_id: str) -> Path:
        if not self.ID_PATTERN.fullmatch(upload_id):
            raise UploadError("Invalid upload ID")
        return self.root / upload_id

    def _metadata_path(self, upload_id: str) -> Path:
        return self._session_dir(upload_id) / "upload.json"

    def _read(self, upload_id: str) -> dict[str, object]:
        path = self._metadata_path(upload_id)
        if not path.is_file():
            raise UploadError("Upload session not found")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UploadError("Upload session is invalid") from exc

    def create(self, files: object) -> dict[str, object]:
        if not isinstance(files, list) or len(files) != 2:
            raise UploadError("Upload exactly one ZIP data package and one CSV sample table")

        normalized: list[dict[str, object]] = []
        total_size = 0
        seen: set[str] = set()
        for index, item in enumerate(files):
            if not isinstance(item, dict):
                raise UploadError("Invalid upload file metadata")
            name = self.safe_filename(item.get("name"))
            key = name.lower()
            if key in seen:
                raise UploadError(f"Duplicate uploaded filename: {name}")
            seen.add(key)
            try:
                size = int(item.get("size", 0))
            except (TypeError, ValueError) as exc:
                raise UploadError(f"Invalid size for {name}") from exc
            if size <= 0:
                raise UploadError(f"Uploaded file is empty: {name}")
            total_size += size
            normalized.append(
                {
                    "index": index,
                    "name": name,
                    "size": size,
                    "chunks": math.ceil(size / self.chunk_size),
                }
            )

        names = [str(item["name"]).lower() for item in normalized]
        if sum(name.endswith(".zip") for name in names) != 1 or sum(name.endswith(".csv") for name in names) != 1:
            raise UploadError("Upload exactly one ZIP data package and one CSV sample table")
        if total_size > self.max_upload_bytes:
            raise UploadError("Upload exceeds the configured size limit")

        with self._lock:
            active = sum(1 for path in self.root.iterdir() if path.is_dir())
            if active >= self.max_sessions:
                raise UploadError("Too many uploads are currently in progress; try again later")
            stamp = datetime.now(timezone.utc).strftime("%y%m%d-%H%M%S")
            upload_id = f"UPL-{stamp}-{secrets.token_hex(8).upper()}"
            directory = self._session_dir(upload_id)
            (directory / "parts").mkdir(parents=True)
            metadata = {
                "id": upload_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "chunk_size": self.chunk_size,
                "total_size": total_size,
                "files": normalized,
            }
            self._metadata_path(upload_id).write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return metadata

    def file_names(self, upload_id: str) -> list[str]:
        metadata = self._read(upload_id)
        return [str(item["name"]) for item in metadata["files"]]

    def write_chunk(
        self,
        upload_id: str,
        file_index: int,
        chunk_index: int,
        reader: BinaryIO,
        content_length: int,
    ) -> dict[str, int]:
        metadata = self._read(upload_id)
        files = metadata.get("files")
        if not isinstance(files, list) or file_index < 0 or file_index >= len(files):
            raise UploadError("Invalid upload file index")
        file_info = files[file_index]
        if not isinstance(file_info, dict):
            raise UploadError("Invalid upload metadata")
        chunk_count = int(file_info["chunks"])
        if chunk_index < 0 or chunk_index >= chunk_count:
            raise UploadError("Invalid upload chunk index")
        file_size = int(file_info["size"])
        expected = min(self.chunk_size, file_size - chunk_index * self.chunk_size)
        if content_length != expected:
            raise UploadError(f"Chunk size mismatch: expected {expected}, received {content_length}")

        parts = self._session_dir(upload_id) / "parts"
        target = parts / f"{file_index:02d}-{chunk_index:06d}.part"
        temporary = parts / f".{target.name}.{threading.get_ident()}.tmp"
        remaining = content_length
        with temporary.open("wb") as handle:
            while remaining:
                block = reader.read(min(64 * 1024, remaining))
                if not block:
                    temporary.unlink(missing_ok=True)
                    raise UploadError("Upload chunk ended early")
                handle.write(block)
                remaining -= len(block)
        temporary.replace(target)
        return {"file_index": file_index, "chunk_index": chunk_index, "bytes": content_length}

    def assemble(self, upload_id: str, destination: Path) -> list[str]:
        with self._lock:
            metadata = self._read(upload_id)
            files = metadata.get("files")
            if not isinstance(files, list):
                raise UploadError("Invalid upload metadata")
            parts = self._session_dir(upload_id) / "parts"
            for file_info in files:
                if not isinstance(file_info, dict):
                    raise UploadError("Invalid upload metadata")
                file_index = int(file_info["index"])
                for chunk_index in range(int(file_info["chunks"])):
                    part = parts / f"{file_index:02d}-{chunk_index:06d}.part"
                    if not part.is_file():
                        raise UploadError(
                            f"Upload is incomplete: missing chunk {chunk_index + 1} for {file_info['name']}"
                        )

            destination.mkdir(parents=True, exist_ok=True)
            names: list[str] = []
            for file_info in files:
                file_index = int(file_info["index"])
                name = str(file_info["name"])
                target = destination / name
                temporary = destination / f".{name}.uploading"
                with temporary.open("wb") as output:
                    for chunk_index in range(int(file_info["chunks"])):
                        part = parts / f"{file_index:02d}-{chunk_index:06d}.part"
                        with part.open("rb") as source:
                            shutil.copyfileobj(source, output, length=1024 * 1024)
                if temporary.stat().st_size != int(file_info["size"]):
                    temporary.unlink(missing_ok=True)
                    raise UploadError(f"Assembled file size mismatch: {name}")
                temporary.replace(target)
                names.append(name)

            shutil.rmtree(self._session_dir(upload_id))
            return names

    def cleanup_expired(self, now: datetime | None = None) -> list[str]:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        cutoff = current - timedelta(seconds=self.retention_seconds)
        removed: list[str] = []
        with self._lock:
            for directory in self.root.iterdir():
                if not directory.is_dir():
                    continue
                try:
                    modified = datetime.fromtimestamp(directory.stat().st_mtime, tz=timezone.utc)
                except OSError:
                    continue
                if modified >= cutoff:
                    continue
                shutil.rmtree(directory, ignore_errors=True)
                removed.append(directory.name)
        return removed
