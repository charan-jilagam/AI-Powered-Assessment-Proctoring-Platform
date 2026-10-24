"""Evidence storage (webcam snapshots).

Cloudinary when configured (private "authenticated" assets, read back through the API with a short signed URL so the
browser never gets a link), otherwise local disk. A storage key starting with ``cld:`` is a Cloudinary public_id;
anything else is a path below EVIDENCE_DIR.
"""
import base64
import binascii
import logging
import os
import re
import secrets
from typing import Optional

from app.config import settings
from app.errors import ApiError

log = logging.getLogger("orvexa.storage")
CLD_PREFIX = "cld:"
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


def _cloudinary():
    """The configured Cloudinary SDK modules (uploader, utils)."""
    import cloudinary
    import cloudinary.uploader
    import cloudinary.utils
    if not settings.cloudinary_url:
        cloudinary.config(cloud_name=settings.cloudinary_cloud_name, api_key=settings.cloudinary_api_key,
                          api_secret=settings.cloudinary_api_secret, secure=True)
    return cloudinary


def save_image(org_id: int, attempt_id: int, kind: str, data_url: str) -> str:
    raw, ext = decode_image(data_url)
    if settings.cloudinary_enabled:
        public_id = f"{settings.cloudinary_folder}/{org_id}/{attempt_id}/{kind}-{secrets.token_hex(8)}"
        try:
            res = _cloudinary().uploader.upload(raw, public_id=public_id, type="authenticated", resource_type="image",
                                                overwrite=False, unique_filename=False)
            return CLD_PREFIX + res["public_id"]
        except Exception:  # noqa: BLE001 - evidence must not be lost because the CDN had a bad moment
            log.exception("Cloudinary upload failed; keeping the image on local disk instead")
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
    if rel.startswith(CLD_PREFIX):
        return _read_cloudinary(rel[len(CLD_PREFIX):])
    try:
        full = _safe_join(rel)
        with open(full, "rb") as fh:
            data = fh.read()
    except (FileNotFoundError, ApiError):
        return None
    ext = rel.rsplit(".", 1)[-1].lower()
    return data, {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "application/octet-stream")


def _read_cloudinary(public_id: str) -> Optional[tuple[bytes, str]]:
    import httpx
    try:
        url, _ = _cloudinary().utils.cloudinary_url(public_id, type="authenticated", resource_type="image", sign_url=True, secure=True)
        resp = httpx.get(url, timeout=10.0)
    except Exception:  # noqa: BLE001
        log.exception("Cloudinary read failed")
        return None
    if resp.status_code != 200:
        return None
    return resp.content, resp.headers.get("content-type", "image/jpeg").split(";")[0]


def delete_image(rel: str) -> None:
    if rel.startswith(CLD_PREFIX):
        try:
            _cloudinary().uploader.destroy(rel[len(CLD_PREFIX):], type="authenticated", resource_type="image", invalidate=True)
        except Exception:  # noqa: BLE001
            log.exception("Cloudinary delete failed")
        return
    try:
        os.remove(_safe_join(rel))
    except (FileNotFoundError, ApiError):
        pass
