---
name: backgrounds
description: Backgrounds on HeyGen POST /v3/videos
---

# Video Backgrounds

`video_inputs[].background` on `POST /v2/video/generate` retires on October 31, 2026. v3 has two different background objects. Do not mix them.

## One avatar (`type: "avatar"`)

`background.type` is `color` or `image` only. There is no video background on this type.

```json
{
  "type": "avatar",
  "avatar_id": "LOOK_ID",
  "script": "Hello with a colored background.",
  "voice_id": "VOICE_ID",
  "background": { "type": "color", "value": "#FFFFFF" }
}
```

```json
{ "type": "image", "url": "https://example.com/office.jpg" }
```

```json
{ "type": "image", "asset_id": "ASSET_ID" }
```

`url` and `asset_id` are mutually exclusive. Upload with `POST /v3/assets`.

Transparent output is `output_format: "webm"`, not a color of `#00FF00` and not `POST /v1/video.webm`. WebM rejects a `background` object. The avatar must support matting. A green screen color is only useful when you will chroma-key an MP4 yourself.

`remove_background: true` on an MP4 removes the plate but the file still has no alpha channel. Use WebM when the compositor needs transparency.

## Several scenes (`type: "studio"`)

On an `avatar_video` scene, `input.background` uses `color` (the hex field), not `value`:

```json
{ "type": "color", "color": "#1a2b3c" }
```

```json
{ "type": "image", "source": { "type": "url", "url": "https://example.com/office.jpg" } }
```

```json
{ "type": "video", "source": { "type": "asset_id", "asset_id": "ASSET_ID" } }
```

Image and video backgrounds cover the frame. A video background is muted and loops for the scene. Each scene can set its own background. See [video-generation.md](video-generation.md).

Match the background image's aspect ratio to `aspect_ratio` so `cover` scaling does not crop the subject of the plate.
