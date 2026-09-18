from __future__ import annotations

import io
import re
from pathlib import Path
from typing import BinaryIO


CHUNK_SIZE = 1024 * 1024
MAX_HEADER_BYTES = 64 * 1024
MAX_FIELD_BYTES = 1024 * 1024


class MultipartError(ValueError):
    pass


def boundary_from_content_type(content_type: str) -> bytes:
    match = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type, re.IGNORECASE)
    if not match:
        raise MultipartError("Missing multipart boundary")
    value = (match.group(1) or match.group(2)).strip()
    if not value:
        raise MultipartError("Empty multipart boundary")
    try:
        return value.encode("ascii")
    except UnicodeEncodeError as error:
        raise MultipartError("Multipart boundary must be ASCII") from error


class LimitedMultipartReader:
    """Buffered reader that never reads beyond the declared HTTP body length."""

    def __init__(self, source: BinaryIO, content_length: int) -> None:
        self.source = source
        self.remaining = content_length
        self.buffer = b""

    def _fill(self) -> bool:
        if self.remaining <= 0:
            return False
        chunk = self.source.read(min(CHUNK_SIZE, self.remaining))
        if not chunk:
            self.remaining = 0
            return False
        self.remaining -= len(chunk)
        self.buffer += chunk
        return True

    def readline(self, limit: int = MAX_HEADER_BYTES) -> bytes:
        while b"\r\n" not in self.buffer:
            if len(self.buffer) > limit:
                raise MultipartError("Multipart header line is too long")
            if not self._fill():
                break
        marker = self.buffer.find(b"\r\n")
        if marker >= 0:
            line = self.buffer[: marker + 2]
            self.buffer = self.buffer[marker + 2 :]
            return line
        line = self.buffer
        self.buffer = b""
        return line

    def read_exact(self, length: int) -> bytes:
        while len(self.buffer) < length:
            if not self._fill():
                raise MultipartError("Unexpected end of multipart body")
        result = self.buffer[:length]
        self.buffer = self.buffer[length:]
        return result

    def read_until(self, delimiter: bytes, sink: BinaryIO, max_bytes: int) -> int:
        total = 0
        keep = max(0, len(delimiter) - 1)
        while True:
            marker = self.buffer.find(delimiter)
            if marker >= 0:
                chunk = self.buffer[:marker]
                sink.write(chunk)
                total += len(chunk)
                self.buffer = self.buffer[marker + len(delimiter) :]
                if total > max_bytes:
                    raise MultipartError("Multipart part is too large")
                return total
            if len(self.buffer) > keep:
                chunk = self.buffer[:-keep] if keep else self.buffer
                sink.write(chunk)
                total += len(chunk)
                self.buffer = self.buffer[-keep:] if keep else b""
                if total > max_bytes:
                    raise MultipartError("Multipart part is too large")
            if not self._fill():
                raise MultipartError("Multipart body ended before its closing boundary")


def parse_multipart_stream(
    source: BinaryIO,
    content_length: int,
    content_type: str,
    destination: Path,
    max_part_bytes: int,
) -> tuple[dict[str, str], list[tuple[str, Path]]]:
    boundary = boundary_from_content_type(content_type)
    delimiter = b"--" + boundary
    reader = LimitedMultipartReader(source, content_length)
    first_line = reader.readline()
    if first_line.rstrip(b"\r\n") != delimiter:
        raise MultipartError("Invalid multipart boundary")

    fields: dict[str, str] = {}
    files: list[tuple[str, Path]] = []
    destination.mkdir(parents=True, exist_ok=True)
    file_index = 0
    first_part = True
    while True:
        if not first_part:
            suffix = reader.read_exact(2)
            if suffix == b"--":
                break
            if suffix != b"\r\n":
                raise MultipartError("Invalid multipart part separator")
        first_part = False

        headers: list[str] = []
        while True:
            line = reader.readline()
            if line in (b"", b"\r\n", b"\n"):
                break
            headers.append(line.decode("utf-8", errors="replace"))
        disposition = next(
            (line for line in headers if line.lower().startswith("content-disposition:")),
            "",
        )
        name_match = re.search(r'name="([^"]*)"', disposition, re.IGNORECASE)
        filename_match = re.search(r'filename="([^"]*)"', disposition, re.IGNORECASE)
        if not name_match:
            raise MultipartError("Multipart part is missing a name")
        field_name = name_match.group(1)
        filename = filename_match.group(1) if filename_match else ""
        if filename:
            file_index += 1
            path = destination / f"part-{file_index}.bin"
            with path.open("wb") as output:
                reader.read_until(b"\r\n" + delimiter, output, max_part_bytes)
            files.append((filename, path))
        else:
            output = io.BytesIO()
            reader.read_until(b"\r\n" + delimiter, output, MAX_FIELD_BYTES)
            fields[field_name] = output.getvalue().decode("utf-8", errors="replace")
    return fields, files
