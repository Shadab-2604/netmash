"""
File transfer security, streaming, chunking, and validation utilities for NetMash.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path
from typing import Generator, Optional, Tuple

from netmash.config import get_app_dir

MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB max limit
CHUNK_SIZE_BYTES = 32768  # 32 KB per chunk


def get_downloads_dir() -> Path:
    """Returns and creates the dedicated NetMash downloads directory."""
    dl_dir = get_app_dir() / "downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)
    return dl_dir


def sanitize_filename(filename: str) -> str:
    """
    Sanitizes filename against directory traversal attacks (../, ..\\, etc.).
    Returns clean basename without illegal path characters.
    """
    if not filename:
        return "unnamed_file"

    # Extract base name only
    clean = os.path.basename(filename)
    # Remove directory separators or null bytes
    clean = clean.replace("/", "").replace("\\", "").replace("\x00", "")
    # Remove non-safe characters
    clean = re.sub(r'[^\w\-_\. ]', '_', clean).strip()
    return clean or "unnamed_file"


def calculate_sha256(file_path: Path) -> str:
    """Computes SHA-256 checksum of a file efficiently by streaming chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def read_file_chunks(
    file_path: Path, chunk_size: int = CHUNK_SIZE_BYTES
) -> Generator[Tuple[int, int, str], None, None]:
    """
    Yields (chunk_index, total_chunks, base64_data) for a file.
    """
    total_size = file_path.stat().st_size
    total_chunks = max(1, (total_size + chunk_size - 1) // chunk_size)

    with open(file_path, "rb") as f:
        for idx in range(total_chunks):
            raw_bytes = f.read(chunk_size)
            b64_data = base64.b64encode(raw_bytes).decode("ascii")
            yield idx, total_chunks, b64_data
