---
name: webhooks
description: Register HeyGen v3 webhook endpoints
---

# Webhooks

`POST /v1/webhook/endpoint.add` and the other `/v1/webhook/endpoint.*` calls retire on October 31, 2026. Management lives under `/v3/webhooks/endpoints`.

| Task | Endpoint |
|------|----------|
| Create | `POST /v3/webhooks/endpoints` |
| List | `GET /v3/webhooks/endpoints` |
| Update | `PATCH /v3/webhooks/endpoints/{endpoint_id}` |
| Delete | `DELETE /v3/webhooks/endpoints/{endpoint_id}` |
| Rotate secret | `POST /v3/webhooks/endpoints/{endpoint_id}/rotate-secret` |
| Event catalog | `GET /v3/webhooks/event-types` |

```bash
curl -X POST "https://api.heygen.com/v3/webhooks/endpoints" \
  -H "X-Api-Key: $HEYGEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/webhooks/heygen",
    "events": ["avatar_video.success", "avatar_video.fail"]
  }'
```

The create response includes `endpoint_id` and `secret`. The secret is shown on create and rotate only. List responses set `secret` to null. Omit `events` to receive every event type. `entity_id` scopes the endpoint to one resource.

`PATCH` replaces the `events` array. Send the full list you want to keep.

HeyGen signs the raw body with HMAC-SHA256 using that secret and sends the hex digest in the `signature` header. Compare it in constant time against the raw bytes, not a re-serialized JSON object. Respond `2xx` within 10 seconds. Failures retry with backoff for up to 24 hours. The same event can arrive twice. De-duplicate on `event_type` plus `event_data.video_id`, or on the `callback_id` you set at create time.

A single job can skip endpoint registration. Pass `callback_url` and optional `callback_id` on `POST /v3/videos`, `POST /v3/video-agents`, or `POST /v3/video-translations`. A callback is attempted once. Keep polling `GET /v3/videos/{video_id}` as the fallback.

```python
import hashlib
import hmac
import os
from flask import Flask, abort, request

app = Flask(__name__)
SECRET = os.environ["HEYGEN_WEBHOOK_SECRET"].encode()

@app.post("/webhooks/heygen")
def heygen_webhook():
    signature = request.headers.get("signature", "")
    raw = request.get_data()
    expected = hmac.new(SECRET, raw, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        abort(401)
    event = request.get_json()
    # event["event_type"] — catalog is GET /v3/webhooks/event-types
    return "", 200
```
