---
name: photo-avatars
description: Create a HeyGen photo avatar with POST /v3/avatars
---

# Photo Avatars

The `/v2/photo_avatar/*` routes, `POST /v2/video/av4/generate`, `GET /v1/talking_photo.list`, and `POST https://upload.heygen.com/v1/asset` retire on October 31, 2026.

## Create from a photo

No separate train call. `POST /v3/avatars` with `type: "photo"` is the confirmed replacement for `POST /v2/photo_avatar/avatar_group/create`. Photo avatars do not use the consent URL that digital twins require.

```bash
curl -X POST "https://api.heygen.com/v3/assets" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -F "file=@portrait.jpg"

curl -X POST "https://api.heygen.com/v3/avatars" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "photo",
    "name": "Sarah",
    "file": { "type": "asset_id", "asset_id": "ASSET_ID" }
  }'
```

`file` may instead be `{ "type": "url", "url": "https://..." }`. The response `data.avatar_item.id` is the `avatar_id` for video. Poll `GET /v3/avatars/looks/{look_id}` until the look is ready if the create response is still processing.

## Create from a text description

`POST /v2/photo_avatar/photo/generate` and `GET /v2/photo_avatar/generation/{id}` are replaced by `POST /v3/avatars` with `type: "prompt"`. Poll `GET /v3/avatars/looks/{look_id}` until `status` is `completed` or `failed`. The look id in that response is the `avatar_id` for `POST /v3/videos`.

```bash
curl -X POST "https://api.heygen.com/v3/avatars" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "prompt",
    "name": "Space Commander",
    "prompt": "Woman in her early 30s, confident expression, short silver hair, dark blue flight suit, spacecraft bridge, cinematic lighting",
    "aspect_ratio": "16:9"
  }'
```

`prompt` is at most 1000 characters. `aspect_ratio` is `16:9`, `9:16`, `1:1`, `4:5`, `5:4`, or `auto`. Pass an existing look as `avatar_id` to restyle that person instead of creating a new one. Up to three `reference_images` use the same `{ "type": "url" | "asset_id" | "base64" }` asset object.

## Render

Avatar IV is the default engine, which replaces `POST /v2/video/av4/generate`.

```bash
curl -X POST "https://api.heygen.com/v3/videos" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "avatar",
    "avatar_id": "PHOTO_LOOK_ID",
    "script": "Hi. This video was created from a single photo.",
    "voice_id": "VOICE_ID",
    "resolution": "1080p",
    "aspect_ratio": "auto",
    "motion_prompt": "nodding gently",
    "expressiveness": "low"
  }'
```

`motion_prompt` and `expressiveness` (`low`, `medium`, `high`) are photo-avatar fields on this request. `expressiveness` is rejected when `engine.type` is `avatar_v`.

## List, get, delete

| Retired | v3 |
|---------|----|
| `GET /v1/talking_photo.list` | `GET /v3/avatars/looks?avatar_type=photo_avatar` |
| `GET /v2/photo_avatar/{id}` | `GET /v3/avatars/looks/{look_id}` |
| `DELETE /v2/photo_avatar/{id}` | `DELETE /v3/avatars/looks/{look_id}` |
| `DELETE /v2/photo_avatar_group/{group_id}` | `DELETE /v3/avatars/{group_id}` |

Public presets: `GET /v3/avatars/looks?avatar_type=photo_avatar&ownership=public`. Use any returned look `id` as `avatar_id`.

## Not confirmed

These v2 calls have no 1:1 v3 path in the current docs or in this repo. Do not send them. Use the HeyGen MCP photo-avatar tools, or stop and say the operation is unmapped.

- `POST /v2/photo_avatar/avatar_group/add` (add another still to an existing group)
- `POST /v2/photo_avatar/train`
- `GET /v2/photo_avatar/train/status/{group_id}`

`POST /v3/avatars/looks` generates a curated look pack for an avatar you already own. That is a different operation from uploading an extra photo.

Use a front-facing, well-lit portrait. Sunglasses and covered foreheads produce worse lip-sync.
