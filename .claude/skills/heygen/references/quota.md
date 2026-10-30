---
name: quota
description: Read HeyGen account balance with GET /v3/users/me
---

# HeyGen Account and Credits

`GET /v2/user/remaining_quota` and `GET /v1/user/me` retire on October 31, 2026. The v3 call is:

```bash
curl "https://api.heygen.com/v3/users/me" \
  -H "X-Api-Key: $HEYGEN_API_KEY"
```

`data.billing_type` is `wallet`, `subscription`, or `usage_based`. Exactly one of these objects is populated:

| `billing_type` | Where remaining usage lives |
|----------------|-----------------------------|
| `wallet` | `data.wallet.remaining_balance` (USD or credits) plus `data.wallet.currency` |
| `subscription` | `data.subscription.plan` and `data.subscription.credits` (`premium_credits.remaining`, `add_on_credits.remaining`, each with `resets_at`) |
| `usage_based` | `data.usage_based.remaining_credits`, `spending_current_usd`, `spending_cap_usd` |

```python
import os
import requests

def remaining(profile: dict) -> str:
    data = profile["data"]
    kind = data.get("billing_type")
    if kind == "wallet" and data.get("wallet"):
        wallet = data["wallet"]
        return f"{wallet.get('remaining_balance')} {wallet.get('currency')}"
    if kind == "subscription" and data.get("subscription"):
        credits = data["subscription"]["credits"]
        premium = (credits.get("premium_credits") or {}).get("remaining")
        return f"{premium} premium credits"
    if kind == "usage_based" and data.get("usage_based"):
        return f"{data['usage_based'].get('remaining_credits')} credits"
    return "unknown"

response = requests.get(
    "https://api.heygen.com/v3/users/me",
    headers={"X-Api-Key": os.environ["HEYGEN_API_KEY"]},
    timeout=30,
)
response.raise_for_status()
print(remaining(response.json()))
```

There is no confirmed v3 "test mode" that replaces the old quota test flag. Draft by using a short script or a 5-second `heygen-video-1` clip, not a retired query parameter.

A `401` is an auth failure. A `429` with `error.code` of `rate_limit_exceeded` is a burst limit (`Retry-After`). `quota_exceeded` or HTTP 402 is an allowance limit. Read `error.message` rather than assuming the balance shape.
