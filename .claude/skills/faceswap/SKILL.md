---
name: faceswap
description: |
  Face swap through HeyGen. The v1 workflow used for this (POST /v1/workflows/executions with FaceswapNode) retires on October 31, 2026 and has no confirmed v3 equivalent. Use the HeyGen MCP or tools/video/heygen_video.py for supported video work.
allowed-tools: mcp__heygen__*
metadata:
  openclaw:
    requires:
      env:
        - HEYGEN_API_KEY
    primaryEnv: HEYGEN_API_KEY
---

# Face Swap

HeyGen retires `POST /v1/workflows/executions` and `GET /v1/workflows/executions/{execution_id}` on October 31, 2026. The face-swap call was `workflow_type: "FaceswapNode"` with a source face image and a target video.

No v3 replacement for that workflow is confirmed in this repo or in HeyGen's current API docs. `POST /v3/lipsyncs` replaces audio and redraws the mouth. It is not a face swap. `POST /v3/videos` and `POST /v3/models/videos` do not take a FaceswapNode payload.

Do not call the v1 workflow.

Use the HeyGen MCP, or `tools/video/heygen_video.py` (`POST /v3/models/videos` for `heygen-video-1` clips). Neither surface currently exposes face swap. If a swap is required, say so and stop rather than sending a retired request.
