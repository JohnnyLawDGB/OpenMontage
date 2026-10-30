---
name: captions
description: Captions on HeyGen POST /v3/videos
---

# Video Captions

The v2 `caption: true` flag beside `video_inputs` retires with `POST /v2/video/generate` on October 31, 2026.

On `POST /v3/videos` (`type: "avatar"` or `type: "image"`), a sidecar subtitle file is always produced. Read `subtitle_url` from `GET /v3/videos/{video_id}` after `status` is `completed`.

```json
{
  "type": "avatar",
  "avatar_id": "LOOK_ID",
  "script": "Hello. This video includes a subtitle file.",
  "voice_id": "VOICE_ID",
  "caption": { "file_format": "srt" }
}
```

Set `caption.style` to also burn captions into the picture. Omit `style` for a sidecar only. The exact style object is not repeated here. If you need a named burn-in preset, use a Studio template (`caption: true` on `POST /v3/templates/{template_id}`, optional `subtitles.preset_name`) or the HeyGen MCP.

`file_format` defaults to `srt`.

Translated videos do not use this object. A completed `GET /v3/video-translations/{id}` returns `srt_caption_url` and `vtt_caption_url` when those files exist. `enable_caption` on the translation request is deprecated and changes nothing.

Position, font, and highlight fields from the old caption helper (`alignment`, bottom vs top, custom SRT upload on the create call) are not confirmed on `POST /v3/videos`. Do not send them. Template `subtitles` accepts `preset_name` plus optional `alignment`, `disable_highlight`, `font_size`, and `position`.

For social crops, set `aspect_ratio` to `9:16` and burn captions in only when the style is known. Otherwise deliver the sidecar and composite in Remotion.
