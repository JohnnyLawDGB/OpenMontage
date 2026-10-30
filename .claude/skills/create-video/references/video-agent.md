---
name: video-agent
description: Create a HeyGen Video Agent session with POST /v3/video-agents
---

# Video Agent API

`POST /v1/video_agent/generate` retires on October 31, 2026. The v3 call is flat. There is no nested `config` object.

Prefer MCP `generate_video_agent` (or `create_video_agent`) when it is connected. Poll the returned `video_id` with MCP `get_video` or `GET /v3/videos/{video_id}`.

## Create

`POST https://api.heygen.com/v3/video-agents`

| Field | Required | Notes |
|-------|:--------:|-------|
| `prompt` | yes | 1–10,000 characters |
| `mode` | no | `generate` (default, one video) or `chat` (may pause for a decision) |
| `avatar_id` | no | Look id from `GET /v3/avatars/looks` |
| `voice_id` | no | Narration voice |
| `style_id` | no | From `GET /v3/video-agents/styles` |
| `orientation` | no | `landscape` or `portrait`. Omitted means the agent chooses. |
| `files` | no | Up to 20 items: `{ "type": "asset_id", "asset_id" }`, `{ "type": "url", "url" }`, or `{ "type": "base64", "media_type", "data" }` |
| `callback_url`, `callback_id` | no | Completion callback |
| `brand_kit_id`, `brand_glossary_id` | no | Optional branding |

```bash
curl -X POST "https://api.heygen.com/v3/video-agents" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A 60-second product demo of a matte black kettle, calm studio lighting.",
    "mode": "generate",
    "orientation": "landscape"
  }'
```

```json
{
  "data": {
    "session_id": "sess_012abc",
    "status": "generating",
    "video_id": null,
    "created_at": 1711929600
  }
}
```

`status` is `generating`, `thinking`, `completed`, or `failed`. `video_id` is null until a render exists. Poll `GET /v3/videos/{video_id}` once it is set. Session status values and video status values are different. The video uses `pending` / `processing` / `completed` / `failed`.

Follow-up messages on a `chat` session go to `POST /v3/video-agents/{session_id}`. Do not invent a v1 `config.duration_sec` field. Duration is not a confirmed field on this request. Say the length in the prompt.

### With a look and a file

```json
{
  "prompt": "Use the attached screenshot as the product and keep the narration under 45 seconds.",
  "avatar_id": "LOOK_ID",
  "voice_id": "VOICE_ID",
  "files": [{ "type": "asset_id", "asset_id": "ASSET_ID" }]
}
```

Upload the file first with `POST /v3/assets`. See [assets.md](assets.md).

## When to use Video Agent vs `POST /v3/videos`

Video Agent writes the script and picks scenes from the prompt. `POST /v3/videos` with `type: "avatar"` speaks the script you send and does not rewrite it. Use studio (`type: "studio"`) when each scene has its own script and background.

Prompt structure still lives in [prompt-optimizer.md](prompt-optimizer.md) and [visual-styles.md](visual-styles.md). Those files describe the prompt, not the HTTP body.
