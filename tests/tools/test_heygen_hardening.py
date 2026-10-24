"""HeyGen v3 hardening (H1-H4): mock-based, no network, no key, no credits.

H1 download hardening, H2 video_id / filename validation, H3 upload path and
type checks, H4 idempotency and resume. requests.get / post / put are patched.
"""
from __future__ import annotations

import pytest
from requests.structures import CaseInsensitiveDict

from tools.video import _shared

GOOD_URL = "https://resource2.heygen.ai/v/clip.mp4"


class Resp:
    def __init__(self, payload=None, status=200, chunks=(b"MP4",), headers=None):
        self._p, self.status_code, self._chunks = payload or {}, status, list(chunks)
        self.headers = CaseInsensitiveDict(headers or {})
        self.closed = False

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1):
        yield from self._chunks

    def close(self):
        self.closed = True


@pytest.fixture
def flow(monkeypatch, tmp_path):
    """Mock the whole create / poll / download flow. flow.create_id and
    flow.video_url can be changed per test; flow.log records every call."""
    monkeypatch.setenv("HEYGEN_API_KEY", "test-not-a-key")
    monkeypatch.setenv("OPENMONTAGE_HEYGEN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("HEYGEN_ALLOW_FAL_FALLBACK", raising=False)
    monkeypatch.setattr(_shared.time, "sleep", lambda s: None)

    class Flow:
        create_id = "vid_1"
        video_url = GOOD_URL
        poll = {"status": "completed"}
        log = []

    f = Flow()
    f.log = []

    def post(url, **kw):
        f.log.append(("POST", url, kw))
        if url.endswith("/v3/assets"):
            return Resp({"data": {"asset_id": "asset_1"}})
        return Resp({"data": {"status": "pending", "video_id": f.create_id}}, status=202)

    def get(url, **kw):
        f.log.append(("GET", url, kw))
        if url.startswith("https://api.heygen.com/"):
            return Resp({"data": {**f.poll, "video_url": f.video_url}})
        return Resp(chunks=[b"MP4"])

    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr("requests.get", get)
    monkeypatch.setattr("requests.put", lambda *a, **k: pytest.fail("unexpected PUT"))
    f.tmp = tmp_path
    return f


# ---------------------------------------------------------------- H1

def _get_returning(monkeypatch, resp):
    seen = []

    def get(url, **kw):
        seen.append((url, kw))
        return resp(url) if callable(resp) else resp

    monkeypatch.setattr("requests.get", get)
    return seen


@pytest.mark.parametrize("url", [
    "http://resource2.heygen.ai/v.mp4",           # not https
    "https://169.254.169.254/latest/meta-data",   # internal host
    "https://evil.example/v.mp4",                 # foreign host
    "https://heygen.ai.evil.example/v.mp4",       # suffix trick
    "https://nothygen.ai/v.mp4",                  # suffix without dot boundary
    "file:///etc/passwd",
])
def test_h1_download_refuses_bad_scheme_or_host(monkeypatch, tmp_path, url):
    seen = _get_returning(monkeypatch, Resp())
    with pytest.raises(ValueError, match="Refusing"):
        _shared.download_heygen_video(url, tmp_path / "o.mp4")
    assert seen == [] and not (tmp_path / "o.mp4").exists()


def test_h1_download_streams_without_key_and_no_redirect_follow(monkeypatch, tmp_path):
    seen = _get_returning(monkeypatch, Resp(chunks=[b"ab", b"cd"], headers={"Content-Type": "video/mp4"}))
    n = _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4")
    assert n == 4 and (tmp_path / "o.mp4").read_bytes() == b"abcd"
    kw = seen[0][1]
    assert kw["stream"] is True and kw["allow_redirects"] is False
    assert "headers" not in kw or not kw["headers"]
    assert not list(tmp_path.glob("*.part"))


def test_h1_download_size_cap_stream_and_declared_length(monkeypatch, tmp_path):
    _get_returning(monkeypatch, Resp(chunks=[b"x" * 6, b"x" * 6]))
    with pytest.raises(ValueError, match="exceeded"):
        _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4", max_bytes=10)
    assert not (tmp_path / "o.mp4").exists() and not list(tmp_path.glob("*.part"))

    _get_returning(monkeypatch, Resp(headers={"Content-Length": "11"}))
    with pytest.raises(ValueError, match="larger"):
        _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4", max_bytes=10)


def test_h1_download_rejects_html_content_type(monkeypatch, tmp_path):
    _get_returning(monkeypatch, Resp(headers={"Content-Type": "text/html"}))
    with pytest.raises(ValueError, match="content type"):
        _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4")


def test_h1_redirect_to_foreign_host_is_refused(monkeypatch, tmp_path):
    seen = _get_returning(monkeypatch, Resp(status=302, headers={"Location": "http://169.254.169.254/x"}))
    with pytest.raises(ValueError, match="Refusing"):
        _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4")
    assert len(seen) == 1


def test_h1_redirect_within_allowlist_is_followed(monkeypatch, tmp_path):
    def resp(url):
        if url == GOOD_URL:
            return Resp(status=302, headers={"Location": "https://files.heygen.com/real.mp4"})
        return Resp(chunks=[b"ok"])

    seen = _get_returning(monkeypatch, resp)
    _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4")
    assert [u for u, _ in seen] == [GOOD_URL, "https://files.heygen.com/real.mp4"]


def test_h1_extra_host_env_is_exact_match(monkeypatch, tmp_path):
    monkeypatch.setenv("HEYGEN_EXTRA_DOWNLOAD_HOSTS", "cdn.example")
    _get_returning(monkeypatch, Resp())
    _shared.download_heygen_video("https://cdn.example/v.mp4", tmp_path / "o.mp4")
    with pytest.raises(ValueError, match="Refusing"):
        _shared.download_heygen_video("https://sub.cdn.example/v.mp4", tmp_path / "p.mp4")


def test_h1_flow_refuses_internal_video_url(flow):
    flow.video_url = "http://169.254.169.254/latest/meta-data"
    with pytest.raises(ValueError, match="Refusing"):
        _shared.generate_heygen_video({"prompt": "p", "output_path": str(flow.tmp / "o.mp4")})
    assert not (flow.tmp / "o.mp4").exists()
    assert not any(c[1].startswith("http://169") for c in flow.log)
