---
name: video-status
description: Poll, list, and delete HeyGen v3 videos
---

# Video Status and Polling

`GET /v1/video_status.get` and `GET /v2/videos/{video_id}` retire on October 31, 2026.

| Task | Endpoint |
|------|----------|
| Avatar, studio, template, or Video Agent render | `GET /v3/videos/{video_id}` |
| `heygen-video-1` model clip | `GET /v3/models/videos/{video_id}` (also visible on `GET /v3/videos/{video_id}`) |
| List | `GET /v3/videos` |
| Delete | `DELETE /v3/videos/{video_id}` |

Prefer MCP `get_video` when it is connected. It should call the v3 status route.

```bash
curl "https://api.heygen.com/v3/videos/VIDEO_ID" \
  -H "X-Api-Key: $HEYGEN_API_KEY"
```

| Status | Meaning |
|--------|---------|
| `pending`, `waiting` | Queued |
| `processing` | Rendering |
| `completed` | Read `video_url`. A sidecar caption is `subtitle_url` when captions were requested. |
| `failed` | Read `failure_message` (and `failure_code` when present) |
| `cancelled` | Model jobs only (`GET /v3/models/videos/{id}`) |

`video_url` is a signed link. Poll again if it expires. Download the file rather than storing the URL.

```python
import os
import time
import requests

def wait_for_video(video_id: str, timeout: int = 900) -> str:
    headers = {"X-Api-Key": os.environ["HEYGEN_API_KEY"]}
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = requests.get(
            f"https://api.heygen.com/v3/videos/{video_id}",
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()["data"]
        status = data.get("status", "")
        if status == "completed" and data.get("video_url"):
            return data["video_url"]
        if status in ("failed", "cancelled"):
            raise RuntimeError(data.get("failure_message") or status)
        time.sleep(10)
    raise TimeoutError(video_id)
```

List is cursor-paginated (`limit`, `token`, `has_more`, `next_token`) and can filter by `folder_id` or a title substring.

```bash
curl -X DELETE "https://api.heygen.com/v3/videos/VIDEO_ID" \
  -H "X-Api-Key: $HEYGEN_API_KEY"
```

Deletion is permanent.

For one video, `callback_url` on the create call avoids polling. For every video, register `POST /v3/webhooks/endpoints`. See [webhooks.md](webhooks.md). Keep polling as the fallback. A callback is attempted once.
