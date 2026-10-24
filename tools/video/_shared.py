"""Shared helpers for provider-specific video generation tools."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from tools.base_tool import ToolResult, ToolStatus

logger = logging.getLogger(__name__)


# HeyGen v3 (POST /v3/models/videos) offers one model, heygen-video-1. The
# third-party variants below ran on the v1 workflows API (GenerateVideoNode),
# retired by HeyGen on Oct 31, 2026, with no documented v3 equivalent. They are
# kept only so old configs get a clear error instead of an unknown-key error.
HEYGEN_DEFAULT_PROVIDER = "heygen_video_1"
HEYGEN_PROVIDERS = {
    "heygen_video_1": {"name": "HeyGen Video 1 (v3)", "quality": "high", "speed": "medium"},
}
HEYGEN_LEGACY_PROVIDERS = {
    "veo_3_1": {"name": "Google VEO 3.1", "quality": "highest", "speed": "slow"},
    "veo_3_1_fast": {"name": "Google VEO 3.1 Fast", "quality": "high", "speed": "medium"},
    "veo3": {"name": "Google VEO 3", "quality": "high", "speed": "slow"},
    "veo3_fast": {"name": "Google VEO 3 Fast", "quality": "high", "speed": "medium"},
    "veo2": {"name": "Google VEO 2", "quality": "medium", "speed": "medium"},
    "kling_pro": {"name": "Kling Pro", "quality": "high", "speed": "medium"},
    "kling_v2": {"name": "Kling v2", "quality": "medium", "speed": "fast"},
    "sora_v2": {"name": "Sora v2", "quality": "high", "speed": "slow"},
    "sora_v2_pro": {"name": "Sora v2 Pro", "quality": "highest", "speed": "slow"},
    "runway_gen4": {"name": "Runway Gen-4", "quality": "high", "speed": "medium"},
    "seedance_lite": {"name": "Seedance Lite", "quality": "medium", "speed": "fast"},
    "seedance_pro": {"name": "Seedance Pro", "quality": "high", "speed": "medium"},
    "ltx_distilled": {"name": "LTX Distilled", "quality": "low", "speed": "fastest"},
}

WAN_VARIANTS = {
    "wan2.1-1.3b": {
        "name": "Wan 2.1 (1.3B)",
        "hf_id": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        "hf_i2v_id": "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers",
        "pipeline_class": "WanPipeline",
        "vram_mb": 8000,
        "quality": "high",
        "speed": "medium",
        "t2v": True,
        "i2v": True,
        "license": "Apache-2.0",
        "default_width": 832,
        "default_height": 480,
        "default_num_frames": 81,
        "fps": 16,
    },
    "wan2.1-14b": {
        "name": "Wan 2.1 (14B)",
        "hf_id": "Wan-AI/Wan2.1-T2V-14B-Diffusers",
        "hf_i2v_id": "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers",
        "pipeline_class": "WanPipeline",
        "vram_mb": 24000,
        "quality": "highest",
        "speed": "slow",
        "t2v": True,
        "i2v": True,
        "license": "Apache-2.0",
        "default_width": 1280,
        "default_height": 720,
        "default_num_frames": 81,
        "fps": 16,
    },
}

HUNYUAN_VARIANTS = {
    "hunyuan-1.5": {
        "name": "HunyuanVideo 1.5",
        "hf_id": "tencent/HunyuanVideo-1.5",
        "pipeline_class": "HunyuanVideoPipeline",
        "vram_mb": 14000,
        "quality": "high",
        "speed": "medium",
        "t2v": True,
        "i2v": True,
        "license": "Apache-2.0",
        "default_width": 848,
        "default_height": 480,
        "default_num_frames": 121,
        "fps": 24,
    },
}

LTX_LOCAL_VARIANTS = {
    "ltx2-local": {
        "name": "LTX-2 (Local)",
        "hf_id": "Lightricks/LTX-2",
        "pipeline_class": "LTXPipeline",
        "vram_mb": 12000,
        "quality": "high",
        "speed": "medium",
        "t2v": True,
        "i2v": True,
        "license": "LTX-2-Community",
        "default_width": 768,
        "default_height": 512,
        "default_num_frames": 121,
        "fps": 24,
    },
}

COGVIDEO_VARIANTS = {
    "cogvideo-5b": {
        "name": "CogVideoX 1.5 (5B)",
        "hf_id": "THUDM/CogVideoX-5b",
        "pipeline_class": "CogVideoXPipeline",
        "vram_mb": 12000,
        "quality": "medium",
        "speed": "medium",
        "t2v": True,
        "i2v": True,
        "license": "Apache-2.0",
        "default_width": 720,
        "default_height": 480,
        "default_num_frames": 49,
        "fps": 8,
    },
    "cogvideo-2b": {
        "name": "CogVideoX (2B)",
        "hf_id": "THUDM/CogVideoX-2b",
        "pipeline_class": "CogVideoXPipeline",
        "vram_mb": 6000,
        "quality": "medium",
        "speed": "fast",
        "t2v": True,
        "i2v": False,
        "license": "Apache-2.0",
        "default_width": 720,
        "default_height": 480,
        "default_num_frames": 49,
        "fps": 8,
    },
}

LTX2_FRAME_COUNTS = {
    "1s": 25,
    "2s": 49,
    "3s": 73,
    "4s": 97,
    "5s": 121,
    "6.7s": 161,
    "8s": 193,
}


def local_generation_enabled() -> bool:
    return os.environ.get("VIDEO_GEN_LOCAL_ENABLED", "").lower() in {"true", "1", "yes"}


def local_generation_status() -> ToolStatus:
    if not local_generation_enabled():
        return ToolStatus.UNAVAILABLE
    try:
        import diffusers  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return ToolStatus.UNAVAILABLE
    return ToolStatus.AVAILABLE


def local_install_instructions() -> str:
    return (
        "Enable local video generation and install the diffusers stack:\n"
        "  set VIDEO_GEN_LOCAL_ENABLED=true\n"
        "  pip install diffusers transformers accelerate torch pillow requests\n"
        "Use a GPU with the VRAM profile listed on the selected tool."
    )


def estimate_quality_cost(quality: str) -> float:
    if quality == "highest":
        return 0.50
    if quality == "high":
        return 0.35
    if quality == "low":
        return 0.15
    return 0.20


def estimate_speed_runtime(speed: str) -> float:
    return {"fastest": 30.0, "fast": 60.0, "medium": 120.0, "slow": 300.0}.get(speed, 120.0)


def estimate_local_runtime(speed: str) -> float:
    return {"fast": 120.0, "medium": 240.0, "slow": 600.0}.get(speed, 240.0)


def load_diffusers_pipeline(pipeline_class: str, model_id: str, enable_offload: bool):
    import diffusers
    import torch

    pipeline_map = {
        "WanPipeline": "WanPipeline",
        "HunyuanVideoPipeline": "HunyuanVideoPipeline",
        "LTXPipeline": "LTXPipeline",
        "CogVideoXPipeline": "CogVideoXPipeline",
    }
    pipeline_name = pipeline_map.get(pipeline_class, pipeline_class)
    pipeline_class_obj = getattr(diffusers, pipeline_name)
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    pipeline = pipeline_class_obj.from_pretrained(model_id, torch_dtype=dtype)

    if enable_offload:
        pipeline.enable_model_cpu_offload()
    else:
        pipeline = pipeline.to("cuda")

    if hasattr(pipeline, "vae") and pipeline.vae is not None:
        if hasattr(pipeline.vae, "enable_tiling"):
            pipeline.vae.enable_tiling()
        if hasattr(pipeline.vae, "enable_slicing"):
            pipeline.vae.enable_slicing()
    return pipeline


def load_reference_image(inputs: dict[str, Any], width: int, height: int):
    from io import BytesIO

    import requests
    from PIL import Image

    ref_path = inputs.get("reference_image_path")
    ref_url = inputs.get("reference_image_url")

    if ref_path:
        image = Image.open(ref_path).convert("RGB")
    elif ref_url:
        response = requests.get(ref_url, timeout=60)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGB")
    else:
        return ToolResult(
            success=False,
            error="image_to_video requires reference_image_url or reference_image_path",
        )

    return image.resize((width, height), Image.LANCZOS)


def generate_local_video(
    *,
    tool_name: str,
    variants: dict[str, dict[str, Any]],
    default_variant: str,
    inputs: dict[str, Any],
) -> ToolResult:
    import torch
    from diffusers.utils import export_to_video

    variant = inputs.get("model_variant", default_variant)
    if variant not in variants:
        return ToolResult(
            success=False,
            error=f"Unknown model_variant: {variant}. Available: {', '.join(sorted(variants))}",
        )

    meta = variants[variant]
    prompt = inputs["prompt"]
    operation = inputs.get("operation", "text_to_video")
    seed = inputs.get("seed")
    enable_offload = inputs.get("enable_model_offload", True)

    if operation == "image_to_video" and not meta.get("i2v"):
        return ToolResult(
            success=False,
            error=f"{meta['name']} does not support image_to_video.",
        )

    width = inputs.get("width", meta["default_width"])
    height = inputs.get("height", meta["default_height"])
    num_frames = inputs.get("num_frames", meta["default_num_frames"])
    fps = meta["fps"]
    model_id = meta.get("hf_i2v_id") if operation == "image_to_video" and meta.get("hf_i2v_id") else meta["hf_id"]
    pipeline = load_diffusers_pipeline(meta["pipeline_class"], model_id, enable_offload)

    generation_args: dict[str, Any] = {
        "prompt": prompt,
        "num_frames": num_frames,
        "width": width,
        "height": height,
        "num_inference_steps": inputs.get("num_inference_steps", 30),
    }
    if seed is not None:
        generation_args["generator"] = torch.Generator(device="cpu").manual_seed(seed)
    if operation == "image_to_video":
        image = load_reference_image(inputs, width, height)
        if isinstance(image, ToolResult):
            return image
        generation_args["image"] = image
    if meta["pipeline_class"] == "CogVideoXPipeline":
        generation_args["negative_prompt"] = "worst quality, low quality, blurry, distorted, watermark"

    output = pipeline(**generation_args)
    frames = output.frames[0] if hasattr(output, "frames") else output.images

    output_path = Path(inputs.get("output_path", f"{tool_name}_{variant}.mp4"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    export_to_video(frames, str(output_path), fps=fps)

    return ToolResult(
        success=True,
        data={
            "provider": tool_name,
            "model_variant": variant,
            "provider_name": meta["name"],
            "mode": "local",
            "prompt": prompt,
            "model_id": model_id,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "fps": fps,
            "duration_seconds": round(num_frames / fps, 2),
            "operation": operation,
            "output": str(output_path),
            "format": "mp4",
            "license": meta["license"],
            **probe_output(output_path),
        },
        artifacts=[str(output_path)],
        seed=seed,
        model=model_id,
    )


HEYGEN_API_BASE = "https://api.heygen.com"
HEYGEN_V3_MODEL = "heygen-video-1"
HEYGEN_TERMINAL_FAILED = {"failed", "cancelled"}


class HeyGenJobFailed(RuntimeError):
    """The HeyGen job ended as failed or cancelled (it will not complete)."""


# Create-request fields that decide which video a run produces. The local resume
# key (heygen_idempotency_key) is built from these plus a digest of the reference image.
HEYGEN_IDEMPOTENCY_FIELDS = [
    "operation",
    "prompt",
    "provider_variant",
    "aspect_ratio",
    "duration",
    "resolution",
    "reference_image_url",
    "reference_image_path",
]
HEYGEN_JOB_TTL_SECONDS = 24 * 3600  # HeyGen replays an Idempotency-Key for 24 h


def heygen_idempotency_key(inputs: dict[str, Any]) -> str:
    """Stable key for one logical generation request.

    Defaults are filled in so an omitted field and its default match. For a local
    reference image the file content digest is included, so a changed file at the
    same path is a different request.
    """
    key_data: dict[str, Any] = {k: inputs.get(k) for k in HEYGEN_IDEMPOTENCY_FIELDS}
    key_data["operation"] = inputs.get("operation", "text_to_video")
    key_data["provider_variant"] = inputs.get("provider_variant", HEYGEN_DEFAULT_PROVIDER)
    key_data["aspect_ratio"] = inputs.get("aspect_ratio", "16:9")
    ref_path = inputs.get("reference_image_path")
    if ref_path:
        try:
            p = Path(ref_path)
            if p.is_file() and p.stat().st_size <= HEYGEN_MAX_UPLOAD_BYTES:
                key_data["reference_image_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            pass
    raw = json.dumps(key_data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _heygen_job_path(key: str) -> Path:
    base = os.environ.get("OPENMONTAGE_HEYGEN_STATE_DIR")
    root = Path(base).expanduser() if base else Path.home() / ".openmontage" / "heygen_jobs"
    return root / f"{key}.json"


def _load_heygen_job(key: str) -> dict[str, Any] | None:
    """Saved job for this key, or None if missing, expired or malformed."""
    try:
        job = json.loads(_heygen_job_path(key).read_text())
        created = float(job["created_at"])
        if not math.isfinite(created) or time.time() - created > HEYGEN_JOB_TTL_SECONDS:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", job["idempotency_key"]):
            return None
        if "video_id" in job:
            validate_heygen_video_id(job["video_id"])
        return job
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_heygen_job(key: str, job: dict[str, Any]) -> None:
    """Write the job file atomically: unique temp file (mode 0600) in the same
    directory, then rename. The directory is created with mode 0700."""
    path = _heygen_job_path(key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(job))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@contextlib.contextmanager
def _heygen_job_lock(key: str, timeout: float = 180.0):
    """Exclusive advisory lock for one request key (a <key>.lock file next to the job
    file), so two runs with the same key cannot both create a video. Held from the
    job load until the video_id is saved, not while polling. Released by the OS if the
    process dies."""
    path = _heygen_job_path(key).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError("Timed out waiting for another HeyGen run with the same request") from None
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)  # closing the descriptor drops the lock


def _clear_heygen_job(key: str) -> None:
    _heygen_job_path(key).unlink(missing_ok=True)


def validate_heygen_video_id(video_id: Any) -> str:
    """Return video_id if it is a plain token, else raise ValueError.

    The id comes from HeyGen's response and is used in the poll URL path and in
    the default output file name, so it must not carry slashes, dots or spaces.
    """
    if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", video_id):
        raise ValueError("Invalid video_id in HeyGen response (expected [A-Za-z0-9_-]{1,64})")
    return video_id


def poll_heygen(video_id: str, api_key: str, timeout: int = 600) -> str:
    """Poll GET /v3/models/videos/{video_id} until completed; return video_url.

    v1 /v1/workflows/executions is retired by HeyGen on Oct 31, 2026.
    """
    import requests

    validate_heygen_video_id(video_id)
    headers = {"X-Api-Key": api_key}
    url = f"{HEYGEN_API_BASE}/v3/models/videos/{video_id}"
    deadline = time.time() + timeout
    interval = 5.0

    while time.time() < deadline:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json().get("data", {})
        status = data.get("status", "")

        if status == "completed":
            video_url = data.get("video_url")
            if video_url:
                return video_url
            raise RuntimeError(f"Completed but no video_url for {video_id}")

        if status in HEYGEN_TERMINAL_FAILED:
            reason = data.get("failure_message") or data.get("failure_code") or "Unknown"
            raise HeyGenJobFailed(f"HeyGen generation {status}: {reason}")

        time.sleep(min(interval, max(0.0, deadline - time.time())))
        interval = min(interval * 1.2, 30.0)

    raise TimeoutError(f"HeyGen video {video_id} timed out after {timeout}s")


# Hosts the completed video_url may be fetched from: HeyGen's own CDN
# (docs show resource2.heygen.ai). Extra exact hosts can be added with
# HEYGEN_EXTRA_DOWNLOAD_HOSTS (comma separated) if a real response uses another one.
HEYGEN_DOWNLOAD_HOST_SUFFIXES = ("heygen.ai", "heygen.com")
HEYGEN_MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
HEYGEN_MAX_REDIRECTS = 3
_REDIRECT_CODES = {301, 302, 303, 307, 308}


_HOSTNAME_RE = re.compile(r"[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63})*")


def _heygen_download_host_allowed(host: str | None) -> bool:
    host = (host or "").lower()
    if not _HOSTNAME_RE.fullmatch(host):  # no empty labels, no trailing dot, no odd characters
        return False
    extra = {h.strip().lower() for h in os.environ.get("HEYGEN_EXTRA_DOWNLOAD_HOSTS", "").split(",") if h.strip()}
    return host in extra or any(host == s or host.endswith("." + s) for s in HEYGEN_DOWNLOAD_HOST_SUFFIXES)


def _https_url_syntax_ok(url: str) -> bool:
    """True if url is a plain https URL that urllib.parse and urllib3 (what requests
    connects with) read the same way.

    Rejects non-ASCII, whitespace, control characters and backslashes anywhere in the
    string, userinfo, ports other than 443, and any difference between the two parsers
    about the host (for example https://evil.tld\\@heygen.ai/).
    """
    from urllib3.util import parse_url

    if not isinstance(url, str) or not url.isascii():
        return False
    if any(ord(c) <= 0x20 or ord(c) == 0x7F or c == "\\" for c in url):
        return False
    try:
        p = urlsplit(url)
        if p.scheme != "https" or p.username is not None or p.password is not None:
            return False
        if p.port not in (None, 443):
            return False
        q = parse_url(url)
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    return bool(host) and (q.host or "").lower() == host and q.scheme == "https" and q.auth is None


def _heygen_download_url_ok(url: str) -> bool:
    return _https_url_syntax_ok(url) and _heygen_download_host_allowed(urlsplit(url).hostname)


_URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
_URL_ARG_RE = re.compile(r"(\burl:\s*)[^\s'\")]+", re.IGNORECASE)


def scrub_urls(text: str) -> str:
    """Remove URLs (and urllib3's 'with url: /path?query' form) from error text.

    HeyGen video links are signed, so they must not reach ToolResult.error or logs.
    """
    return _URL_ARG_RE.sub(r"\1<removed>", _URL_RE.sub("<url removed>", text))


def _refusal(url: str) -> ValueError:
    # Name the host only when the URL is well formed and just not allowlisted, so an
    # operator can add it to HEYGEN_EXTRA_DOWNLOAD_HOSTS. Never the path or query (signed).
    if _https_url_syntax_ok(url):
        return ValueError(f"Refusing HeyGen video download from host {urlsplit(url).hostname}")
    return ValueError("Refusing HeyGen video download (url not allowed)")


def download_heygen_video(video_url: str, output_path: Path, max_bytes: int = HEYGEN_MAX_DOWNLOAD_BYTES) -> int:
    """Download a completed HeyGen video to output_path and return its size.

    https only, host allowlist and parser agreement (re-checked on every redirect), streamed to a
    .part file with a size cap. No API key is sent. The URL is never put in an
    error message because it is a signed URL.
    """
    import requests

    url = video_url
    for _ in range(HEYGEN_MAX_REDIRECTS + 1):
        if not _heygen_download_url_ok(url):  # initial URL and every redirect hop
            raise _refusal(url)
        # requests and urllib3 put the full URL, query string included, in their messages, so
        # only the exception class name is kept, and it is raised outside the except block so
        # the original exception is not attached as __context__.
        failure = None
        try:
            resp = requests.get(url, stream=True, timeout=120, allow_redirects=False)
        except requests.RequestException as exc:
            failure = type(exc).__name__
        if failure:
            raise RuntimeError(f"HeyGen video download failed: {failure}")
        try:
            if resp.status_code in _REDIRECT_CODES:
                location = resp.headers.get("Location")
                if not location:
                    raise RuntimeError("HeyGen video download redirect without Location")
                if any(ord(c) <= 0x20 or ord(c) == 0x7F or c == "\\" for c in location):
                    raise _refusal("")  # urljoin would silently drop tabs and newlines
                url = urljoin(url, location)
                continue
            if resp.status_code >= 400:  # not raise_for_status(): its message carries the signed URL
                raise RuntimeError(f"HeyGen video download failed: HTTP {resp.status_code}")
            ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if ctype and not (ctype.startswith("video/") or ctype == "application/octet-stream"):
                raise ValueError(f"Unexpected content type for HeyGen video download: {ctype}")
            declared = resp.headers.get("Content-Length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise ValueError(f"HeyGen video is larger than the {max_bytes} byte limit")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            # Unique temp file in the same directory (never a shared <name>.part), then an
            # atomic rename, so concurrent downloads to one path cannot corrupt each other.
            fd, tmp_name = tempfile.mkstemp(dir=output_path.parent, prefix=output_path.name + ".", suffix=".part")
            tmp = Path(tmp_name)
            written = 0
            try:
                with os.fdopen(fd, "wb") as fh:
                    try:
                        for chunk in resp.iter_content(chunk_size=1024 * 1024):
                            written += len(chunk)
                            if written > max_bytes:
                                raise ValueError(f"HeyGen video exceeded the {max_bytes} byte limit")
                            fh.write(chunk)
                    except requests.RequestException as exc:
                        failure = type(exc).__name__
                    if failure:
                        raise RuntimeError(f"HeyGen video download failed: {failure}")
                if written == 0:
                    raise RuntimeError("HeyGen video download was empty")
                os.chmod(tmp, 0o644)  # mkstemp creates 0600; keep the usual mode for a media file
                os.replace(tmp, output_path)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            return written
        finally:
            resp.close()
    raise RuntimeError("Too many redirects downloading HeyGen video")


def upload_image_fal(image_path: str) -> str:
    """Upload a local image to fal.ai storage and return a public URL.

    The path goes through the same checks as HeyGen uploads (validate_upload_path:
    inside the allowed asset roots, png/jpeg/webp, at most 32 MB, magic bytes match
    the extension), so an agent-supplied path cannot publish an arbitrary local file.
    """
    import requests

    path, content_type = validate_upload_path(image_path)
    data_bytes = _read_validated_image(path, content_type)

    api_key = os.environ.get("FAL_KEY") or os.environ.get("FAL_AI_API_KEY")
    if not api_key:
        raise RuntimeError("FAL_KEY or FAL_AI_API_KEY required for image upload")

    # Initiate upload
    init_resp = requests.post(
        "https://rest.alpha.fal.ai/storage/upload/initiate",
        headers={"Authorization": f"Key {api_key}", "Content-Type": "application/json"},
        json={"content_type": content_type, "file_name": path.name},
        timeout=30,
    )
    init_resp.raise_for_status()
    data = init_resp.json()

    # Upload file content
    put_resp = requests.put(
        data["upload_url"],
        headers={"Content-Type": content_type},
        data=data_bytes,
        timeout=60,
    )
    put_resp.raise_for_status()

    return data["file_url"]


HEYGEN_MAX_UPLOAD_BYTES = 32 * 1024 * 1024
_UPLOAD_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _sniff_image_type(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _allowed_asset_roots() -> list[Path]:
    """Directories that reference images may be read from and videos written to:
    <repo>/projects, <repo>/assets and each OPENMONTAGE_ASSET_DIR entry (os.pathsep
    separated). Resolved, so symlinks in the roots themselves are followed."""
    repo_root = Path(__file__).resolve().parents[2]
    roots = [repo_root / "projects", repo_root / "assets"]
    for part in os.environ.get("OPENMONTAGE_ASSET_DIR", "").split(os.pathsep):
        if part.strip():
            roots.append(Path(part).expanduser())
    return [r.resolve() for r in roots]


def _heygen_default_output_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "projects" / "_heygen"


def validate_heygen_output_path(output_path: str | Path) -> Path:
    """Return the resolved path a HeyGen video may be written to, or raise ValueError.

    The path must resolve (symlinks followed, so a link pointing out of the roots is
    refused) inside the allowed asset roots, end in .mp4 and not be a directory.
    """
    resolved = Path(output_path).resolve()
    if not any(resolved.is_relative_to(root) for root in _allowed_asset_roots()):
        raise ValueError(f"Refusing to write {resolved.name}: output_path is outside the project asset directory")
    if resolved.suffix.lower() != ".mp4":
        raise ValueError(f"Refusing to write {resolved.name}: output_path must end in .mp4")
    if resolved.is_dir():
        raise ValueError(f"Refusing to write {resolved.name}: output_path is a directory")
    return resolved


def validate_heygen_upload_path(image_path: str) -> tuple[Path, str]:
    """Return (resolved path, content type) for an image that may be uploaded.

    The path must resolve (symlinks followed) inside <repo>/projects, <repo>/assets
    or OPENMONTAGE_ASSET_DIR. It must be a png, jpeg or webp of at most 32 MB whose
    magic bytes match its extension; the content type comes from the magic bytes.
    """
    resolved = Path(image_path).resolve()
    if not any(resolved.is_relative_to(root) for root in _allowed_asset_roots()):
        raise ValueError(f"Refusing to upload {resolved.name}: outside the project asset directory")
    if not resolved.is_file():  # after the roots check, so this is not a file-exists oracle
        raise FileNotFoundError(f"Image not found: {image_path}")
    expected = _UPLOAD_IMAGE_TYPES.get(resolved.suffix.lower())
    if not expected:
        raise ValueError(f"Refusing to upload {resolved.name}: only png, jpg, jpeg and webp images are allowed")
    size = resolved.stat().st_size
    if size == 0 or size > HEYGEN_MAX_UPLOAD_BYTES:
        raise ValueError(f"Refusing to upload {resolved.name}: size must be 1 to {HEYGEN_MAX_UPLOAD_BYTES} bytes")
    with resolved.open("rb") as fh:
        content_type = _sniff_image_type(fh.read(16))
    if content_type != expected:
        raise ValueError(f"Refusing to upload {resolved.name}: file content does not match its extension")
    return resolved, content_type


validate_upload_path = validate_heygen_upload_path  # generic name for non-HeyGen callers


def _read_validated_image(path: Path, content_type: str) -> bytes:
    """Read the file once and re-check size and magic bytes on the bytes that are sent,
    so a file swapped or grown after validate_upload_path is not uploaded."""
    data = path.read_bytes()
    if not data or len(data) > HEYGEN_MAX_UPLOAD_BYTES or _sniff_image_type(data[:16]) != content_type:
        raise ValueError(f"Refusing to upload {path.name}: file changed during validation")
    return data


def upload_image_heygen(image_path: str, api_key: str) -> dict[str, str]:
    """Upload a local image with POST /v3/assets (multipart) and return a v3
    asset input ({"type": "asset_id", "asset_id": ...}).

    Replaces POST /v2/assets/upload (retired Oct 31, 2026). The path is checked
    by validate_heygen_upload_path first. If the HeyGen upload fails the image is
    NOT sent to public fal.ai storage unless HEYGEN_ALLOW_FAL_FALLBACK=1; the
    fallback is logged as a warning.
    """
    import requests

    path, content_type = validate_heygen_upload_path(image_path)

    data = _read_validated_image(path, content_type)
    try:
        resp = requests.post(
            f"{HEYGEN_API_BASE}/v3/assets",
            headers={"X-Api-Key": api_key},
            files={"file": (path.name, data, content_type)},
            timeout=60,
        )
        asset_id = resp.json().get("data", {}).get("asset_id") if resp.status_code in (200, 201) else None
        failure = "no asset_id in response" if resp.status_code in (200, 201) else f"HTTP {resp.status_code}"
    except Exception as exc:
        asset_id, failure = None, type(exc).__name__
    if asset_id:
        return {"type": "asset_id", "asset_id": asset_id}

    if os.environ.get("HEYGEN_ALLOW_FAL_FALLBACK") != "1":
        raise RuntimeError(
            f"HeyGen asset upload failed ({failure}). The public fal.ai fallback is off; "
            "set HEYGEN_ALLOW_FAL_FALLBACK=1 to allow it."
        )
    logger.warning(
        "HeyGen asset upload failed (%s); uploading %s to public fal.ai storage (HEYGEN_ALLOW_FAL_FALLBACK=1)",
        failure,
        path.name,
    )
    return {"type": "url", "url": upload_image_fal(str(path))}


def generate_heygen_video(inputs: dict[str, Any]) -> ToolResult:
    import requests

    api_key = os.environ.get("HEYGEN_API_KEY")
    if not api_key:
        return ToolResult(success=False, error="HEYGEN_API_KEY not set.")

    provider = inputs.get("provider_variant", HEYGEN_DEFAULT_PROVIDER)
    if provider in HEYGEN_LEGACY_PROVIDERS:
        return ToolResult(
            success=False,
            error=(
                f"provider_variant {provider} used the HeyGen v1 workflows API, which HeyGen retires on "
                f"Oct 31, 2026, and has no documented v3 equivalent. Use {HEYGEN_DEFAULT_PROVIDER} "
                "(POST /v3/models/videos) or another video tool."
            ),
        )
    if provider not in HEYGEN_PROVIDERS:
        return ToolResult(
            success=False,
            error=f"Unknown provider_variant: {provider}. Available: {', '.join(sorted(HEYGEN_PROVIDERS))}",
        )

    prompt = inputs["prompt"]
    aspect_ratio = inputs.get("aspect_ratio", "16:9")
    operation = inputs.get("operation", "text_to_video")
    if operation not in ("text_to_video", "image_to_video"):
        return ToolResult(success=False, error=f"Unsupported operation: {operation}")
    if operation == "text_to_video" and inputs.get("resolution") in ("1080p", "2k") and aspect_ratio not in ("16:9", "9:16"):
        return ToolResult(
            success=False,
            error=f"HeyGen renders {inputs['resolution']} only in 16:9 or 9:16 for text_to_video, not {aspect_ratio}",
        )

    # Confine the output file before anything is created or billed.
    custom_output = inputs.get("output_path")
    try:
        output_path = validate_heygen_output_path(custom_output) if custom_output else None
    except ValueError as exc:
        return ToolResult(success=False, error=str(exc))

    # Resume: a job saved for the same request is polled instead of creating (and
    # billing) a new video. The saved Idempotency-Key also makes a retry after a
    # timed-out create return the original response.
    job_key = heygen_idempotency_key(inputs)
    with _heygen_job_lock(job_key):
        job = _load_heygen_job(job_key)
        if job is None:
            job = {"idempotency_key": uuid.uuid4().hex, "created_at": time.time()}
            _save_heygen_job(job_key, job)
        resumed = "video_id" in job

        if resumed:
            video_id = job["video_id"]
        else:
            body: dict[str, Any] = {"model": HEYGEN_V3_MODEL, "mode": operation, "prompt": prompt}
            if "duration" in inputs:
                body["duration"] = int(inputs["duration"])
            if "resolution" in inputs:
                body["resolution"] = inputs["resolution"]
            if operation == "image_to_video":
                ref_url = inputs.get("reference_image_url")
                ref_path = inputs.get("reference_image_path")
                if ref_url:
                    image = {"type": "url", "url": ref_url}
                elif ref_path:
                    image = upload_image_heygen(ref_path, api_key)
                else:
                    return ToolResult(
                        success=False,
                        error="image_to_video requires reference_image_url or reference_image_path",
                    )
                body["image"] = image  # image_to_video follows the first frame; no aspect_ratio
            else:
                body["aspect_ratio"] = aspect_ratio

            try:
                response = requests.post(
                    f"{HEYGEN_API_BASE}/v3/models/videos",
                    headers={
                        "X-Api-Key": api_key,
                        "Content-Type": "application/json",
                        "Idempotency-Key": job["idempotency_key"],
                    },
                    json=body,
                    timeout=30,
                )
                response.raise_for_status()
            except requests.HTTPError as exc:
                # A 4xx (not 409) means HeyGen rejected the request, so nothing was billed:
                # drop the saved key. A timeout or 5xx may have been accepted: keep it.
                code = getattr(exc.response, "status_code", 0) or 0
                if 400 <= code < 500 and code != 409:
                    _clear_heygen_job(job_key)
                raise
            payload = response.json()
            video_id = payload.get("data", {}).get("video_id")
            if not video_id:
                return ToolResult(success=False, error="No video_id in HeyGen v3 response")
            try:
                validate_heygen_video_id(video_id)  # before the poll URL and the file name
            except ValueError as exc:
                return ToolResult(success=False, error=str(exc))
            job["video_id"] = video_id
            _save_heygen_job(job_key, job)  # before polling, so a re-run resumes this id
    execution_id = video_id  # kept as a result field name for callers

    try:
        video_url = poll_heygen(execution_id, api_key, timeout=600)
    except HeyGenJobFailed:
        _clear_heygen_job(job_key)  # a failed job is not resumable; the next run starts fresh
        raise
    except requests.HTTPError as exc:
        if resumed and getattr(exc.response, "status_code", 0) == 404:
            _clear_heygen_job(job_key)
            raise RuntimeError(
                f"Saved HeyGen job {execution_id} no longer exists; cleared it, run again to start a new generation"
            ) from exc
        raise
    if output_path is None:
        output_path = validate_heygen_output_path(_heygen_default_output_dir() / f"heygen_video_{execution_id}.mp4")
    download_heygen_video(video_url, output_path)

    meta = HEYGEN_PROVIDERS[provider]
    return ToolResult(
        success=True,
        data={
            "provider": "heygen",
            "provider_variant": provider,
            "provider_name": meta["name"],
            "mode": "api",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "operation": operation,
            "execution_id": execution_id,
            "resumed": resumed,
            "output": str(output_path),
            "format": "mp4",
        },
        artifacts=[str(output_path)],
        model=provider,
    )


def generate_ltx_modal_video(inputs: dict[str, Any]) -> ToolResult:
    import base64

    import requests

    endpoint_url = os.environ.get("MODAL_LTX2_ENDPOINT_URL")
    if not endpoint_url:
        return ToolResult(success=False, error="MODAL_LTX2_ENDPOINT_URL not set.")

    prompt = inputs["prompt"]
    operation = inputs.get("operation", "text_to_video")
    aspect = inputs.get("aspect_ratio", "16:9")
    width = inputs.get("width")
    height = inputs.get("height")
    if width is None or height is None:
        if aspect == "16:9":
            width, height = 1024, 576
        elif aspect == "9:16":
            width, height = 576, 1024
        else:
            width, height = 512, 512

    num_frames = inputs.get("num_frames", LTX2_FRAME_COUNTS.get(inputs.get("duration_hint", "5s"), 121))
    if (num_frames - 1) % 8 != 0:
        num_frames = ((num_frames - 1) // 8) * 8 + 1

    payload: dict[str, Any] = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "fps": 24,
        "steps": inputs.get("num_inference_steps", 30),
        "negative_prompt": "worst quality, low quality, blurry, distorted, watermark, text, logo",
    }
    if inputs.get("seed") is not None:
        payload["seed"] = inputs["seed"]

    if operation == "image_to_video":
        ref_path = inputs.get("reference_image_path")
        ref_url = inputs.get("reference_image_url")
        if ref_path:
            payload["input_image"] = base64.b64encode(Path(ref_path).read_bytes()).decode()
        elif ref_url:
            payload["input_image_url"] = ref_url
        else:
            return ToolResult(
                success=False,
                error="image_to_video requires reference_image_url or reference_image_path",
            )

    response = requests.post(endpoint_url, json=payload, timeout=300)
    response.raise_for_status()
    output_path = Path(inputs.get("output_path", "ltx_video_modal.mp4"))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    content_type = response.headers.get("content-type", "")
    if "video" in content_type or "octet-stream" in content_type:
        output_path.write_bytes(response.content)
    else:
        response_payload = response.json()
        video_url = response_payload.get("video_url") or response_payload.get("url")
        if not video_url:
            return ToolResult(success=False, error=f"No video data in response: {response_payload}")
        download = requests.get(video_url, timeout=120)
        download.raise_for_status()
        output_path.write_bytes(download.content)

    return ToolResult(
        success=True,
        data={
            "provider": "ltx-modal",
            "provider_name": "LTX-2 (Modal)",
            "mode": "modal",
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "fps": 24,
            "duration_seconds": round(num_frames / 24, 2),
            "operation": operation,
            "output": str(output_path),
            "format": "mp4",
        },
        artifacts=[str(output_path)],
        seed=inputs.get("seed"),
        model="ltx-2",
    )


def probe_output(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"file_size_bytes": path.stat().st_size}
    if not shutil.which("ffprobe"):
        return info

    import json

    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0:
            probe = json.loads(proc.stdout)
            fmt = probe.get("format", {})
            info["duration_seconds"] = float(fmt.get("duration", 0))
            info["file_size_mb"] = round(path.stat().st_size / (1024 * 1024), 2)
            for stream in probe.get("streams", []):
                if stream.get("codec_type") == "video":
                    info["video_width"] = int(stream.get("width", 0))
                    info["video_height"] = int(stream.get("height", 0))
                    info["video_codec"] = stream.get("codec_name", "")
                    break
    except Exception:
        pass
    return info
