---
name: voices
description: List HeyGen voices and apply them on v3 video and speech calls
---

# HeyGen Voices

`GET /v2/voices` and `GET /v1/audio/voices` retire on October 31, 2026. Both are `GET https://api.heygen.com/v3/voices`.

```bash
curl "https://api.heygen.com/v3/voices?language=en&gender=female" \
  -H "X-Api-Key: $HEYGEN_API_KEY"
```

Confirmed filters: `type`, `engine` (`orca`, `starfish`, `elevenlabs`), `language`, `gender`. Each voice includes `voice_id`, `available_engines`, `default_engine`, and `support_pause`. Pagination is `has_more` / `next_token`.

## Use a voice on an avatar video

`POST /v3/videos` with `type: "avatar"`:

```json
{
  "type": "avatar",
  "avatar_id": "LOOK_ID",
  "script": "Hello. <break time=\"0.5s\"/> Welcome back.",
  "voice_id": "VOICE_ID",
  "voice_settings": { "speed": 1.0, "pitch": 0, "locale": "en-US" }
}
```

Omit `voice_id` to use the avatar's default voice. `voice_settings` applies only when the video is synthesized from `script`.

| Setting | Range | Default |
|---------|-------|---------|
| `speed` | 0.5–1.5 | 1 |
| `pitch` | -50 to 50 semitones | 0 |
| `volume` | 0–1 | 1 |
| `locale` | BCP-47, such as `en-US` | omitted |

`<break time="1s"/>` inside `script` is confirmed. Check `support_pause` on the voice first.

Standalone audio (no video) is `POST /v3/voices/speech`. Its `speed` range is 0.5–2.0, and pitch is not a confirmed field there. See the `text-to-speech` skill. HeyGen Voice clones use `POST /v3/models/audio/tts` instead of `/v3/voices/speech`.

## Bring your own audio

On `POST /v3/videos`, `audio_url` or `audio_asset_id` replaces `script` and `voice_id`. Send exactly one audio source. Upload the file with `POST /v3/assets` first if it is not a public URL.

## Clone

`POST /v3/voices/clone` creates a clone from an audio file and returns a `voice_clone_id`. Poll `GET /v3/voices/{voice_clone_id}` until `status` is `complete`. That voice can be used with `POST /v3/voices/speech` and `POST /v3/videos`.
