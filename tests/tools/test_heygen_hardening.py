"""HeyGen v3 hardening (H1-H4): mock-based, no network, no key, no credits.

H1 download hardening, H2 video_id / filename validation, H3 upload path and
type checks, H4 idempotency and resume. requests.get / post / put are patched.
"""
from __future__ import annotations

import json
import re
import time

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from tools.video import _shared
from tools.video.heygen_video import HeyGenVideo

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
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

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


# ---------------------------------------------------------------- H2

BAD_IDS = ["../../escaped", "a/b", "a b", "a.b", "a\nb", "ok\n", "", "x" * 65, "vid;rm", "%2e%2e", "vid?x=1", 12345, ["a"]]


@pytest.mark.parametrize("vid", ["a", "vid_1", "A-b_9", "x" * 64])
def test_h2_valid_ids_pass(vid):
    assert _shared.validate_heygen_video_id(vid) == vid


@pytest.mark.parametrize("vid", BAD_IDS)
def test_h2_invalid_ids_rejected(vid):
    with pytest.raises(ValueError):
        _shared.validate_heygen_video_id(vid)


@pytest.mark.parametrize("vid", [b for b in BAD_IDS if b])
def test_h2_extra_b_create_response_id_checked_before_poll_and_filename(flow, vid):
    """Extra (b): rejected right after create; no GET poll URL, no file written."""
    flow.create_id = vid
    out = _shared.generate_heygen_video({"prompt": "p", "output_path": str(flow.tmp / "o.mp4")})
    assert not out.success and "video_id" in out.error
    assert [c for c in flow.log if c[0] == "GET"] == []
    assert [c for c in flow.log if c[0] == "POST"][0][1].endswith("/v3/models/videos")
    assert list(flow.tmp.glob("**/*.mp4")) == []


def test_h2_poll_heygen_refuses_bad_id_without_request(flow):
    with pytest.raises(ValueError):
        _shared.poll_heygen("../../x", "k", timeout=5)
    assert flow.log == []


def test_h2_default_filename_uses_validated_id(flow, monkeypatch):
    monkeypatch.chdir(flow.tmp)
    out = _shared.generate_heygen_video({"prompt": "p"})
    assert out.success, out.error
    assert out.artifacts == ["heygen_video_vid_1.mp4"]
    assert (flow.tmp / "heygen_video_vid_1.mp4").read_bytes() == b"MP4"


# ---------------------------------------------------------------- H3

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 12
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 4


@pytest.fixture
def assets(monkeypatch, tmp_path):
    d = tmp_path / "assets_dir"
    d.mkdir()
    monkeypatch.setenv("OPENMONTAGE_ASSET_DIR", str(d))
    return d


def _posts(flow):
    return [c for c in flow.log if c[0] == "POST"]


def test_h3_path_outside_asset_dir_is_refused_and_nothing_is_sent(flow, assets):
    secret = flow.tmp / "id_rsa.png"          # right extension and magic bytes, wrong place
    secret.write_bytes(PNG)
    with pytest.raises(ValueError, match="outside"):
        _shared.upload_image_heygen(str(secret), "k")
    traversal = assets / ".." / "id_rsa.png"
    with pytest.raises(ValueError, match="outside"):
        _shared.upload_image_heygen(str(traversal), "k")
    assert flow.log == []


def test_h3_symlink_out_of_asset_dir_is_refused(flow, assets):
    target = flow.tmp / "outside.png"
    target.write_bytes(PNG)
    (assets / "link.png").symlink_to(target)
    with pytest.raises(ValueError, match="outside"):
        _shared.upload_image_heygen(str(assets / "link.png"), "k")
    assert flow.log == []


@pytest.mark.parametrize("name,data,match", [
    ("id_rsa", PNG, "only png"),
    ("notes.txt", PNG, "only png"),
    ("fake.png", b"not an image at all", "does not match"),
    ("really_png.jpg", PNG, "does not match"),
    ("empty.png", b"", "size"),
])
def test_h3_extension_magic_bytes_and_size_checks(flow, assets, name, data, match):
    p = assets / name
    p.write_bytes(data)
    with pytest.raises(ValueError, match=match):
        _shared.upload_image_heygen(str(p), "k")
    assert flow.log == []


