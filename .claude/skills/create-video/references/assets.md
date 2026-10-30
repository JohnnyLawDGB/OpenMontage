---
name: assets
description: Upload images, audio, and video for HeyGen v3 requests
---

# Asset Upload

HeyGen retires `POST https://upload.heygen.com/v1/asset` on October 31, 2026. That call returned an `image_key`. v3 returns an `asset_id`.

Prefer the HeyGen MCP asset tools when they are connected. Otherwise:

## Upload a file (32 MB or smaller)

`POST https://api.heygen.com/v3/assets` as `multipart/form-data`. The form field name is `file`.

```bash
curl -X POST "https://api.heygen.com/v3/assets" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -F "file=@./portrait.png"
```

```json
{
  "data": {
    "asset_id": "asset_abc123",
    "url": "https://files.heygen.ai/assets/asset_abc123.png",
    "mime_type": "image/png",
    "size_bytes": 245760
  }
}
```

Confirmed types for this call: png, jpeg, mp4, webm, mp3, wav, pdf. This repo's `upload_image_heygen` sends png, jpeg, or webp to the same endpoint for `heygen-video-1` image-to-video. Webp is accepted by that tool; HeyGen's upload guide lists png and jpeg for images.

```python
import os
import requests

with open("portrait.png", "rb") as handle:
    response = requests.post(
        "https://api.heygen.com/v3/assets",
        headers={"X-Api-Key": os.environ["HEYGEN_API_KEY"]},
        files={"file": ("portrait.png", handle, "image/png")},
        timeout=60,
    )
response.raise_for_status()
asset_id = response.json()["data"]["asset_id"]
```

## Larger files

Files over 32 MB use direct upload (up to 200 MB for video, image, PDF, and zip; 1.5 GB for audio):

1. `POST /v3/assets/direct-uploads` with `filename`, `content_type`, and `size_bytes`.
2. `PUT` the raw bytes to `upload_url` with every header in `upload_headers`.
3. `POST /v3/assets/{asset_id}/complete`.

The `asset_id` is usable after step 3. Delete with `DELETE /v3/assets/{asset_id}`.

## Use the asset

Pass a discriminated object. Do not send `image_key`.

| Where | Shape |
|-------|--------|
| Video Agent `files[]` | `{ "type": "asset_id", "asset_id": "..." }` |
| `POST /v3/models/videos` image-to-video `image` | `{ "type": "asset_id", "asset_id": "..." }` |
| Avatar video background | `{ "type": "image", "asset_id": "..." }` |
| Photo avatar `file` | `{ "type": "asset_id", "asset_id": "..." }` |
| Avatar video lip-sync audio | top-level `audio_asset_id` (mutually exclusive with `script`) |

Public HTTPS URLs use `{ "type": "url", "url": "..." }` and skip the upload. URL images are capped at 16 MB; URL video, audio, and PDF at 32 MB.
