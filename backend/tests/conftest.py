"""Shared test setup."""

import os

import pytest


@pytest.fixture(autouse=True)
def no_real_ai_calls(monkeypatch):
    """The test container loads backend/.env, which holds the real Anthropic key. Tests must never
    reach the real model (it costs money and makes tests flaky), so the key and model are removed
    from the environment for every test. The one live test opts in with RUN_LIVE_VISION=1."""
    if os.environ.get("RUN_LIVE_VISION") == "1":
        return
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
