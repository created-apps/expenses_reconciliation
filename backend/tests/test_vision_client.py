"""The real vision client, with a fake stand-in for the Anthropic SDK (no network, no key, no cost)."""

import base64
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.engine.invoices.vision import SCHEMA, VisionError
from app.services.vision_client import FRIENDLY, MAX_TOKENS, AnthropicVision, build_vision

IMAGE = b"\x89PNG not really an image"


class FakeSDK:
    """Looks like `anthropic.Anthropic()` for the one call we make: `client.messages.create(...)`."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response


def response(*blocks, stop_reason="end_turn", model="claude-sonnet-5-5", usage=(2500, 120)):
    return SimpleNamespace(
        content=list(blocks), stop_reason=stop_reason, model=model,
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]),
    )


def text(value):
    return SimpleNamespace(type="text", text=value)


def named_error(name):
    return type(name, (Exception,), {})("secret details with sk-ant-should-never-be-shown")


def test_the_request_has_the_model_the_image_the_instructions_and_the_response_format():
    sdk = FakeSDK(response(text('{"ok": true}')))
    AnthropicVision(sdk, "claude-sonnet-5-5").read(IMAGE, "image/png", "INSTRUCTIONS", SCHEMA)
    (request,) = sdk.requests
    assert request["model"] == "claude-sonnet-5-5" and request["max_tokens"] == MAX_TOKENS
    assert request["system"] == "INSTRUCTIONS"
    image_block, prompt_block = request["messages"][0]["content"]
    assert image_block == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(IMAGE).decode()},
    }
    assert prompt_block["type"] == "text"
    assert request["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}}


def test_no_sampling_or_thinking_settings_are_sent():
    sdk = FakeSDK(response(text("{}")))
    AnthropicVision(sdk, "m").read(IMAGE, "image/jpeg", "i", SCHEMA)
    assert not {"temperature", "top_p", "top_k", "thinking", "tool_choice"} & set(sdk.requests[0])


def test_the_text_block_is_returned_with_its_usage_even_after_a_thinking_block():
    thinking = SimpleNamespace(type="thinking", thinking="")
    out = AnthropicVision(FakeSDK(response(thinking, text('{"a": 1}'))), "m").read(IMAGE, "image/png", "i", SCHEMA)
    assert (out.text, out.model, out.input_tokens, out.output_tokens) == ('{"a": 1}', "claude-sonnet-5-5", 2500, 120)


def test_a_refusal_is_reported_as_the_ai_declining():
    with pytest.raises(VisionError, match="declined"):
        AnthropicVision(FakeSDK(response(stop_reason="refusal")), "m").read(IMAGE, "image/png", "i", SCHEMA)


def test_a_file_type_the_model_cannot_read_is_refused_before_any_call():
    sdk = FakeSDK(response(text("{}")))
    with pytest.raises(VisionError, match="can't read"):
        AnthropicVision(sdk, "m").read(IMAGE, "application/pdf", "i", SCHEMA)
    assert sdk.requests == []


@pytest.mark.parametrize("name", sorted(FRIENDLY))
def test_each_known_sdk_error_gives_a_message_a_person_can_act_on(name):
    with pytest.raises(VisionError) as caught:
        AnthropicVision(FakeSDK(error=named_error(name)), "m").read(IMAGE, "image/png", "i", SCHEMA)
    assert str(caught.value) == FRIENDLY[name]
    assert "sk-ant" not in str(caught.value)  # the SDK's own text is never passed on


def test_nothing_from_the_sdk_error_text_or_the_key_is_logged(caplog):
    import logging

    secret = "sk-ant-api03-THE-REAL-KEY-VALUE"
    error = type("AuthenticationError", (Exception,), {"status_code": 401})(f"invalid x-api-key {secret}; request id abc")
    with caplog.at_level(logging.DEBUG), pytest.raises(VisionError):
        AnthropicVision(FakeSDK(error=error), "m").read(IMAGE, "image/png", "i", SCHEMA)
    assert "AuthenticationError" in caplog.text and "401" in caplog.text  # what kind of failure is still visible
    assert secret not in caplog.text and "invalid x-api-key" not in caplog.text and "request id" not in caplog.text


def test_the_key_never_appears_in_the_clients_text_when_a_request_fails_in_the_invoice_job(caplog):
    # End to end through the engine: a client that raises with a secret in its message.
    import logging

    from app.engine.invoices.vision import read_image_invoice

    class Leaky:
        def read(self, *args):
            raise RuntimeError("boom sk-ant-api03-SECRET")

    with caplog.at_level(logging.DEBUG):
        item = read_image_invoice(IMAGE, "image/png", Leaky(), [])
    assert item.extraction_status == "needs_check" and "sk-ant" not in caplog.text
    assert "sk-ant" not in str(item.problems) and "sk-ant" not in str(item.extra)


def test_an_unknown_error_is_named_but_not_quoted():
    with pytest.raises(VisionError) as caught:
        AnthropicVision(FakeSDK(error=named_error("WeirdError")), "m").read(IMAGE, "image/png", "i", SCHEMA)
    assert str(caught.value) == "AI reading failed (WeirdError)"


def test_the_wrong_model_name_message_says_what_to_fix():
    assert "ANTHROPIC_MODEL" in FRIENDLY["NotFoundError"] and "claude-sonnet-5-5" in FRIENDLY["NotFoundError"]
    assert "ANTHROPIC_API_KEY" in FRIENDLY["AuthenticationError"]


# ---- Configuration -------------------------------------------------------------------------------------------
def settings(key="", model=""):
    return Settings(_env_file=None, anthropic_api_key=key, anthropic_model=model)


@pytest.mark.parametrize("key, model", [("", ""), ("sk-ant-x", ""), ("", "claude-sonnet-5-5"), ("  ", "  ")])
def test_without_both_the_key_and_the_model_there_is_no_ai(key, model):
    assert build_vision(settings(key, model), sdk_client=FakeSDK()) is None


def test_with_both_the_client_uses_the_model_name_from_the_settings():
    vision = build_vision(settings("sk-ant-x", " claude-haiku-5-5 "), sdk_client=FakeSDK())
    assert isinstance(vision, AnthropicVision) and vision.model == "claude-haiku-5-5"  # whitespace trimmed, nothing hard-coded


def test_the_real_sdk_client_is_built_from_the_settings_key():
    pytest.importorskip("anthropic")
    vision = build_vision(settings("sk-ant-test-key", "claude-sonnet-5-5"))
    assert vision is not None and vision.client.api_key == "sk-ant-test-key"
    assert not hasattr(vision.client, "last_request")  # constructing the client makes no request
