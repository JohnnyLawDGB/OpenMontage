"""HeyGen v3 hardening (H1-H4): mock-based, no network, no key, no credits.

H1 download hardening, H2 video_id / filename validation, H3 upload path and
type checks, H4 idempotency and resume. requests.get / post / put are patched.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from tools.video import _shared
from tools.video.heygen_video import HeyGenVideo

GOOD_URL = "https://resource2.heygen.ai/v/clip.mp4"
_REAL_SLEEP = time.sleep   # the flow fixture replaces time.sleep with a no-op
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 20   # an mp4 header: bytes 4-8 are ftyp


class Resp:
    def __init__(self, payload=None, status=200, chunks=(MP4,), headers=None):
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
        return Resp(chunks=[MP4])

    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr("requests.get", get)
    monkeypatch.setattr("requests.put", lambda *a, **k: pytest.fail("unexpected PUT"))
    f.tmp = tmp_path
    f.out = tmp_path / "out"
    f.out.mkdir()
    monkeypatch.setenv("OPENMONTAGE_ASSET_DIR", str(f.out))
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
    seen = _get_returning(monkeypatch, Resp(chunks=[MP4[:7], MP4[7:]], headers={"Content-Type": "video/mp4"}))
    n = _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4")
    assert n == len(MP4) and (tmp_path / "o.mp4").read_bytes() == MP4
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
        return Resp(chunks=[MP4])

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
        _shared.generate_heygen_video({"prompt": "p", "output_path": str(flow.out / "o.mp4")})
    assert not (flow.out / "o.mp4").exists()
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
    out = _shared.generate_heygen_video({"prompt": "p", "output_path": str(flow.out / "o.mp4")})
    assert not out.success and "video_id" in out.error
    assert [c for c in flow.log if c[0] == "GET"] == []
    assert [c for c in flow.log if c[0] == "POST"][0][1].endswith("/v3/models/videos")
    assert list(flow.tmp.glob("**/*.mp4")) == []


def test_h2_poll_heygen_refuses_bad_id_without_request(flow):
    with pytest.raises(ValueError):
        _shared.poll_heygen("../../x", "k", timeout=5)
    assert flow.log == []


def test_h2_default_filename_uses_validated_id(flow, monkeypatch):
    monkeypatch.setattr(_shared, "_heygen_default_output_dir", lambda: flow.out)
    out = _shared.generate_heygen_video({"prompt": "p"})
    assert out.success, out.error
    assert out.artifacts == [str((flow.out / "heygen_video_vid_1.mp4").resolve())]
    assert (flow.out / "heygen_video_vid_1.mp4").read_bytes() == MP4


# ---------------------------------------------------------------- H3

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 12
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 4


@pytest.fixture
def assets(monkeypatch, tmp_path):
    d = tmp_path / "assets_dir"
    d.mkdir()
    monkeypatch.setenv("OPENMONTAGE_ASSET_DIR", os.pathsep.join(filter(None, [os.environ.get("OPENMONTAGE_ASSET_DIR"), str(d)])))
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
    return _shared.generate_heygen_video({"prompt": "same prompt", "output_path": str(flow.out / "o.mp4"), **inputs})


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


def test_h4_extra_a_reference_image_content_and_path_change_the_key(assets):
    a, b = assets / "a.png", assets / "b.png"
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
    first = HeyGenVideo().execute({"prompt": "same prompt", "output_path": str(flow.out / "o.mp4")})
    second = HeyGenVideo().execute({"prompt": "same prompt", "output_path": str(flow.out / "o2.mp4")})
    assert first.success and second.success
    assert first.cost_usd > 0 and second.cost_usd == 0.0 and second.data["resumed"]
    assert len(_creates(flow)) == 1 and (flow.out / "o2.mp4").read_bytes() == MP4


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


# ------------------------------------------------ Security flag F1: host parser differential

F1_BAD = [
    "https://evil.tld\\@heygen.ai/v.mp4",
    "https://127.0.0.1:1\\@heygen.ai/v.mp4?X-Amz-Signature=a",
    "https://evil.tld@heygen.ai/v.mp4",
    "https://heygen.ai:evil@evil.tld/v.mp4",
    "https://user:pw@resource2.heygen.ai/v.mp4",
    "https://heygen.ai:8443/v.mp4",
    "https://resource2.heygen.ai:80/v.mp4",
    "https://heygen.ai./v.mp4",             # trailing dot
    "https://a..heygen.ai/v.mp4",           # empty label
    "https://.heygen.ai/v.mp4",
    "https://evil.tld\t.heygen.ai/v.mp4",
    "https://evil.tld\x00.heygen.ai/v.mp4",
    "https://evil.tld\n.heygen.ai/v.mp4",
    "https:// heygen.ai/v.mp4",
    "https://resource2.heygen.ai/v mp4",
    "https://resource2.heygen.ai/v\\x.mp4",
    "https://heygen。ai/v.mp4",
    "https://hеygen.ai/v.mp4",              # cyrillic e
    "https://ｈｅｙｇｅｎ.ai/v.mp4",
    "https://heygen.ai%40evil.tld/v.mp4",
    "https://heygen.ai%2eevil.tld/v.mp4",
    "https://evil.tld#@heygen.ai/v.mp4",
    "https://evil.tld?@heygen.ai/v.mp4",
    "https://heygen.com.evil.tld/v.mp4",
    "https://evilheygen.com/v.mp4",
    "https://127.0.0.1/v.mp4",
    "https://[::1]/v.mp4",
    "https://2130706433/v.mp4",
    "https://169.254.169.254/latest/meta-data/",
    "//resource2.heygen.ai/v.mp4",
    "resource2.heygen.ai/v.mp4",
    "HTTP://resource2.heygen.ai/v.mp4",
]
F1_GOOD = [
    "https://resource2.heygen.ai/v.mp4?X-Amz-Signature=a%40b&Expires=1",
    "https://RESOURCE2.HeyGen.AI/v.mp4",
    "https://files.heygen.ai:443/video/abc123.mp4",
    "https://x.heygen.com/ok",
    "https://heygen.ai/v.mp4",
]


@pytest.mark.parametrize("url", F1_BAD)
def test_f1_initial_url_is_refused_without_a_request(monkeypatch, tmp_path, url):
    seen = _get_returning(monkeypatch, Resp())
    with pytest.raises(ValueError, match="Refusing"):
        _shared.download_heygen_video(url, tmp_path / "o.mp4")
    assert seen == [] and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("url", [u for u in F1_BAD if "://" in u and not u.startswith("//")])
def test_f1_same_strings_as_redirect_location_are_refused(monkeypatch, tmp_path, url):
    seen = _get_returning(monkeypatch, Resp(status=302, headers={"Location": url}))
    with pytest.raises(ValueError, match="Refusing"):
        _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4")
    assert [u for u, _ in seen] == [GOOD_URL]


@pytest.mark.parametrize("url", F1_GOOD)
def test_f1_normal_signed_urls_still_pass(monkeypatch, tmp_path, url):
    seen = _get_returning(monkeypatch, Resp())
    _shared.download_heygen_video(url, tmp_path / "o.mp4")
    assert [u for u, _ in seen] == [url]


@pytest.mark.parametrize("url", F1_BAD + F1_GOOD)
def test_f1_accepted_urls_have_one_host_for_both_parsers(url):
    from urllib.parse import urlsplit
    from urllib3.util import parse_url

    if _shared._heygen_download_url_ok(url):
        assert (parse_url(url).host or "").lower() == urlsplit(url).hostname.lower()


def test_f1_the_known_differential_is_real_and_is_caught():
    from urllib.parse import urlsplit
    from urllib3.util import parse_url

    url = "https://evil.tld\\@heygen.ai/v.mp4"
    assert urlsplit(url).hostname == "heygen.ai" and parse_url(url).host != "heygen.ai"
    assert _shared._heygen_download_host_allowed(urlsplit(url).hostname)   # host check alone is fooled
    assert not _shared._heygen_download_url_ok(url)                        # the full check is not


def test_f1_refusal_names_host_only_for_well_formed_urls(monkeypatch, tmp_path):
    with pytest.raises(ValueError) as e:
        _shared.download_heygen_video("https://cdn.other.example/v.mp4?Signature=SECRETSIG", tmp_path / "o.mp4")
    assert "cdn.other.example" in str(e.value) and "SECRETSIG" not in str(e.value)
    with pytest.raises(ValueError) as e:
        _shared.download_heygen_video("https://evil.tld\\@heygen.ai/v.mp4?Signature=SECRETSIG", tmp_path / "o.mp4")
    assert "evil" not in str(e.value) and "SECRETSIG" not in str(e.value)


@pytest.mark.parametrize("extra", ["127.0.0.1", "localhost", "a b", "..x", "evil.tld\\@x"])
def test_f1_extra_hosts_env_ignores_nonsense_entries_but_never_ips_via_syntax(monkeypatch, extra):
    monkeypatch.setenv("HEYGEN_EXTRA_DOWNLOAD_HOSTS", extra)
    assert not _shared._heygen_download_url_ok("https://evil.tld\\@heygen.ai/v.mp4")
    assert not _shared._heygen_download_url_ok("https://evil.tld/v.mp4")


# ------------------------------------------------ Security flag F2: signed URL in error text

SIG_URL = "https://resource2.heygen.ai/v.mp4?X-Amz-Signature=FAKESIG123&Expires=1"


def _assert_clean(text):
    assert "FAKESIG123" not in text and "Signature" not in text and "Expires" not in text


@pytest.mark.parametrize("status", [403, 404, 500])
def test_f2_http_error_on_download_has_no_url(monkeypatch, tmp_path, status):
    _get_returning(monkeypatch, Resp(status=status))
    with pytest.raises(RuntimeError) as e:
        _shared.download_heygen_video(SIG_URL, tmp_path / "o.mp4")
    _assert_clean(str(e.value) + repr(e.value) + repr(e.value.__cause__) + repr(e.value.__context__))
    assert f"HTTP {status}" in str(e.value) and e.value.__cause__ is None and e.value.__context__ is None


@pytest.mark.parametrize("exc", [
    requests.ConnectionError(f"Max retries exceeded with url: /v.mp4?X-Amz-Signature=FAKESIG123&Expires=1 ({SIG_URL})"),
    requests.Timeout(f"Read timed out for url: {SIG_URL}"),
    requests.exceptions.SSLError(SIG_URL),
])
def test_f2_connection_error_on_download_has_no_url(monkeypatch, tmp_path, exc):
    def get(url, **kw):
        raise exc

    monkeypatch.setattr("requests.get", get)
    with pytest.raises(RuntimeError) as e:
        _shared.download_heygen_video(SIG_URL, tmp_path / "o.mp4")
    _assert_clean(str(e.value) + repr(e.value.__cause__) + repr(e.value.__context__))
    assert type(exc).__name__ in str(e.value)


def test_f2_error_while_streaming_has_no_url(monkeypatch, tmp_path):
    class Broken(Resp):
        def iter_content(self, chunk_size=1):
            yield b"\x00\x00\x00\x18ftypmp42"
            raise requests.exceptions.ChunkedEncodingError(f"broken for url: {SIG_URL}")

    _get_returning(monkeypatch, Broken())
    with pytest.raises(RuntimeError) as e:
        _shared.download_heygen_video(SIG_URL, tmp_path / "o.mp4")
    _assert_clean(str(e.value) + repr(e.value.__cause__) + repr(e.value.__context__))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("status", [403, 404])
def test_f2_tool_result_error_has_no_signed_url(flow, monkeypatch, caplog, status):
    flow.video_url = SIG_URL
    real_get = requests.get

    def get(url, **kw):
        if url.startswith("https://resource2.heygen.ai/"):
            return Resp(status=status)
        return real_get(url, **kw)

    monkeypatch.setattr("requests.get", get)
    with caplog.at_level("DEBUG"):
        out = HeyGenVideo().execute({"prompt": "p", "output_path": str(flow.out / "o.mp4")})
    assert not out.success
    _assert_clean(out.error + caplog.text)


def test_f2_tool_result_scrubs_urls_from_any_exception(flow, monkeypatch):
    monkeypatch.setattr(_shared, "generate_heygen_video", lambda inputs: (_ for _ in ()).throw(
        requests.HTTPError(f"403 Client Error: Forbidden for url: {SIG_URL}")))
    monkeypatch.setattr("tools.video.heygen_video.generate_heygen_video", _shared.generate_heygen_video)
    out = HeyGenVideo().execute({"prompt": "p"})
    _assert_clean(out.error)
    assert "403" in out.error


@pytest.mark.parametrize("text", [
    f"Max retries exceeded with url: /v.mp4?X-Amz-Signature=FAKESIG123&Expires=1 (Caused by X)",
    f"403 Client Error: Forbidden for url: {SIG_URL}",
    f"plain {SIG_URL} text",
])
def test_f2_scrub_urls(text):
    _assert_clean(_shared.scrub_urls(text))


# ------------------------------------------------ Security flag F3: concurrency, temp files, modes

import os
import stat
import threading


def _slow_create(flow, monkeypatch, delay=0.2, counter_file=None):
    """Make the create call slow so concurrent runs overlap; count creates."""
    real_post = requests.post

    def post(url, **kw):
        if url.endswith("/v3/models/videos"):
            if counter_file is not None:
                with open(counter_file, "a") as fh:
                    fh.write(kw["headers"]["Idempotency-Key"] + "\n")
            _REAL_SLEEP(delay)
        return real_post(url, **kw)

    monkeypatch.setattr("requests.post", post)


def test_f3_threads_same_key_create_exactly_one_video(flow, monkeypatch):
    _slow_create(flow, monkeypatch)
    results, errors = [], []
    barrier = threading.Barrier(5)

    def worker(i):
        try:
            barrier.wait()
            results.append(_run(flow, output_path=str(flow.out / f"o{i}.mp4")))
        except Exception as exc:  # pragma: no cover - failure path is asserted below
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert len(_creates(flow)) == 1
    assert {r.data["execution_id"] for r in results} == {"vid_1"}
    assert sorted(r.data["resumed"] for r in results) == [False, True, True, True, True]
    assert all((flow.out / f"o{i}.mp4").read_bytes() == MP4 for i in range(5))
    assert {c[2]["headers"]["Idempotency-Key"] for c in _creates(flow)} and len(list((flow.tmp / "state").glob("*.tmp"))) == 0


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs fork")
def test_f3_processes_same_key_create_exactly_one_video(flow, monkeypatch):
    import multiprocessing

    counter = flow.tmp / "creates.log"
    _slow_create(flow, monkeypatch, counter_file=counter)
    ctx = multiprocessing.get_context("fork")
    q = ctx.Queue()

    def child(i):
        out = _run(flow, output_path=str(flow.out / f"p{i}.mp4"))
        q.put((out.success, out.data["execution_id"], out.data["resumed"]))

    procs = [ctx.Process(target=child, args=(i,)) for i in range(3)]
    [p.start() for p in procs]
    got = [q.get(timeout=30) for _ in procs]
    [p.join(timeout=30) for p in procs]
    assert all(p.exitcode == 0 for p in procs)
    assert len(counter.read_text().split()) == 1
    assert {g[1] for g in got} == {"vid_1"} and all(g[0] for g in got)
    assert sorted(g[2] for g in got) == [False, True, True]


def test_f3_different_keys_do_not_block_each_other(flow, monkeypatch):
    _slow_create(flow, monkeypatch, delay=0.3)
    flow.create_id = "vid_x"
    t0 = time.monotonic()
    ts = [threading.Thread(target=_run, args=(flow,), kwargs={"prompt": f"p{i}", "output_path": str(flow.out / f"d{i}.mp4")})
          for i in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(_creates(flow)) == 3 and time.monotonic() - t0 < 0.85


def test_f3_job_saves_use_unique_temp_files_and_never_collide(flow):
    key = "k" * 8
    errors = []

    def worker(i):
        try:
            for n in range(50):
                _shared._save_heygen_job(key, {"idempotency_key": f"id{i}", "created_at": time.time(), "n": n})
        except Exception as exc:
            errors.append(repr(exc))

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == []
    assert _shared._load_heygen_job(key) is not None
    assert sorted(p.name for p in (flow.tmp / "state").iterdir()) == [key + ".json"]


def test_f3_concurrent_downloads_to_one_path_do_not_collide(monkeypatch, tmp_path):
    _get_returning(monkeypatch, lambda url: Resp(chunks=[MP4[:12], MP4[12:]]))
    errors = []

    def worker():
        try:
            for _ in range(30):
                _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4")
        except Exception as exc:
            errors.append(repr(exc))

    ts = [threading.Thread(target=worker) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == []
    assert [p.name for p in tmp_path.iterdir()] == ["o.mp4"] and (tmp_path / "o.mp4").read_bytes() == MP4


def test_f3_lock_wait_times_out_instead_of_hanging(flow):
    held, release = threading.Event(), threading.Event()

    def holder():
        with _shared._heygen_job_lock("kk"):
            held.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    held.wait(5)
    try:
        with pytest.raises(TimeoutError):
            with _shared._heygen_job_lock("kk", timeout=0.2):
                pass
    finally:
        release.set()
        t.join()
    with _shared._heygen_job_lock("kk", timeout=1):   # free again
        pass


def test_f3_state_dir_is_0700_and_files_0600(flow):
    old = os.umask(0o022)
    try:
        _shared._save_heygen_job("modekey", {"idempotency_key": "a", "created_at": time.time()})
        with _shared._heygen_job_lock("modekey"):
            pass
    finally:
        os.umask(old)
    d = flow.tmp / "state"
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
    for p in d.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o600, p.name


@pytest.mark.parametrize("created", ["NaN", "Infinity", "-Infinity"])
def test_f3_non_finite_created_at_is_ignored(flow, created):
    p = _shared._heygen_job_path("nankey")
    p.parent.mkdir(parents=True)
    p.write_text('{"idempotency_key": "a", "video_id": "v1", "created_at": %s}' % created)
    assert _shared._load_heygen_job("nankey") is None


# ------------------------------------------------ Security flag F4: output_path confinement

def test_f4_output_outside_roots_is_refused_before_any_call(flow):
    victim = flow.tmp / "config.mp4"
    out = _shared.generate_heygen_video({"prompt": "p", "output_path": str(victim)})
    assert not out.success and "outside" in out.error
    assert flow.log == [] and not victim.exists()
    assert list(flow.tmp.glob("*.mp4*")) == []


@pytest.mark.parametrize("rel", [
    "../escaped.mp4",
    "sub/../../escaped.mp4",
])
def test_f4_dotdot_traversal_is_refused(flow, rel):
    out = _shared.generate_heygen_video({"prompt": "p", "output_path": str(flow.out / rel)})
    assert not out.success and "outside" in out.error and flow.log == []
    assert not (flow.tmp / "escaped.mp4").exists()


@pytest.mark.parametrize("path", ["/etc/cron.d/x.mp4", "/root/.ssh/authorized_keys", "~/.bashrc"])
def test_f4_absolute_system_paths_are_refused(flow, path):
    out = _shared.generate_heygen_video({"prompt": "p", "output_path": path})
    assert not out.success and flow.log == []


def test_f4_symlink_pointing_out_of_roots_is_refused(flow):
    outside = flow.tmp / "outside.mp4"
    outside.write_bytes(b"precious")
    (flow.out / "link.mp4").symlink_to(outside)
    out = _shared.generate_heygen_video({"prompt": "p", "output_path": str(flow.out / "link.mp4")})
    assert not out.success and "outside" in out.error and flow.log == []
    assert outside.read_bytes() == b"precious"


def test_f4_symlinked_directory_out_of_roots_is_refused(flow):
    outside_dir = flow.tmp / "elsewhere"
    outside_dir.mkdir()
    (flow.out / "d").symlink_to(outside_dir, target_is_directory=True)
    out = _shared.generate_heygen_video({"prompt": "p", "output_path": str(flow.out / "d" / "x.mp4")})
    assert not out.success and flow.log == [] and list(outside_dir.iterdir()) == []


def test_f4_symlink_staying_inside_roots_is_allowed_and_written_at_the_target(flow):
    (flow.out / "real.mp4").write_bytes(b"old")
    (flow.out / "ok.mp4").symlink_to(flow.out / "real.mp4")
    out = _shared.generate_heygen_video({"prompt": "p", "output_path": str(flow.out / "ok.mp4")})
    assert out.success, out.error
    assert (flow.out / "real.mp4").read_bytes() == MP4


@pytest.mark.parametrize("name", ["clip.txt", "clip", "clip.mp4.sh", "clip.png"])
def test_f4_only_mp4_names(flow, name):
    out = _shared.generate_heygen_video({"prompt": "p", "output_path": str(flow.out / name)})
    assert not out.success and ".mp4" in out.error and flow.log == []


def test_f4_directory_target_is_refused(flow):
    (flow.out / "adir.mp4").mkdir()
    out = _shared.generate_heygen_video({"prompt": "p", "output_path": str(flow.out / "adir.mp4")})
    assert not out.success and "directory" in out.error and flow.log == []


def test_f4_sibling_prefix_directory_is_not_inside(flow):
    sibling = flow.tmp / "out-evil"
    sibling.mkdir()
    out = _shared.generate_heygen_video({"prompt": "p", "output_path": str(sibling / "x.mp4")})
    assert not out.success and flow.log == []


def test_f4_nested_new_directories_inside_roots_work(flow):
    target = flow.out / "projects_x" / "assets" / "video" / "clip.mp4"
    out = _shared.generate_heygen_video({"prompt": "p", "output_path": str(target)})
    assert out.success, out.error
    assert target.read_bytes() == MP4


def test_f4_repo_projects_dir_is_allowed(monkeypatch):
    monkeypatch.delenv("OPENMONTAGE_ASSET_DIR", raising=False)
    p = _shared.validate_heygen_output_path("projects/demo/assets/video/x.mp4")
    assert p.parts[-5:] == ("projects", "demo", "assets", "video", "x.mp4")
    with pytest.raises(ValueError):
        _shared.validate_heygen_output_path("elsewhere/x.mp4")


def test_f4_tool_execute_reports_refusal_as_error(flow):
    out = HeyGenVideo().execute({"prompt": "p", "output_path": str(flow.tmp / "x.mp4")})
    assert not out.success and "outside" in out.error and flow.log == []


def test_f4_asset_dir_env_accepts_several_entries(flow, monkeypatch, tmp_path):
    other = tmp_path / "other_root"
    other.mkdir()
    monkeypatch.setenv("OPENMONTAGE_ASSET_DIR", os.pathsep.join([str(flow.out), str(other)]))
    assert _shared.validate_heygen_output_path(other / "a.mp4") == (other / "a.mp4").resolve()
    assert _shared.validate_heygen_output_path(flow.out / "a.mp4")


def test_f4_missing_upload_file_outside_roots_does_not_reveal_existence(flow):
    with pytest.raises(ValueError, match="outside"):          # not FileNotFoundError
        _shared.validate_heygen_upload_path(str(flow.tmp / "does-not-exist.png"))


# ------------------------------------------------ Low F5: upload_image_fal (used by video_selector) is validated

@pytest.fixture
def fal(flow, assets, monkeypatch):
    monkeypatch.setenv("FAL_KEY", "test-not-a-fal-key")
    calls = []

    def post(url, **kw):
        calls.append(("POST", url, kw))
        return Resp({"upload_url": "https://fal.example/put", "file_url": "https://fal.example/f.png"})

    def put(url, **kw):
        calls.append(("PUT", url, kw))
        return Resp()

    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr("requests.put", put)
    return calls


def test_f5_fal_upload_refuses_paths_outside_roots_without_any_request(fal, flow, monkeypatch):
    monkeypatch.delenv("FAL_KEY")                      # validation comes before the key check
    secret = flow.tmp / "id_rsa.png"
    secret.write_bytes(PNG)
    with pytest.raises(ValueError, match="outside"):
        _shared.upload_image_fal(str(secret))
    with pytest.raises(ValueError, match="outside"):
        _shared.upload_image_fal("/etc/passwd")
    assert fal == []


@pytest.mark.parametrize("name,data,match", [
    ("id_rsa", PNG, "only png"),
    ("notes.txt", PNG, "only png"),
    ("fake.png", b"-----BEGIN OPENSSH PRIVATE KEY-----", "does not match"),
    ("big.png", PNG, "size"),
])
def test_f5_fal_upload_checks_type_and_size(fal, assets, monkeypatch, name, data, match):
    p = assets / name
    p.write_bytes(data)
    if name == "big.png":
        monkeypatch.setattr(_shared, "HEYGEN_MAX_UPLOAD_BYTES", 10)
    with pytest.raises(ValueError, match=match):
        _shared.upload_image_fal(str(p))
    assert fal == []


def test_f5_fal_upload_uses_sniffed_type_and_sends_the_validated_bytes(fal, assets):
    p = assets / "pic.JPG"
    p.write_bytes(JPEG)
    assert _shared.upload_image_fal(str(p)) == "https://fal.example/f.png"
    (_, _, init), (_, _, put) = fal
    assert init["json"] == {"content_type": "image/jpeg", "file_name": "pic.JPG"}
    assert put["data"] == JPEG and put["headers"]["Content-Type"] == "image/jpeg"


def test_f5_file_swapped_after_validation_is_not_sent(fal, assets, monkeypatch):
    p = assets / "a.png"
    p.write_bytes(PNG)
    real = _shared.validate_upload_path

    def validate_then_swap(path):
        out = real(path)
        p.write_bytes(b"secret text that is not an image")
        return out

    monkeypatch.setattr(_shared, "validate_upload_path", validate_then_swap)
    with pytest.raises(ValueError, match="changed"):
        _shared.upload_image_fal(str(p))
    assert fal == []


def test_f5_heygen_fallback_path_still_works_with_validated_fal(flow, assets, monkeypatch):
    p = assets / "a.png"
    p.write_bytes(PNG)
    real_post = requests.post

    def post(url, **kw):
        if url.endswith("/v3/assets"):
            return Resp({}, status=500)
        if "fal.ai" in url:
            return Resp({"upload_url": "https://fal.example/put", "file_url": "https://fal.example/f.png"})
        return real_post(url, **kw)

    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr("requests.put", lambda *a, **k: Resp())
    monkeypatch.setenv("FAL_KEY", "test-not-a-fal-key")
    monkeypatch.setenv("HEYGEN_ALLOW_FAL_FALLBACK", "1")
    assert _shared.upload_image_heygen(str(p), "k") == {"type": "url", "url": "https://fal.example/f.png"}


# ------------------------------------------------ Low F6: reference_image_url is vetted

@pytest.mark.parametrize("url", [
    "http://images.shopfront.com/a.png",
    "ftp://images.shopfront.com/a.png",
    "file:///etc/passwd",
    "//images.shopfront.com/a.png",
    "images.shopfront.com/a.png",
    "https://user:pw@images.shopfront.com/a.png",
    "https://evil.tld\\@images.shopfront.com/a.png",
    "https://images.shopfront.com:8443/a.png",
    "https://images.shopfront.com/a b.png",
    "https://images.shopfront.com/a.png\n",
    "https://images.shopfront.com/" + "a" * 2050,
    "https://ｉmg.example/a.png",
    123,
])
def test_f6_bad_reference_urls_are_refused_before_any_call(flow, url):
    out = _run(flow, operation="image_to_video", reference_image_url=url)
    assert not out.success and "reference_image_url" in out.error
    assert flow.log == []
    if isinstance(url, str) and url:
        assert url[:40] not in out.error      # the URL is not echoed


@pytest.mark.parametrize("url", ["https://images.shopfront.com/a.png", "https://images.shopfront.com:443/a.png?x=1&y=%20"])
def test_f6_plain_https_reference_url_is_sent_as_is(flow, url):
    out = _run(flow, operation="image_to_video", reference_image_url=url)
    assert out.success, out.error
    assert _creates(flow)[0][2]["json"]["image"] == {"type": "url", "url": url}


def test_f6_text_to_video_ignores_the_field(flow):
    assert _run(flow, reference_image_url="http://bad.example/").success


# ------------------------------------------------ Low F7: broad OPENMONTAGE_ASSET_DIR values are ignored

@pytest.mark.parametrize("bad", ["/", "/tmp", "/home", "/etc", "~", "~/..", "//", "/usr/"])
def test_f7_broad_asset_dir_is_ignored_with_a_warning(monkeypatch, caplog, bad):
    monkeypatch.setenv("OPENMONTAGE_ASSET_DIR", bad)
    with caplog.at_level("WARNING"):
        roots = _shared._allowed_asset_roots()
    assert [r.name for r in roots] == ["projects", "assets"]
    assert "too broad" in caplog.text


def test_f7_home_directory_itself_is_ignored_but_a_subfolder_is_fine(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "me"))
    (tmp_path / "me" / "media").mkdir(parents=True)
    monkeypatch.setenv("OPENMONTAGE_ASSET_DIR", os.pathsep.join([str(tmp_path / "me"), str(tmp_path / "me" / "media")]))
    roots = _shared._allowed_asset_roots()
    assert (tmp_path / "me" / "media").resolve() in roots and (tmp_path / "me").resolve() not in roots


def test_f7_with_broad_dir_outputs_and_uploads_outside_the_repo_are_still_refused(flow, monkeypatch):
    monkeypatch.setenv("OPENMONTAGE_ASSET_DIR", "/")
    out = _shared.generate_heygen_video({"prompt": "p", "output_path": str(flow.tmp / "x.mp4")})
    assert not out.success and flow.log == []
    with pytest.raises(ValueError):
        _shared.validate_heygen_upload_path("/etc/passwd")


# ------------------------------------------------ Low F8: content type, magic bytes, length, deadline

@pytest.mark.parametrize("ctype", ["video/mp4", "video/quicktime", "application/octet-stream",
                                   "VIDEO/MP4; codecs=avc1", " application/octet-stream ", ""])
def test_f8_accepted_content_types(monkeypatch, tmp_path, ctype):
    _get_returning(monkeypatch, Resp(headers={"Content-Type": ctype}))
    assert _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4") == len(MP4)


@pytest.mark.parametrize("ctype", ["text/html", "text/plain", "application/json", "image/png",
                                   "application/x-msdownload", "video", "application/octet-stream-x", "multipart/form-data"])
def test_f8_refused_content_types(monkeypatch, tmp_path, ctype):
    _get_returning(monkeypatch, Resp(headers={"Content-Type": ctype}))
    with pytest.raises(ValueError, match="content type"):
        _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("body", [
    b"<html>signed url expired</html>",
    b"MZ" + b"\x90" * 30,
    b"\x89PNG\r\n\x1a\n" + b"0" * 20,
    b"short",
    b"\x00\x00\x00\x18ftyx" + b"0" * 20,
])
@pytest.mark.parametrize("ctype", ["video/mp4", "application/octet-stream", ""])
def test_f8_body_must_start_like_an_mp4(monkeypatch, tmp_path, body, ctype):
    _get_returning(monkeypatch, Resp(chunks=[body], headers={"Content-Type": ctype}))
    with pytest.raises(ValueError, match="not an mp4"):
        _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4")
    assert list(tmp_path.iterdir()) == []


def test_f8_non_ascii_digit_content_length_does_not_crash(monkeypatch, tmp_path):
    _get_returning(monkeypatch, Resp(headers={"Content-Length": "\u00b2\u0663"}))
    assert _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4") == len(MP4)


def test_f8_overall_deadline_stops_a_slow_download(monkeypatch, tmp_path):
    monkeypatch.setattr(_shared, "HEYGEN_DOWNLOAD_DEADLINE_SECONDS", -1)
    _get_returning(monkeypatch, Resp())
    with pytest.raises(RuntimeError, match="too long"):
        _shared.download_heygen_video(GOOD_URL, tmp_path / "o.mp4")
    assert list(tmp_path.iterdir()) == []


def test_f8_deadline_default_is_fifteen_minutes():
    assert _shared.HEYGEN_DOWNLOAD_DEADLINE_SECONDS == 15 * 60


# ------------------------------------------------ Low F11/F12: key defaults, ref path, cost estimate

def test_f11_omitted_duration_and_resolution_match_their_defaults():
    a = _shared.heygen_idempotency_key({"prompt": "p"})
    assert a == _shared.heygen_idempotency_key({"prompt": "p", "duration": 5, "resolution": "768p"})
    assert a != _shared.heygen_idempotency_key({"prompt": "p", "duration": 6})
    assert a != _shared.heygen_idempotency_key({"prompt": "p", "resolution": "1080p"})


def test_f11_relative_and_absolute_ref_path_share_a_key(assets, monkeypatch):
    (assets / "a.png").write_bytes(PNG)
    monkeypatch.chdir(assets)
    base = {"operation": "image_to_video", "prompt": "p"}
    assert _shared.heygen_idempotency_key({**base, "reference_image_path": "a.png"}) == \
        _shared.heygen_idempotency_key({**base, "reference_image_path": str(assets / "a.png")})


def test_f11_files_outside_the_roots_are_not_read_for_the_digest(flow, monkeypatch):
    outside = flow.tmp / "secret.png"
    outside.write_bytes(PNG)
    read = []
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: (read.append(self), real(self))[1])
    _shared.heygen_idempotency_key({"operation": "image_to_video", "prompt": "p", "reference_image_path": str(outside)})
    assert read == []


def test_f11_changed_image_content_changes_the_key(assets):
    p = assets / "a.png"
    inputs = {"operation": "image_to_video", "prompt": "p", "reference_image_path": str(p)}
    p.write_bytes(PNG)
    k1 = _shared.heygen_idempotency_key(inputs)
    p.write_bytes(PNG + b"1")
    assert k1 != _shared.heygen_idempotency_key(inputs)


@pytest.mark.parametrize("res,factor", [(None, 1), ("768p", 1), ("720p", 1), ("1080p", 3), ("2k", 3)])
def test_f12_estimate_cost_is_3x_for_1080p_and_2k(res, factor):
    tool = HeyGenVideo()
    base = tool.estimate_cost({"prompt": "p"})
    inputs = {"prompt": "p", **({"resolution": res} if res else {})}
    assert tool.estimate_cost(inputs) == pytest.approx(base * factor)
    assert base > 0


# ------------------------------------------------ Follow-up (a): reference_image_url must look public

@pytest.mark.parametrize("url", [
    "https://127.0.0.1/a.png", "https://10.0.0.5/a.png", "https://169.254.169.254/latest/meta-data/",
    "https://[::1]/a.png", "https://[fe80::1]/a.png", "https://[2001:db8::1]/a.png",
    "https://2130706433/a.png", "https://0x7f000001/a.png", "https://127.1/a.png", "https://017700000001/a.png",
    "https://0x7f.0.0.1/a.png", "https://1.2.3.4.5/a.png",
    "https://localhost/a.png", "https://localhost./a.png", "https://LOCALHOST/a.png", "https://app.localhost/a.png",
    "https://intranet/a.png", "https://printer/a.png",
    "https://nas.local/a.png", "https://db.internal/a.png", "https://router.lan/a.png", "https://x.corp/a.png",
    "https://metadata.google.internal/a.png", "https://host.home/a.png", "https://a.example/a.png",
    "https://-bad.example.com/a.png", "https://a..com/a.png", "https://site.c0m/a.png",
])
def test_fa_non_public_looking_hosts_are_refused(flow, url):
    out = _run(flow, operation="image_to_video", reference_image_url=url)
    assert not out.success and "reference_image_url" in out.error and flow.log == []


@pytest.mark.parametrize("url", [
    "https://images.shopfront.com/a.png?token=abc",
    "https://images.shopfront.com/a.png?access_token=abc",
    "https://images.shopfront.com/a.png?API_KEY=abc",
    "https://images.shopfront.com/a.png?apikey=abc",
    "https://images.shopfront.com/a.png?key=abc",
    "https://images.shopfront.com/a.png?secret=abc",
    "https://images.shopfront.com/a.png?password=abc",
    "https://images.shopfront.com/a.png?sig=abc",
    "https://images.shopfront.com/a.png?signature=abc",
    "https://images.shopfront.com/a.png?X-Amz-Signature=abc",
    "https://images.shopfront.com/a.png?X-Amz-Credential=abc",
    "https://images.shopfront.com/a.png?X-Goog-Signature=abc",
    "https://images.shopfront.com/a.png?auth=abc",
    "https://images.shopfront.com/a.png?w=1&session=abc",
    "https://images.shopfront.com/a.png?x=sk-abcdef",
    "https://images.shopfront.com/a.png?x=ghp_abcdef",
    "https://images.shopfront.com/a.png?x=eyJhbGciOi",
    "https://images.shopfront.com/a.png?x=AKIAABCDEFG",
    "https://images.shopfront.com/a.png?" + "a=b&" * 200,
    "https://images.shopfront.com/a.png#frag",
])
def test_fa_secret_looking_query_strings_are_refused_and_not_echoed(flow, url):
    out = _run(flow, operation="image_to_video", reference_image_url=url)
    assert not out.success and "reference_image_url" in out.error and flow.log == []
    assert "abc" not in out.error and "?" not in out.error.split("DNS name")[0]
    assert "reference_image_path" in out.error            # tells the user what to do instead


@pytest.mark.parametrize("url", [
    "https://images.shopfront.com/a.png",
    "https://cdn.shopfront.co.uk/a/b/c.jpg?w=800&h=600",
    "https://images.shopfront.com/a.png?v=3&format=webp&keyword=sunset",
    "https://xn--bcher-kva.example.com/a.png",
    "https://resource2.heygen.ai/image/x.png",
    "https://a.b.c.d.com/x.png?size=large",
    "https://shop.com:443/a.png",
    "https://images.shopfront.com/assets/token-icon.png",     # a path may mention words; only the query is checked
    "https://images.shopfront.com/a.png?monkey=1&author=me&keyword=x&design=2",  # substrings of longer, harmless names
])
def test_fa_ordinary_public_urls_still_work(flow, url):
    out = _run(flow, operation="image_to_video", reference_image_url=url)
    assert out.success, out.error
    assert _creates(flow)[0][2]["json"]["image"] == {"type": "url", "url": url}


def test_fa_reference_url_check_is_pure_syntax_no_dns(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("no DNS lookups"))
    assert _shared._reference_url_ok("https://images.shopfront.com/a.png")
