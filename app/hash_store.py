"""
Persistent hash store for duplicate detection.

Stores SHA256 hashes of already exported documents
to prevent duplicate processing and exports.
"""

import json
import hashlib
from pathlib import Path
from typing import Optional


class HashStore:
    def __init__(self, base_path: str) -> None:
        self.store_file = Path(base_path) / ".hashes.json"
        self.hashes = self._load()

    def _load(self) -> dict:
        if not self.store_file.exists():
            return {}
        return json.loads(self.store_file.read_text())

    def save(self) -> None:
        self.store_file.write_text(
            json.dumps(self.hashes, indent=2)
        )

    def exists(self, file_hash: str) -> bool:
        return file_hash in self.hashes

    def add(self, file_hash: str, path: str) -> None:
        self.hashes[file_hash] = path
        self.save()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()