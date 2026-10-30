---
name: templates
description: List HeyGen Studio templates and render them on v3
---

# Video Templates

`GET /v2/templates`, `GET /v2/template/{template_id}`, and `POST /v2/template/{template_id}/generate` retire on October 31, 2026.

| Task | Endpoint |
|------|----------|
| List | `GET /v3/templates` |
| Read variables | `GET /v3/templates/{template_id}` |
| Render | `POST /v3/templates/{template_id}` |
| Poll | `GET /v3/videos/{video_id}` |

```bash
curl "https://api.heygen.com/v3/templates?limit=100" \
  -H "X-Api-Key: $HEYGEN_API_KEY"
```

The list returns `data.templates[]` with `id`, `name`, `thumbnail_url`, `aspect_ratio`, `created_at`, `updated_at`, plus `has_more` and `next_token`.

`GET /v3/templates/{template_id}` returns `variables` keyed by name. Each value uses the same shape you send back:

| `type` | Fields |
|--------|--------|
| `text` | `content` (required on generate, max 10,000 characters) |
| `image`, `video` | `asset` (`url`, `asset_id`, or `base64`) and optional `fit` (`cover`, `contain`, `crop`, `none`) |
| `audio` | `asset` |
| `voice` | `voice_id`, optional `locale` |
| `character` | `avatar_id` (a look id). Send `avatar_id`, not `avatar_look_id` or `character_id`. |

```bash
curl -X POST "https://api.heygen.com/v3/templates/TEMPLATE_ID" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "variables": {
      "headline": { "type": "text", "content": "Q3 in review" },
      "cover_image": {
        "type": "image",
        "asset": { "type": "url", "url": "https://example.com/cover.png" },
        "fit": "cover"
      }
    },
    "title": "Quarterly Update — Q3",
    "caption": false
  }'
```

The response is `data.video_id`. Send every text variable. An omitted text variable is not filled from the template default. Character, voice, image, video, and audio variables may be omitted to keep the template value.

Other confirmed body fields: `scene_ids` (reorder or repeat existing scenes only), `dimension` as `{ "width", "height" }` (even, 128–4096, same aspect ratio as the template), `fps` (`25`, `30`, or `60`), `caption` (boolean; burn-in), `callback_url`, `callback_id`, `folder_id`, `brand_glossary_id`.

Many videos from one template are separate POSTs, or `POST /v3/videos/batches` when the batch item shape matches a video create. Do not loop the retired `/v2/template/{id}/generate` path.
