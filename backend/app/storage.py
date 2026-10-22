"""Evidence storage (webcam snapshots). Local disk by default; the interface is small so S3 can replace it."""
import base64
import binascii
import os
import re
import secrets
from typing import Optional

from app.config import settings
from app.errors import ApiError

_DATA_URL = re.compile(r"^data:image/(jpeg|jpg|png|webp);base64,(.+)$", re.DOTALL)
_MAGIC = {
    "jpeg": (b"\xff\xd8\xff",),
    "jpg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "webp": (b"RIFF",),
}


def decode_image(data_url: str) -> tuple[bytes, str]:
    """Validate a browser data URL and return (bytes, extension). Never trusts the declared type."""
    match = _DATA_URL.match(data_url.strip()) if isinstance(data_url, str) else None
    if not match:
        raise ApiError(400, "Unsupported image format", "bad_image")
    kind, payload = match.group(1), match.group(2)
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(400, "Corrupt image data", "bad_image")
    if len(raw) > settings.max_image_bytes:
        raise ApiError(413, "Image is too large", "image_too_large")
    if not any(raw.startswith(sig) for sig in _MAGIC[kind]):
        raise ApiError(400, "Image content does not match its type", "bad_image")
    return raw, ("jpg" if kind in ("jpeg", "jpg") else kind)


def save_image(org_id: int, attempt_id: int, kind: str, data_url: str) -> str:
    raw, ext = decode_image(data_url)
    rel = os.path.join(str(org_id), str(attempt_id), f"{kind}-{secrets.token_hex(8)}.{ext}")
    full = _safe_join(rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(raw)
    return rel.replace(os.sep, "/")


def _safe_join(rel: str) -> str:
    base = os.path.realpath(settings.evidence_dir)
    full = os.path.realpath(os.path.join(base, rel))
    if not full.startswith(base + os.sep):
        raise ApiError(400, "Invalid evidence path", "bad_path")
    return full


def read_image(rel: str) -> Optional[tuple[bytes, str]]:
    try:
        full = _safe_join(rel)
        with open(full, "rb") as fh:
            data = fh.read()
    except (FileNotFoundError, ApiError):
        return None
    ext = rel.rsplit(".", 1)[-1].lower()
    return data, {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "application/octet-stream")


def delete_image(rel: str) -> None:
    try:
        os.remove(_safe_join(rel))
    except (FileNotFoundError, ApiError):
        pass
