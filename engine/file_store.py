"""
Content-addressed file store for uploaded invoices/bills.

Files land in `settings.UPLOAD_DIR/{sha256}.{ext}`. Re-uploads of the same
file dedupe to the same path — useful when an accountant uploads the same
invoice twice across runs.
"""
from __future__ import annotations

import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings


_EXT_BY_MIME = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}


def _ext_from(mime: str, filename: str) -> str:
    if mime in _EXT_BY_MIME:
        return _EXT_BY_MIME[mime]
    _, dot_ext = os.path.splitext(filename or "")
    return (dot_ext or ".bin").lower()


def _uploads_root() -> str:
    """Resolves UPLOAD_DIR relative to project root. Creates if missing."""
    if os.path.isabs(settings.UPLOAD_DIR):
        root = settings.UPLOAD_DIR
    else:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        root = os.path.join(project_root, settings.UPLOAD_DIR)
    os.makedirs(root, exist_ok=True)
    return root


def save_upload(file_bytes: bytes, filename: str, mime: str) -> tuple[str, str]:
    """
    Persist `file_bytes` under a content-addressed path. Idempotent.

    Returns:
        (file_hash, storage_path) where storage_path is relative to UPLOAD_DIR.
    """
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    ext = _ext_from(mime, filename)
    rel_path = f"{file_hash}{ext}"
    abs_path = os.path.join(_uploads_root(), rel_path)

    if not os.path.exists(abs_path):
        with open(abs_path, "wb") as f:
            f.write(file_bytes)
    return file_hash, rel_path


def load_file(storage_path: str) -> bytes:
    """Read a previously saved file by its storage_path (relative to UPLOAD_DIR)."""
    abs_path = os.path.join(_uploads_root(), storage_path)
    with open(abs_path, "rb") as f:
        return f.read()


def file_exists(storage_path: str) -> bool:
    return os.path.exists(os.path.join(_uploads_root(), storage_path))


def absolute_path(storage_path: str) -> str:
    """Useful for st.image / st.pdf widgets that accept absolute paths."""
    return os.path.join(_uploads_root(), storage_path)
