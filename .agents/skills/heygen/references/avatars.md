---
name: avatars
description: List HeyGen avatar groups and looks on v3
---

# HeyGen Avatars

HeyGen retires `GET /v2/avatars`, `GET /v2/avatar_group.list`, `GET /v2/avatar_group/{group_id}/avatars`, and `GET /v2/avatar/{avatar_id}/details` on October 31, 2026.

The id you pass as `avatar_id` to `POST /v3/videos` is a **look** id, not a group id.

| Task | Endpoint |
|------|----------|
| List characters (groups) | `GET /v3/avatars` |
| List looks | `GET /v3/avatars/looks` |
| Looks in one group | `GET /v3/avatars/looks?group_id={group_id}` |
| One look | `GET /v3/avatars/looks/{look_id}` |
| One group | `GET /v3/avatars/{group_id}` |

```bash
curl "https://api.heygen.com/v3/avatars/looks?ownership=public&limit=20" \
  -H "X-Api-Key: $HEYGEN_API_KEY"
```

Confirmed filters on list looks: `group_id`, `avatar_type` (for example `photo_avatar`), and `ownership` (`public` or private). Pagination uses `has_more` and `next_token`.

A look payload includes preview URLs, training status, preferred orientation, and `supported_api_engines`. Pass `engine` on `POST /v3/videos` only when that list contains the engine. Avatar IV is the default when `engine` is omitted.

`GET /v2/avatar/{id}/details` used to return `default_voice_id`. The v3 look response does not document that field. Omit `voice_id` on `POST /v3/videos` and HeyGen uses the avatar's default voice.

Avatar styles named `normal`, `closeUp`, and `circle` are v2 fields with no confirmed v3 equivalent. Framing on v3 is `fit`: `cover` fills the frame, `contain` fits inside it. Omit `fit` to let the server choose.

Photo avatars are looks with `avatar_type=photo_avatar`. Create them with `POST /v3/avatars` and `"type": "photo"`. See [photo-avatars.md](photo-avatars.md).

```python
import os
import requests

def list_looks() -> list[dict]:
    response = requests.get(
        "https://api.heygen.com/v3/avatars/looks",
        headers={"X-Api-Key": os.environ["HEYGEN_API_KEY"]},
        params={"limit": 20},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    return body.get("data") or []
```

Use the look `id` as `avatar_id` in [video-generation.md](video-generation.md).
