"""The real vision client: Claude through the official Anthropic SDK.

Only this module talks to the model. The engine (`engine/invoices/vision.py`) gets a `VisionClient`
and never imports the SDK. The key and the model name are read from the environment
(`ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`); the model name is never written in code.
"""

import base64
import logging
from typing import Any

from fastapi import Depends

from app.config import Settings, get_settings
from app.engine.invoices.vision import VisionError, VisionReply

log = logging.getLogger("app.vision")

# One short extraction: thinking effort is kept low, and there is room left for it inside max_tokens.
MAX_TOKENS = 4000
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

# What a person should be told, by the kind of SDK error (matched on the class name so this module
# does not have to import the SDK's error types).
FRIENDLY = {
    "AuthenticationError": "The AI service did not accept the API key. Check ANTHROPIC_API_KEY.",
    "PermissionDeniedError": "The AI key is not allowed to use this model. Check ANTHROPIC_MODEL and the key.",
    "NotFoundError": "The AI model was not found. Check ANTHROPIC_MODEL (it must be a model ID such as claude-sonnet-5-5).",
    "RateLimitError": "The AI service is busy (rate limit). Read the invoices again in a minute.",
    "APITimeoutError": "The AI service took too long to answer. Try again.",
    "APIConnectionError": "Could not reach the AI service. Check the internet connection and try again.",
    "InternalServerError": "The AI service had a problem. Try again in a moment.",
    "OverloadedError": "The AI service is overloaded. Try again in a moment.",
}


class AnthropicVision:
    """Sends one image and the extraction instructions; returns the model's JSON text and token usage."""

    def __init__(self, client: Any, model: str, max_tokens: int = MAX_TOKENS):
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    def read(self, image: bytes, media_type: str, instructions: str, schema: dict[str, Any]) -> VisionReply:
        if media_type not in IMAGE_TYPES:
            raise VisionError(f"The AI can't read {media_type} files (use PNG, JPEG, GIF or WebP).")
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=instructions,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": base64.standard_b64encode(image).decode("ascii"),
                                },
                            },
                            {"type": "text", "text": "Read this document."},
                        ],
                    }
                ],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            )
        except Exception as exc:  # noqa: BLE001 - turned into a message a person can act on
            name = type(exc).__name__
            # Only the kind of error and its HTTP status are logged: never the SDK's message text, which
            # can echo request details. The person sees the friendly message below.
            log.warning("AI request failed: %s (status %s)", name, getattr(exc, "status_code", None))
            raise VisionError(FRIENDLY.get(name, f"AI reading failed ({name})")) from None

        if getattr(response, "stop_reason", None) == "refusal":
            raise VisionError("The AI declined to read this image.")
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
        usage = getattr(response, "usage", None)
        return VisionReply(
            text=text,
            model=getattr(response, "model", None) or self.model,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )


def build_vision(settings: Settings, sdk_client: Any | None = None) -> AnthropicVision | None:
    """The configured vision client, or None when the key or the model name is not set (images then
    stay `pending` and a person can type their values in). `sdk_client` is for tests."""
    key = settings.anthropic_api_key.get_secret_value().strip()
    model = settings.anthropic_model.strip()
    if not key or not model:
        return None
    if sdk_client is None:
        import anthropic  # imported here so the rest of the app (and its tests) never need the SDK

        sdk_client = anthropic.Anthropic(api_key=key, timeout=90.0, max_retries=2)
    return AnthropicVision(sdk_client, model)


def get_vision(settings: Settings = Depends(get_settings)) -> AnthropicVision | None:
    return build_vision(settings)