def test_h3_size_cap(flow, assets, monkeypatch):
    p = assets / "big.png"
    p.write_bytes(PNG)
    monkeypatch.setattr(_shared, "HEYGEN_MAX_UPLOAD_BYTES", 10)
    with pytest.raises(ValueError, match="size"):
        _shared.upload_image_heygen(str(p), "k")


@pytest.mark.parametrize("name,data,ctype", [
    ("a.png", PNG, "image/png"), ("a.jpg", JPEG, "image/jpeg"),
    ("a.JPEG", JPEG, "image/jpeg"), ("a.webp", WEBP, "image/webp"),
])
def test_h3_content_type_comes_from_magic_bytes(flow, assets, name, data, ctype):
    p = assets / name
    p.write_bytes(data)
    assert _shared.upload_image_heygen(str(p), "k") == {"type": "asset_id", "asset_id": "asset_1"}
    (_, url, kw), = _posts(flow)
    assert url == "https://api.heygen.com/v3/assets"
    assert kw["files"]["file"][0] == p.name and kw["files"]["file"][2] == ctype


def _failing_assets(monkeypatch, how):
    def post(url, **kw):
        if how == "raise":
            raise ConnectionError("boom")
        return Resp({}, status=500)

    monkeypatch.setattr("requests.post", post)


@pytest.mark.parametrize("how", ["raise", "http500"])
def test_h3_fal_fallback_is_off_by_default(flow, assets, monkeypatch, how):
    p = assets / "a.png"
    p.write_bytes(PNG)
    _failing_assets(monkeypatch, how)
    monkeypatch.setattr(_shared, "upload_image_fal", lambda path: pytest.fail("public upload must not happen"))
    with pytest.raises(RuntimeError, match="HEYGEN_ALLOW_FAL_FALLBACK"):
        _shared.upload_image_heygen(str(p), "test-not-a-key")


def test_h3_fal_fallback_opt_in_is_logged(flow, assets, monkeypatch, caplog):
    p = assets / "a.png"
    p.write_bytes(PNG)
    _failing_assets(monkeypatch, "http500")
    monkeypatch.setenv("HEYGEN_ALLOW_FAL_FALLBACK", "1")
    sent = []
    monkeypatch.setattr(_shared, "upload_image_fal", lambda path: sent.append(path) or "https://fal.example/a.png")
    with caplog.at_level("WARNING"):
        out = _shared.upload_image_heygen(str(p), "test-not-a-key")
    assert out == {"type": "url", "url": "https://fal.example/a.png"}
    assert sent == [str(p.resolve())]
    assert "fal.ai" in caplog.text and "HTTP 500" in caplog.text and "test-not-a-key" not in caplog.text


def test_h3_image_to_video_flow_refuses_outside_path(flow, assets):
    secret = flow.tmp / "x.png"
    secret.write_bytes(PNG)
    with pytest.raises(ValueError, match="outside"):
        _shared.generate_heygen_video({"prompt": "p", "operation": "image_to_video",
                                       "reference_image_path": str(secret)})
    assert flow.log == []


# ---------------------------------------------------------------- H4

def _creates(flow):
    return [c for c in flow.log if c[0] == "POST" and c[1].endswith("/v3/models/videos")]


def _run(flow, **inputs):
    return _shared.generate_heygen_video({"prompt": "same prompt", "output_path": str(flow.tmp / "o.mp4"), **inputs})


def test_h4_key_fields_cover_the_create_request():
    fields = HeyGenVideo.idempotency_key_fields
    for f in ("operation", "prompt", "provider_variant", "aspect_ratio", "duration", "resolution",
              "reference_image_url", "reference_image_path"):
        assert f in fields


