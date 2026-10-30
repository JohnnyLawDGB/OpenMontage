---
name: dimensions
description: Resolution options (720p/1080p) and aspect ratios for HeyGen videos
---

# Video Dimensions and Resolution

HeyGen supports various video dimensions and aspect ratios to fit different platforms and use cases.

## Standard Resolutions

### Landscape (16:9)

| Resolution | Width | Height | Use Case |
|------------|-------|--------|----------|
| 720p | 1280 | 720 | Standard quality, faster processing |
| 1080p | 1920 | 1080 | High quality, most common |

### Portrait (9:16)

| Resolution | Width | Height | Use Case |
|------------|-------|--------|----------|
| 720p | 720 | 1280 | Mobile-first content |
| 1080p | 1080 | 1920 | High quality vertical |

### Square (1:1)

| Resolution | Width | Height | Use Case |
|------------|-------|--------|----------|
| 720p | 720 | 720 | Social media posts |
| 1080p | 1080 | 1080 | High quality square |

## Setting Dimensions

`POST /v2/video/generate` with `dimension: { width, height }` retires on October 31, 2026. `POST /v3/videos` takes `aspect_ratio` and `resolution`, not pixel width and height.

| `aspect_ratio` | Use |
|----------------|-----|
| `16:9` | YouTube, LinkedIn, landscape |
| `9:16` | TikTok, Reels, Shorts |
| `1:1` | Square feed |
| `4:5`, `5:4` | Social crops |
| `auto` | Match the avatar or image. Default in the HeyGen docs for new requests is often `16:9` unless you set `auto`. |

`resolution` on an avatar video is `720p`, `1080p`, or `4k` (`4k` only for Avatar III digital twins and studio avatars). `4:3` is not a confirmed `aspect_ratio`.

```bash
curl -X POST "https://api.heygen.com/v3/videos" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "avatar",
    "avatar_id": "LOOK_ID",
    "script": "Hello.",
    "voice_id": "VOICE_ID",
    "aspect_ratio": "16:9",
    "resolution": "1080p"
  }'
```

Pixel width and height still matter for Remotion compositions and for `POST /v3/templates/{template_id}`, which accepts `dimension: { width, height }` (even numbers, 128–4096, same aspect ratio as the template). The tables above are for that compositor, not for `POST /v3/videos`.

`heygen-video-1` (`POST /v3/models/videos`) uses `aspect_ratio` `16:9`, `9:16`, or `1:1` and `resolution` `480p`, `768p`, `1080p`, or `2k`. That is a different enum from avatar videos.

## Dimension Helper Functions

```typescript
type AspectRatio = "16:9" | "9:16" | "1:1" | "4:3" | "4:5";
type Quality = "720p" | "1080p";

interface Dimensions {
  width: number;
  height: number;
}

function getDimensions(aspectRatio: AspectRatio, quality: Quality): Dimensions {
  const configs: Record<AspectRatio, Record<Quality, Dimensions>> = {
    "16:9": {
      "720p": { width: 1280, height: 720 },
      "1080p": { width: 1920, height: 1080 },
    },
    "9:16": {
      "720p": { width: 720, height: 1280 },
      "1080p": { width: 1080, height: 1920 },
    },
    "1:1": {
      "720p": { width: 720, height: 720 },
      "1080p": { width: 1080, height: 1080 },
    },
    "4:3": {
      "720p": { width: 960, height: 720 },
      "1080p": { width: 1440, height: 1080 },
    },
    "4:5": {
      "720p": { width: 576, height: 720 },
      "1080p": { width: 864, height: 1080 },
    },
  };

  return configs[aspectRatio][quality];
}

// Usage
const youTubeDimensions = getDimensions("16:9", "1080p");
const tikTokDimensions = getDimensions("9:16", "1080p");
const instagramDimensions = getDimensions("1:1", "1080p");
```

## Platform-Specific Recommendations

### YouTube

```json
{ "type": "avatar", "aspect_ratio": "16:9", "resolution": "1080p" }
```

### TikTok / Instagram Reels / YouTube Shorts

```json
{ "type": "avatar", "aspect_ratio": "9:16", "resolution": "1080p" }
```

### Instagram Feed Post

```json
{ "type": "avatar", "aspect_ratio": "1:1", "resolution": "1080p" }
```

### LinkedIn

```json
{ "type": "avatar", "aspect_ratio": "16:9", "resolution": "1080p" }
```

### Twitter/X

```json
{ "type": "avatar", "aspect_ratio": "16:9", "resolution": "720p" }
```

## Avatar IV

Avatar IV is the default engine on `POST /v3/videos` when `engine` is omitted. It uses the same `aspect_ratio` and `resolution` fields as any other avatar video. Photo avatars should prefer `aspect_ratio: "auto"` so the frame follows the still.

Video Agent orientation is `landscape` or `portrait` on `POST /v3/video-agents`, not a pixel size.

## Custom pixel sizes

Arbitrary width and height are confirmed on `POST /v3/templates/{template_id}` only:

- Minimum 128px on a side, maximum 4096px
- Both sides even
- Must keep the template's aspect ratio

`POST /v3/videos` will reject a `dimension` object. Do not send one.

```typescript
function validateDimensions(width: number, height: number): boolean {
  if (width < 128 || height < 128) {
    throw new Error("Dimensions must be at least 128px");
  }
  if (width > 4096 || height > 4096) {
    throw new Error("Dimensions cannot exceed 4096px");
  }
  if (width % 2 !== 0 || height % 2 !== 0) {
    throw new Error("Dimensions must be even numbers");
  }
  return true;
}
```

## Resolution

`720p` is enough for a draft. `1080p` is the usual delivery size. Credit cost depends on the account. Read the balance with `GET /v3/users/me` (see [quota.md](quota.md)) instead of assuming a fixed multiplier.

## Background Considerations

Match background image/video dimensions to your video dimensions:

```json
{
  "type": "avatar",
  "aspect_ratio": "16:9",
  "resolution": "1080p",
  "background": { "type": "image", "url": "https://example.com/1920x1080-background.jpg" }
}
```

## Creating a Video Config Factory

```typescript
interface VideoConfigOptions {
  script: string;
  avatarId: string;
  voiceId: string;
  platform: "youtube" | "tiktok" | "instagram_feed" | "instagram_story" | "linkedin";
  quality?: "720p" | "1080p";
}

function createVideoConfig(options: VideoConfigOptions) {
  const aspectRatio: Record<string, "16:9" | "9:16" | "1:1"> = {
    youtube: "16:9",
    tiktok: "9:16",
    instagram_feed: "1:1",
    instagram_story: "9:16",
    linkedin: "16:9",
  };

  return {
    type: "avatar" as const,
    avatar_id: options.avatarId,
    voice_id: options.voiceId,
    script: options.script,
    aspect_ratio: aspectRatio[options.platform],
    resolution: options.quality ?? "1080p",
  };
}

// Usage
const tiktokVideo = createVideoConfig({
  script: "Hey everyone! Check this out!",
  avatarId: "josh_lite3_20230714",
  voiceId: "1bd001e7e50f421d891986aad5158bc8",
  platform: "tiktok",
  quality: "1080p",
});
```
