"""AI intro image generation via Cloudflare Workers AI (text-to-image).

Used for the optional AI-generated intro title card. The image prompt itself is
written by the Gemma LLM (see AgentService.write_intro_image_prompt) so the
banner reflects the actual destination and attractions being covered.
"""

from __future__ import annotations

import base64
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 90  # Workers AI image gen can take a while on cold start


def cloudflare_configured() -> bool:
    return bool(settings.cloudflare_account_id and settings.cloudflare_api_token)


def generate_image_bytes(prompt: str) -> bytes:
    """Call Cloudflare Workers AI text-to-image and return PNG bytes.

    Raises ValueError with a user-facing message on any failure.
    """
    if not cloudflare_configured():
        raise ValueError(
            "Cloudflare image generation is not configured. Set CLOUDFLARE_ACCOUNT_ID "
            "and CLOUDFLARE_API_TOKEN in .env."
        )

    model = settings.cloudflare_image_model
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{settings.cloudflare_account_id}/ai/run/{model}"
    )
    headers = {
        "Authorization": f"Bearer {settings.cloudflare_api_token}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(url, headers=headers, json={"prompt": prompt})
    except httpx.RequestError as e:
        raise ValueError(f"Could not reach Cloudflare image API: {e}") from e

    if resp.status_code != 200:
        raise ValueError(
            f"Cloudflare image API returned HTTP {resp.status_code}: {resp.text[:300]}"
        )

    content_type = resp.headers.get("Content-Type", "")
    if "image" in content_type:
        # Some models return raw image bytes directly.
        return resp.content

    # Otherwise the JSON-wrapped form: {"result": {"image": "<base64>"}, "success": true}
    try:
        data = resp.json()
    except ValueError as e:
        raise ValueError("Cloudflare returned an unexpected (non-image, non-JSON) response.") from e

    if not data.get("success", False):
        raise ValueError(f"Cloudflare image generation failed: {data.get('errors')}")

    image_b64 = data.get("result", {}).get("image")
    if not image_b64:
        raise ValueError("Cloudflare response did not contain an image.")

    try:
        return base64.b64decode(image_b64)
    except Exception as e:  # noqa: BLE001
        raise ValueError("Could not decode the image returned by Cloudflare.") from e
