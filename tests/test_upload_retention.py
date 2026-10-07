from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.upload_store import UploadStore


class UploadRetentionTests(unittest.TestCase):
    def test_cleanup_uses_latest_chunk_activity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "uploads"
            session = root / "UPL-RECENT"
            parts = session / "parts"
            parts.mkdir(parents=True)
            now = datetime(2026, 10, 7, tzinfo=timezone.utc)
            created = now.timestamp() - 13 * 60 * 60
            active = now.timestamp() - 11 * 60 * 60
            os.utime(session, (created, created))
            os.utime(parts, (active, active))
            store = UploadStore(
                root,
                max_upload_bytes=1024,
                chunk_size=4,
                retention_seconds=12 * 60 * 60,
            )

            self.assertEqual(store.cleanup_expired(now), [])

            os.utime(parts, (created, created))
            self.assertEqual(store.cleanup_expired(now), ["UPL-RECENT"])


if __name__ == "__main__":
    unittest.main()