def test_h4_extra_a_key_changes_with_every_field():
    base = {"prompt": "p", "operation": "image_to_video", "reference_image_url": "https://x.example/a.png",
            "duration": 5, "resolution": "768p", "aspect_ratio": "16:9"}
    k = HeyGenVideo().idempotency_key
    assert k(base) == k(dict(base))
    for field, other in [("operation", "text_to_video"), ("duration", 10), ("resolution", "480p"),
                         ("aspect_ratio", "9:16"), ("prompt", "q"),
                         ("reference_image_url", "https://x.example/b.png")]:
        assert k({**base, field: other}) != k(base), field
    # omitted defaults match explicit defaults
    assert k({"prompt": "p"}) == k({"prompt": "p", "operation": "text_to_video",
                                    "provider_variant": "heygen_video_1", "aspect_ratio": "16:9"})
    assert HeyGenVideo().idempotency_key(base) == _shared.heygen_idempotency_key(base)


def test_h4_extra_a_reference_image_content_and_path_change_the_key(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(PNG + b"A")
    b.write_bytes(PNG + b"B")
    k = HeyGenVideo().idempotency_key
    inp = {"prompt": "p", "operation": "image_to_video"}
    ka = k({**inp, "reference_image_path": str(a)})
    assert ka != k({**inp, "reference_image_path": str(b)})
    a.write_bytes(PNG + b"changed")           # same path, new content
    assert ka != k({**inp, "reference_image_path": str(a)})


def test_h4_extra_a_two_image_runs_same_prompt_never_resume_the_wrong_video(flow, assets):
    a, b = assets / "a.png", assets / "b.png"
    a.write_bytes(PNG + b"A")
    b.write_bytes(PNG + b"B")
    flow.create_id = "vid_A"
    r1 = _run(flow, operation="image_to_video", reference_image_path=str(a))
    flow.create_id = "vid_B"
    r2 = _run(flow, operation="image_to_video", reference_image_path=str(b))
    assert r1.data["execution_id"] == "vid_A" and not r1.data["resumed"]
    assert r2.data["execution_id"] == "vid_B" and not r2.data["resumed"]
    assert len(_creates(flow)) == 2
    # and the same image again resumes its own video, not the other one
    flow.create_id = "vid_C"
    r3 = _run(flow, operation="image_to_video", reference_image_path=str(a))
    assert r3.data["execution_id"] == "vid_A" and r3.data["resumed"] and len(_creates(flow)) == 2


def test_h4_rerun_after_timeout_resumes_and_does_not_create_again(flow, monkeypatch):
    real_poll = _shared.poll_heygen
    calls = []

    def poll(video_id, api_key, timeout=600):
        calls.append(video_id)
        if len(calls) == 1:
            raise TimeoutError("timed out")
        return real_poll(video_id, api_key, timeout)

    monkeypatch.setattr(_shared, "poll_heygen", poll)
    with pytest.raises(TimeoutError):
        _run(flow)
    out = _run(flow)
    assert out.success and out.data["resumed"] and out.data["execution_id"] == "vid_1"
    assert len(_creates(flow)) == 1 and calls == ["vid_1", "vid_1"]


def test_h4_rerun_after_success_does_not_bill_again(flow, monkeypatch):
    monkeypatch.setenv("OPENMONTAGE_HEYGEN_STATE_DIR", str(flow.tmp / "state"))
    first = HeyGenVideo().execute({"prompt": "same prompt", "output_path": str(flow.tmp / "o.mp4")})
    second = HeyGenVideo().execute({"prompt": "same prompt", "output_path": str(flow.tmp / "o2.mp4")})
    assert first.success and second.success
    assert first.cost_usd > 0 and second.cost_usd == 0.0 and second.data["resumed"]
    assert len(_creates(flow)) == 1 and (flow.tmp / "o2.mp4").read_bytes() == b"MP4"


def test_h4_video_id_is_saved_before_polling(flow, monkeypatch):
    monkeypatch.setattr(_shared, "poll_heygen", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("t")))
    with pytest.raises(TimeoutError):
        _run(flow)
    saved = [json.loads(p.read_text()) for p in (flow.tmp / "state").glob("*.json")]
    assert len(saved) == 1 and saved[0]["video_id"] == "vid_1"


