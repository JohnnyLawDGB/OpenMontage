---
name: text-to-speech
description: |
  Generate speech audio from text using HeyGen. Use when: (1) Generating standalone speech audio files from text, (2) Converting text to speech with voice selection and speed control, (3) Creating audio for voiceovers, narration, or podcasts, (4) Working with HeyGen POST /v3/voices/speech or POST /v3/models/audio/tts, (5) Listing voices with GET /v3/voices.
allowed-tools: mcp__heygen__*
metadata:
  openclaw:
    requires:
      env:
        - HEYGEN_API_KEY
    primaryEnv: HEYGEN_API_KEY
---

# Text-to-Speech (HeyGen)

Generate a standalone audio file from text. HeyGen retires `GET /v1/audio/voices`, `GET /v2/voices`, and `POST /v1/audio/text_to_speech` on October 31, 2026.

Prefer the HeyGen MCP (`list_voices`, `create_speech`) when it is connected. The REST calls below are the confirmed v3 replacements.

Catalog and designed voices, including Starfish:

- `GET https://api.heygen.com/v3/voices`
- `POST https://api.heygen.com/v3/voices/speech`

HeyGen Voice clones (instant or professional) speak through a different route, `POST /v3/models/audio/tts`. Filter the catalog with `GET /v3/voices?engine=starfish` when you need a Starfish voice. Each voice reports `available_engines` and `default_engine`.

## Authentication

Send `X-Api-Key: $HEYGEN_API_KEY` on every request.

## List voices

```bash
curl "https://api.heygen.com/v3/voices?engine=starfish" \
  -H "X-Api-Key: $HEYGEN_API_KEY"
```

Confirmed query filters: `engine` (`orca`, `starfish`, `elevenlabs`), `language`, `gender`, and `type`. Pagination is cursor-based (`has_more`, `next_token`). Check `support_pause` before inserting break tags.

`GET /v1/audio/voices` and `GET /v2/voices` are the same v3 list. There is no longer a separate audio-voices host path.

## Generate speech

`POST https://api.heygen.com/v3/voices/speech`

| Field | Required | Notes |
|-------|:--------:|-------|
| `text` | yes | 1–5,000 characters |
| `voice_id` | yes | From `GET /v3/voices` |
| `engine` | no | `orca` (HeyGen Voice catalog), `starfish`, or `elevenlabs`. Omit to use the voice default. |
| `speed` | no | 0.5–2.0, default 1.0 |
| `language` | no | Base code such as `en`. Auto-detected when omitted. |
| `locale` | no | BCP-47 tag such as `en-US`. Overrides `language`. Starfish uses `locale`. |
| `settings.model_id` | no | ElevenLabs only. Confirmed ids include `eleven_v4`, `eleven_v3`, `eleven_multilingual_v2`, `eleven_flash_v2`, `eleven_flash_v2_5`, `eleven_turbo_v2_5`. |
| `force_regenerate` | no | Skip the speech cache |

Pitch is not a confirmed field on this endpoint. Avatar video requests accept `voice_settings.pitch` on `POST /v3/videos` instead.

```bash
curl -X POST "https://api.heygen.com/v3/voices/speech" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello from HeyGen. <break time=\"1s\"/> Let us get started.",
    "voice_id": "VOICE_ID",
    "engine": "starfish",
    "locale": "en-US",
    "speed": 1.0
  }'
```

```json
{
  "data": {
    "audio_url": "https://files.heygen.ai/audio/req_xyz789.mp3",
    "duration": 2.4,
    "engine": "starfish",
    "request_id": "req_xyz789"
  }
}
```

`word_timestamps` is included when the engine returns them. `<break time="1s"/>` is the only markup to put in `text`. The same tag works inside `script` on `POST /v3/videos`.

```python
import os
import requests

def synthesize(text: str, voice_id: str) -> str:
    response = requests.post(
        "https://api.heygen.com/v3/voices/speech",
        headers={"X-Api-Key": os.environ["HEYGEN_API_KEY"]},
        json={"text": text, "voice_id": voice_id, "engine": "starfish"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["data"]["audio_url"]
```

A `400` means the voice, plan, or language cannot use the requested engine. Read `available_engines` and pick another. A `403` with `ai_vendor_access_restricted` means a workspace admin has blocked ElevenLabs.

## HeyGen Voice clones

Instant and professional clones are not spoken with `POST /v3/voices/speech`. HeyGen documents `POST /v3/models/audio/tts` (and `/v3/models/audio/tts/stream`) for those voices, and `GET /v3/models/audio/voices` to list them. This repo's video tool does not call the speech routes. If MCP `create_speech` is available, use that and let it select the engine.
