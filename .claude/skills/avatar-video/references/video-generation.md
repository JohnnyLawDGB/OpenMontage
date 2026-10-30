---
name: video-generation
description: Create HeyGen avatar and studio videos with POST /v3/videos
---

# Video Generation

`POST /v2/video/generate` and `POST /v1/video.webm` retire on October 31, 2026. Avatar and multi-scene videos are both `POST https://api.heygen.com/v3/videos`. Poll with `GET /v3/videos/{video_id}`.

Prompt-only clips with no avatar look (`heygen-video-1`) are a different route: `POST /v3/models/videos`. See the `ai-video-gen` skill.

Prefer the HeyGen MCP when it is connected (`create_video_from_avatar`).

## Single avatar video

```bash
curl -X POST "https://api.heygen.com/v3/videos" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "avatar",
    "avatar_id": "LOOK_ID",
    "script": "Hi. This is the exact line the avatar speaks.",
    "voice_id": "VOICE_ID",
    "title": "Product intro",
    "resolution": "1080p",
    "aspect_ratio": "16:9",
    "output_format": "mp4",
    "background": { "type": "color", "value": "#1a1a2e" }
  }'
```

```json
{ "data": { "video_id": "v_abc123", "status": "waiting" } }
```

`avatar_id` is a look id from `GET /v3/avatars/looks`. Omit `voice_id` to use that avatar's default voice. `script` and `audio_url` / `audio_asset_id` are mutually exclusive.

| Field | Notes |
|-------|--------|
| `type` | `avatar` |
| `resolution` | `720p`, `1080p`, or `4k` (`4k` only for Avatar III digital twins and studio avatars) |
| `aspect_ratio` | `16:9` (default), `9:16`, `4:5`, `5:4`, `1:1`, `auto` |
| `fit` | `cover` or `contain`. Omit to let the server choose. |
| `output_format` | `mp4` (default) or `webm` |
| `background` | `{ "type": "color", "value": "#RRGGBB" }` or `{ "type": "image", "url": "..." }` or `{ "type": "image", "asset_id": "..." }` |
| `remove_background` | boolean. Video avatars must be trained with matting. |
| `voice_settings` | `speed` 0.5–1.5, `pitch` -50–50, `volume` 0–1, `locale` |
| `caption` | `{ "file_format": "srt", "style": null }`. A sidecar is always returned as `subtitle_url`. Set `style` to burn captions into the picture. |
| `engine` | Omit for Avatar IV. `{ "type": "avatar_v" }` or `{ "type": "avatar_iii" }` only if the look's `supported_api_engines` includes it. |
| `motion_prompt` | Photo avatars, and video avatars only when `engine.type` is `avatar_v` |
| `expressiveness` | Photo avatars on Avatar IV: `low` (default), `medium`, `high` |
| `callback_url`, `callback_id` | Optional completion webhook for this video |

v2 fields with no confirmed place on this body: `video_inputs`, `character`, `avatar_style` (`normal`, `closeUp`, `circle`), `input_text`, `dimension: { width, height }`. Pixel width and height are a template override (`POST /v3/templates/{id}`), not this call.

### Transparent WebM

Replaces `POST /v1/video.webm`. The avatar must support matting.

```json
{
  "type": "avatar",
  "avatar_id": "LOOK_ID",
  "script": "Hi. This file has an alpha channel.",
  "voice_id": "VOICE_ID",
  "resolution": "1080p",
  "aspect_ratio": "16:9",
  "output_format": "webm"
}
```

Do not send `background` together with `output_format: "webm"`. The response echoes `output_format`. The completed `video_url` is a WebM. `type: "cinematic_avatar"` has no `output_format`.

### Your own audio

```json
{
  "type": "avatar",
  "avatar_id": "LOOK_ID",
  "audio_asset_id": "ASSET_ID",
  "aspect_ratio": "16:9",
  "resolution": "1080p"
}
```

`audio_url` is the public-URL form of the same idea.

## Several scenes

`type: "studio"` replaces a multi-scene `video_inputs` array. Output settings are global. Send 1–50 scenes. Rendering is all-or-nothing. The container is MP4 (`output_format` is not on this type).

Studio color backgrounds use `color`, not `value`.

```bash
curl -X POST "https://api.heygen.com/v3/videos" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "studio",
    "title": "Two scenes",
    "aspect_ratio": "16:9",
    "resolution": "1080p",
    "scenes": [
      {
        "type": "avatar_video",
        "input": {
          "type": "avatar",
          "avatar_id": "LOOK_ID",
          "script": "Welcome to the quarterly update.",
          "voice_id": "VOICE_ID",
          "background": { "type": "color", "color": "#1a1a2e" }
        }
      },
      {
        "type": "avatar_video",
        "input": {
          "type": "avatar",
          "avatar_id": "LOOK_ID",
          "script": "Revenue grew 25 percent.",
          "voice_id": "VOICE_ID",
          "background": {
            "type": "image",
            "source": { "type": "url", "url": "https://example.com/chart.png" }
          }
        }
      }
    ]
  }'
```

Other confirmed scene types on the same array are `image` and `video`. A studio video background is `{ "type": "video", "source": { "type": "url", "url": "..." } }` on an `avatar_video` scene. It is muted and loops. Image and video backgrounds cover the frame.

`<break time="1s"/>` inside `script` is confirmed. There is no confirmed test-mode flag. Use a short script to draft.

## Poll

```bash
curl "https://api.heygen.com/v3/videos/VIDEO_ID" \
  -H "X-Api-Key: $HEYGEN_API_KEY"
```

`pending` or `waiting` means queued, `processing` means rendering, `completed` means `video_url` is ready, `failed` includes `failure_message`. See [video-status.md](video-status.md).

## Batches

Up to 100 videos in one call: `POST /v3/videos/batches`. Poll the batch id. Per-item bodies use the same `type` values as a single create.
