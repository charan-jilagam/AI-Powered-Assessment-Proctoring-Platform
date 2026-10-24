"""Evidence storage: local fallback and the Cloudinary path (SDK replaced by a fake; no network)."""
import base64
from types import SimpleNamespace

import pytest

from app import storage
from app.config import settings

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()


class FakeCloudinary:
    def __init__(self):
        self.store, self.destroyed = {}, []
        self.uploader = SimpleNamespace(upload=self.upload, destroy=self.destroy)
        self.utils = SimpleNamespace(cloudinary_url=lambda pid, **kw: (f"https://res.test/{pid}?sig=1" if kw.get("sign_url") else "", {}))

    def upload(self, raw, **kw):
        assert kw["type"] == "authenticated"          # evidence must never be publicly deliverable
        self.store[kw["public_id"]] = raw
        return {"public_id": kw["public_id"]}

    def destroy(self, pid, **kw):
        self.destroyed.append(pid)


@pytest.fixture()
def cld(monkeypatch):
    fake = FakeCloudinary()
    monkeypatch.setattr(settings, "cloudinary_cloud_name", "demo")
    monkeypatch.setattr(settings, "cloudinary_api_key", "k")
    monkeypatch.setattr(settings, "cloudinary_api_secret", "s")
    monkeypatch.setattr(storage, "_cloudinary", lambda: fake)
    return fake


def test_upload_read_delete_roundtrip(cld, monkeypatch):
    key = storage.save_image(7, 9, "face", PNG)
    assert key.startswith("cld:orvexa/7/9/face-") and len(cld.store) == 1

    import httpx
    monkeypatch.setattr(httpx, "get", lambda url, timeout: SimpleNamespace(status_code=200, content=b"IMG", headers={"content-type": "image/png; x=1"}))
    assert storage.read_image(key) == (b"IMG", "image/png")

    storage.delete_image(key)
    assert cld.destroyed == [key[4:]]


def test_cloudinary_outage_falls_back_to_local_disk(cld):
    def boom(*a, **k):
        raise RuntimeError("down")
    cld.uploader.upload = boom
    key = storage.save_image(1, 1, "periodic", PNG)
    assert not key.startswith("cld:") and storage.read_image(key)[1] == "image/png"
    storage.delete_image(key)


def test_local_storage_when_not_configured():
    assert not settings.cloudinary_enabled
    key = storage.save_image(1, 2, "id", PNG)
    assert storage.read_image(key)[0].startswith(b"\x89PNG")
    storage.delete_image(key)
    assert storage.read_image(key) is None
