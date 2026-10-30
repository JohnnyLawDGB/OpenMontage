---
name: authentication
description: HeyGen API key authentication for v3
---

# HeyGen Authentication

Every v3 request uses the API key. v1 and v2 hosts retire on October 31, 2026. Do not verify the key with `GET /v2/avatars`.

## Getting a key

Create a key at https://app.heygen.com/settings?nav=API (or the platform API keys page). Store it as `HEYGEN_API_KEY`. Never paste the key into chat.

## Header

```bash
curl "https://api.heygen.com/v3/users/me" \
  -H "X-Api-Key: $HEYGEN_API_KEY"
```

HeyGen's docs also accept the header name `x-api-key`. This repo sends `X-Api-Key`. OAuth bearer tokens work on the same routes; production calls in this repo use the API key.

A `401` means the key is missing, invalid, or expired.

## Python

```python
import os
import requests

response = requests.get(
    "https://api.heygen.com/v3/users/me",
    headers={"X-Api-Key": os.environ["HEYGEN_API_KEY"]},
    timeout=30,
)
response.raise_for_status()
print(response.json()["data"]["username"])
```

`GET /v3/users/me` is the confirmed way to check that the key works. It returns the profile and whichever billing object matches `billing_type` (`wallet`, `subscription`, or `usage_based`). See [quota.md](quota.md).
