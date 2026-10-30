---
name: text-overlays
description: On-screen text for HeyGen videos after the v2 overlay payload was retired
---

# Text Overlays

HeyGen's v2 `video_inputs` text-overlay payload (fonts, x/y positions, lower thirds, timed title cards) retires with `POST /v2/video/generate` on October 31, 2026.

No equivalent freeform overlay object is confirmed on `POST /v3/videos`. Do not send the old overlay JSON to v3.

Confirmed ways to put words on screen:

1. **Template text variables.** `POST /v3/templates/{template_id}` with `variables.{name} = { "type": "text", "content": "..." }`. The position and font are whatever the Studio template already designed. See [templates.md](templates.md).
2. **Video Agent prompt.** Name the on-screen words in the `prompt` for `POST /v3/video-agents`. The agent lays them out. It will not honor pixel coordinates.
3. **HeyGen MCP** (`create_video_agent` or template generation) when you do not want to call REST yourself.
4. **Composite after render.** Burn titles in Remotion on top of the MP4 or WebM from `POST /v3/videos`. That path is local and does not use a retired HeyGen overlay endpoint.

`caption.style` burns subtitles, not arbitrary title cards. See [captions.md](captions.md).
