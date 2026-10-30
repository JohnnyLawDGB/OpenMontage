---
name: video-translate
description: |
  Translate and dub existing videos into multiple languages using HeyGen v3. Use when: (1) Translating a video into another language, (2) Dubbing video content with lip-sync, (3) Creating multi-language versions of existing videos, (4) Audio-only translation without lip-sync, (5) Working with POST /v3/video-translations.
allowed-tools: mcp__heygen__*
metadata:
  openclaw:
    requires:
      env:
        - HEYGEN_API_KEY
    primaryEnv: HEYGEN_API_KEY
---

# Video Translation (HeyGen)

Translate and dub an existing video. HeyGen retires `POST /v2/video_translate` and `GET /v2/video_translate/{translate_id}` on October 31, 2026.

Prefer the HeyGen MCP (`create_video_translation`, `get_video_translation`, `list_video_translation_languages`) when it is connected.

| Retired | v3 |
|---------|----|
| `POST /v2/video_translate` | `POST /v3/video-translations` |
| `GET /v2/video_translate/{id}` | `GET /v3/video-translations/{video_translation_id}` |
| `GET /v2/video_translate/target_languages` | `GET /v3/video-translations/languages` |
| `GET /v2/video_translate/caption` | `srt_caption_url` and `vtt_caption_url` on the GET above |
| `POST /v2/video_translate/proofread` | `POST /v3/video-translations/proofreads` |

## Authentication

`X-Api-Key: $HEYGEN_API_KEY`

## Languages

Do not send BCP-47 codes such as `es-ES` unless `GET /v3/video-translations/languages` returns them. The confirmed request uses language names:

```bash
curl "https://api.heygen.com/v3/video-translations/languages" \
  -H "X-Api-Key: $HEYGEN_API_KEY"
```

## Create a translation

```bash
curl -X POST "https://api.heygen.com/v3/video-translations" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "video": { "type": "url", "url": "https://example.com/original-video.mp4" },
    "output_languages": ["Spanish"],
    "mode": "speed",
    "title": "Spanish Version"
  }'
```

One id is returned per language:

```json
{ "data": { "video_translation_ids": ["tr_abc123"] } }
```

Source video is `{ "type": "url", "url": "..." }` or `{ "type": "asset_id", "asset_id": "..." }` from `POST /v3/assets`. The URL must be publicly fetchable.

| Field | Default | Notes |
|-------|---------|-------|
| `output_languages` | required | Array of language names. Several languages return several ids. |
| `mode` | `speed` | `precision` is the slower, higher-fidelity lip-sync mode |
| `title` | | Display title |
| `translate_audio_only` | `false` | `true` translates audio and skips lip-sync |
| `speaker_num` | auto | Speaker count |
| `enable_dynamic_duration` | `true` | Output length may change to fit speech. Billing uses source duration. |
| `disable_music_track` | `false` | Drop background music |
| `enable_speech_enhancement` | `false` | Clean up speech |
| `brand_glossary_id` | | Pronunciations, do-not-translate terms, and forced translations. Create with `POST /v3/brand-glossaries`. |
| `callback_url`, `callback_id` | | One-off completion callback |

`enable_caption` is deprecated on this route and no longer changes the result. Captions arrive as URLs on the completed job.

These v2/v4-style fields are **not** confirmed on `POST /v3/video-translations`: `video_url`, `video_id` as top-level source keys, `output_language` (singular code), `vocabulary`, `srt_key`, `srt_role`, `instruction`, `google_url`, `input_video_id`, `keep_the_same_format`, `enable_video_stretching`. Keep a term untranslated with a brand glossary (`do_not_translate_terms`), not a `vocabulary` array. Editable subtitles use the proofread routes below.

### Audio only

```json
{
  "video": { "type": "url", "url": "https://example.com/original.mp4" },
  "output_languages": ["Spanish"],
  "translate_audio_only": true
}
```

## Poll

```bash
curl "https://api.heygen.com/v3/video-translations/VIDEO_TRANSLATION_ID" \
  -H "X-Api-Key: $HEYGEN_API_KEY"
```

| Status | Meaning |
|--------|---------|
| `pending` | Queued |
| `running` | In progress |
| `completed` | `video_url` is set. `srt_caption_url` and `vtt_caption_url` appear when those files exist. |
| `failed` | Read `failure_message` |

```python
import os
import time
import requests

def translate(video_url: str, language: str = "Spanish") -> str:
    headers = {"X-Api-Key": os.environ["HEYGEN_API_KEY"]}
    created = requests.post(
        "https://api.heygen.com/v3/video-translations",
        headers=headers,
        json={
            "video": {"type": "url", "url": video_url},
            "output_languages": [language],
            "mode": "speed",
        },
        timeout=60,
    )
    created.raise_for_status()
    translation_id = created.json()["data"]["video_translation_ids"][0]
    deadline = time.time() + 1800
    while time.time() < deadline:
        detail = requests.get(
            f"https://api.heygen.com/v3/video-translations/{translation_id}",
            headers=headers,
            timeout=30,
        )
        detail.raise_for_status()
        data = detail.json()["data"]
        if data["status"] == "completed":
            return data["video_url"]
        if data["status"] == "failed":
            raise RuntimeError(data.get("failure_message") or "failed")
        time.sleep(10)
    raise TimeoutError(translation_id)
```

List with `GET /v3/video-translations`. Delete with `DELETE /v3/video-translations/{video_translation_id}`.

## Proofread

`POST /v3/video-translations/proofreads` accepts the same video input plus `output_languages` and returns `proofread_ids`. Poll `GET /v3/video-translations/proofreads/{proofread_id}`. Download subtitles with `GET /v3/video-translations/proofreads/{proofread_id}/srt`, replace them with `PUT` of `{ "srt": { "type": "url", "url": "..." } }`, then `POST /v3/video-translations/proofreads/{proofread_id}/generate`. That returns a `video_translation_id` to poll on the translation GET.
