---
name: ai-video-gen
description: |
  Generate AI videos from text prompts using multiple provider gateways. Use when: (1) Generating videos from text descriptions, (2) Creating AI-generated video clips for content production, (3) Image-to-video generation with a reference image, (4) Choosing between video generation providers (VEO, Kling, Sora, Runway, Seedance, MiniMax). Supports two gateways: HeyGen API v3 and fal.ai API.
allowed-tools: mcp__heygen__*
metadata:
  openclaw:
    requires:
      env_any:
        - HEYGEN_API_KEY
        - FAL_KEY
---

# Video Generation (Multi-Gateway)

Generate AI videos from text prompts. HeyGen v1 and v2 REST, including `POST /v1/workflows/executions`, retire on October 31, 2026.

| Gateway | Env Variable | Providers | Tool |
|---------|-------------|-----------|------|
| **fal.ai** | `FAL_KEY` | Kling v3/v2.1, MiniMax, VEO | `kling_video`, `minimax_video`, `veo_video` |
| **HeyGen v3** | `HEYGEN_API_KEY` | `heygen-video-1` only | `heygen_video` (`tools/video/heygen_video.py`) |

**IMPORTANT:** Always use `video_selector` instead of calling provider tools directly. The selector handles availability checks, cost comparison, and automatic fallback.

HeyGen's old workflow gateway (`workflow_type: "GenerateVideoNode"` with `provider` values such as `veo_3_1`, `kling_pro`, `sora_v2`, `runway_gen4`, `seedance_pro`, or `ltx_distilled`) has no confirmed v3 equivalent. `tools/video/heygen_video.py` refuses those provider variants. Use the fal.ai tools above for Kling, MiniMax, and VEO. Use HeyGen only for `heygen-video-1`.

## Authentication

- **HeyGen:** `HEYGEN_API_KEY` sent as `X-Api-Key`.
- **fal.ai:** `FAL_KEY`.

Prefer the HeyGen MCP or `tools/video/heygen_video.py` inside this repo. The curls below match that tool and HeyGen's current model-video docs.

## HeyGen Video 1

`POST https://api.heygen.com/v3/models/videos`

`GET https://api.heygen.com/v3/models/videos/{video_id}`

The same completed job is also readable with `GET /v3/videos/{video_id}`.

### Text to video

```bash
curl -X POST "https://api.heygen.com/v3/models/videos" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "model": "heygen-video-1",
    "mode": "text_to_video",
    "prompt": "A drone shot flying over a coastal city at golden hour, cinematic lighting",
    "duration": 5,
    "resolution": "768p",
    "aspect_ratio": "16:9"
  }'
```

Submission returns `202` with `data.video_id` and `data.status` of `pending`. Retrying the same `Idempotency-Key` within 24 hours returns the original response.

### Image to video

`image_to_video` uses the image as the first frame. Do not send `aspect_ratio` on this mode. Upload a local file with `POST /v3/assets` (multipart field `file`) and pass the returned `asset_id`, or pass a public HTTPS URL.

```bash
curl -X POST "https://api.heygen.com/v3/models/videos" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "heygen-video-1",
    "mode": "image_to_video",
    "prompt": "Animate this product photo with a slow push-in",
    "image": { "type": "url", "url": "https://example.com/product-photo.png" },
    "duration": 5,
    "resolution": "768p"
  }'
```

`reference_to_video` is a third mode (prompt plus `reference_images`, `reference_videos`, and/or `reference_audio`). It is documented by HeyGen. This repo's `heygen_video` tool calls only `text_to_video` and `image_to_video`.

### Fields this repo and the docs both confirm

| Field | Notes |
|-------|--------|
| `model` | `heygen-video-1` |
| `mode` | `text_to_video` or `image_to_video` |
| `prompt` | Required |
| `duration` | Whole seconds. The tool schema allows 5–15. HeyGen's docs also allow 5–30 for `text_to_video` and `image_to_video` with turbo or quality enhancement. |
| `resolution` | `480p`, `768p` (default), `1080p`, `2k` |
| `aspect_ratio` | `16:9`, `9:16`, or `1:1` on `text_to_video`. `1080p` and `2k` text-to-video in this repo require `16:9` or `9:16`. |
| `image` | `image_to_video` only. `{ "type": "url", "url": "..." }` or `{ "type": "asset_id", "asset_id": "..." }` |

### Poll

```bash
curl "https://api.heygen.com/v3/models/videos/VIDEO_ID" \
  -H "X-Api-Key: $HEYGEN_API_KEY"
```

`pending` is queued, `processing` is running. Terminal states are `completed`, `failed`, and `cancelled`. A completed payload includes `data.video_url`. Failed and cancelled jobs include `failure_code` and `failure_message`. `video_url` is a signed link; poll again to refresh it.

```python
import os
import time
import requests

def generate_heygen_clip(prompt: str, aspect_ratio: str = "16:9") -> str:
    headers = {"X-Api-Key": os.environ["HEYGEN_API_KEY"]}
    created = requests.post(
        "https://api.heygen.com/v3/models/videos",
        headers=headers,
        json={
            "model": "heygen-video-1",
            "mode": "text_to_video",
            "prompt": prompt,
            "duration": 5,
            "resolution": "768p",
            "aspect_ratio": aspect_ratio,
        },
        timeout=30,
    )
    created.raise_for_status()
    video_id = created.json()["data"]["video_id"]
    deadline = time.time() + 600
    while time.time() < deadline:
        status = requests.get(
            f"https://api.heygen.com/v3/models/videos/{video_id}",
            headers=headers,
            timeout=30,
        )
        status.raise_for_status()
        data = status.json()["data"]
        if data["status"] == "completed":
            return data["video_url"]
        if data["status"] in ("failed", "cancelled"):
            raise RuntimeError(data.get("failure_message") or data["status"])
        time.sleep(5)
    raise TimeoutError(video_id)
```

Avatar videos with a script and a chosen look are a different API: `POST /v3/videos` with `type: "avatar"`. See the `avatar-video` skill. Prompt-built presenter videos are `POST /v3/video-agents`. See the `create-video` skill.

## Best practices

1. Describe camera, light, and sound in the prompt. `heygen-video-1` generates picture and audio together.
2. Use `9:16` for vertical social clips and `16:9` for landscape.
3. Poll about every 5–10 seconds. Jobs can take several minutes.
4. Download `video_url` promptly. It is a signed link.
5. For Kling, MiniMax, or VEO, use the fal.ai tools. Do not send those names as a HeyGen `provider`.