def test_h4_create_sends_idempotency_key_and_reuses_it_after_a_timed_out_create(flow, monkeypatch):
    real_post = requests.post
    state = {"n": 0}

    def post(url, **kw):
        if url.endswith("/v3/models/videos"):
            state["n"] += 1
            if state["n"] == 1:
                flow.log.append(("POST", url, kw))
                raise requests.ConnectionError("read timed out")  # accepted by HeyGen, reply lost
        return real_post(url, **kw)

    monkeypatch.setattr("requests.post", post)
    # real_post is the flow's mock, captured before this patch replaced it
    with pytest.raises(requests.ConnectionError):
        _run(flow)
    out = _run(flow)
    assert out.success
    h1, h2 = (c[2]["headers"]["Idempotency-Key"] for c in _creates(flow))
    assert h1 == h2 and re.fullmatch(r"[A-Za-z0-9_-]{1,255}", h1)


def test_h4_failed_job_is_not_resumed_and_gets_a_new_key(flow):
    flow.poll = {"status": "failed", "failure_code": "generation_failed"}
    with pytest.raises(RuntimeError, match="generation_failed"):
        _run(flow)
    flow.poll = {"status": "completed"}
    flow.create_id = "vid_2"
    out = _run(flow)
    assert out.data["execution_id"] == "vid_2" and not out.data["resumed"]
    h1, h2 = (c[2]["headers"]["Idempotency-Key"] for c in _creates(flow))
    assert h1 != h2


def test_h4_rejected_create_drops_the_saved_key(flow, monkeypatch):
    seen = []

    def post(url, **kw):
        flow.log.append(("POST", url, kw))
        seen.append(kw["headers"]["Idempotency-Key"])
        return Resp({}, status=400) if len(seen) == 1 else Resp({"data": {"video_id": "vid_1"}}, status=202)

    monkeypatch.setattr("requests.post", post)
    with pytest.raises(requests.HTTPError):
        _run(flow)
    assert _run(flow).success
    assert seen[0] != seen[1]


def test_h4_saved_job_with_bad_id_or_expired_is_ignored(flow):
    key = _shared.heygen_idempotency_key({"prompt": "same prompt"})
    path = _shared._heygen_job_path(key)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"idempotency_key": "abc", "video_id": "../../x", "created_at": time.time()}))
    assert _run(flow).data["resumed"] is False
    path.write_text(json.dumps({"idempotency_key": "abc", "video_id": "vid_old",
                                "created_at": time.time() - _shared.HEYGEN_JOB_TTL_SECONDS - 5}))
    out = _run(flow)
    assert out.data["resumed"] is False and out.data["execution_id"] == "vid_1"
    path.write_text("not json")
    assert _run(flow).data["resumed"] is False


def test_h4_resumed_job_that_no_longer_exists_is_cleared(flow, monkeypatch):
    key = _shared.heygen_idempotency_key({"prompt": "same prompt"})
    _shared._save_heygen_job(key, {"idempotency_key": "abc", "video_id": "gone", "created_at": time.time()})
    monkeypatch.setattr("requests.get", lambda url, **kw: Resp({}, status=404))
    with pytest.raises(RuntimeError, match="no longer exists"):
        _run(flow)
    assert _shared._load_heygen_job(key) is None and _creates(flow) == []


@pytest.mark.parametrize("res", ["1080p", "2k"])
def test_h4_square_text_to_video_at_1080p_or_2k_is_rejected_before_any_call(flow, res):
    out = _run(flow, aspect_ratio="1:1", resolution=res)
    assert not out.success and "16:9 or 9:16" in out.error and flow.log == []
    assert _run(flow, aspect_ratio="9:16", resolution=res).success
    assert _run(flow, aspect_ratio="1:1", resolution="768p").success
