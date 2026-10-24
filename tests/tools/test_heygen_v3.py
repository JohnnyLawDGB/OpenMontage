"""HeyGen v3 migration: mock-based check that no v1/v2 endpoint is called.

HeyGen retires REST API v1 and v2 on Oct 31, 2026. These tests patch
requests.get / requests.post / requests.put, so no network and no key.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

import pytest

from tools.video import _shared
from tools.video.heygen_video import HeyGenVideo

LEGACY = re.compile(r"heygen\.com/v[12]/")
REPO = Path(__file__).resolve().parents[2]


class Resp:
    def __init__(self, payload=None, status=200, content=b"MP4"):
        self._p, self.status_code, self.content = payload or {}, status, content
        self.headers = {}

    def iter_content(self, chunk_size=1):
        yield self.content

    def close(self):
        pass

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def calls(monkeypatch):
    monkeypatch.setenv("HEYGEN_API_KEY", "test-not-a-key")
    monkeypatch.setattr(_shared.time, "sleep", lambda s: None)
    log = []
    polls = iter([{"data": {"status": "pending"}},
                  {"data": {"status": "completed", "video_url": "https://resource2.heygen.ai/v.mp4"}}])

    def post(url, **kw):
        log.append(("POST", url, kw))
        if url.endswith("/v3/assets"):
            return Resp({"data": {"asset_id": "asset_1", "url": "https://files.example/a.png"}})
        return Resp({"data": {"status": "pending", "video_id": "vid_1"}}, status=202)

    def get(url, **kw):
        log.append(("GET", url, kw))
        if "resource2.heygen.ai" in url:
            return Resp(content=b"MP4")
        return Resp(next(polls))

    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr("requests.get", get)
    monkeypatch.setattr("requests.put", lambda *a, **k: pytest.fail("no presigned PUT in v3 path"))
    return log


def test_text_to_video_uses_v3_models_videos(calls, tmp_path):
    out = tmp_path / "o.mp4"
    r = HeyGenVideo().execute({"prompt": "a coin", "output_path": str(out)})
    assert r.success, r.error
    post = [c for c in calls if c[0] == "POST"][0]
    assert post[1] == "https://api.heygen.com/v3/models/videos"
    assert post[2]["json"] == {"model": "heygen-video-1", "mode": "text_to_video",
                               "prompt": "a coin", "aspect_ratio": "16:9"}
    assert [c[1] for c in calls if c[0] == "GET"][:2] == ["https://api.heygen.com/v3/models/videos/vid_1"] * 2
    assert out.read_bytes() == b"MP4"
    assert not any(LEGACY.search(c[1]) for c in calls)


def test_image_to_video_uploads_via_v3_assets(calls, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMONTAGE_ASSET_DIR", str(tmp_path))
    img = tmp_path / "f.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 8)
    r = HeyGenVideo().execute({"prompt": "zoom", "operation": "image_to_video",
                               "reference_image_path": str(img), "output_path": str(tmp_path / "o.mp4")})
    assert r.success, r.error
    posts = [c for c in calls if c[0] == "POST"]
    assert posts[0][1] == "https://api.heygen.com/v3/assets" and "files" in posts[0][2]
    assert posts[1][2]["json"]["image"] == {"type": "asset_id", "asset_id": "asset_1"}
    assert "aspect_ratio" not in posts[1][2]["json"]
    assert not any(LEGACY.search(c[1]) for c in calls)


def test_legacy_provider_variant_is_refused_without_calling_heygen(calls):
    r = HeyGenVideo().execute({"prompt": "x", "provider_variant": "veo_3_1"})
    assert not r.success and "v3" in r.error
    assert calls == []


def test_failed_status_raises(monkeypatch):
    monkeypatch.setattr(_shared.time, "sleep", lambda s: None)
    monkeypatch.setattr("requests.get", lambda *a, **k: Resp({"data": {"status": "failed", "failure_code": "generation_failed"}}))
    with pytest.raises(RuntimeError, match="generation_failed"):
        _shared.poll_heygen("vid_1", "k", timeout=5)


def test_no_v1_or_v2_heygen_endpoint_left_in_code():
    hits = []
    for p in list((REPO / "tools").rglob("*.py")) + list((REPO / "lib").rglob("*.py")):
        for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            if LEGACY.search(line):
                hits.append(f"{p.relative_to(REPO)}:{n}")
    assert hits == []
