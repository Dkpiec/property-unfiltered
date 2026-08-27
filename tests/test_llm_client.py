import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import src.llm_client as llm  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env():
    saved = {}
    for k in ("LLM_PROVIDER", "LLM_MODEL"):
        saved[k] = __import__("os").environ.pop(k, None)
    yield
    import os
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def test_generate_returns_parsed_and_raw(monkeypatch):
    monkeypatch.setattr(llm, "_call", lambda *a, **k: '{"titles": ["A", "B"]}')
    data, raw = llm.generate("metadata", "write titles")
    assert data == {"titles": ["A", "B"]}
    assert '"A"' in raw


def test_generate_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return '{"ok": true}'

    monkeypatch.setattr(llm, "_call", flaky)
    data, _ = llm.generate("metadata", "x")
    assert data == {"ok": True}
    assert calls["n"] == 2


def test_generate_failover_to_fallback(monkeypatch):
    # Force primary provider to fail every attempt; fallback should succeed.
    import os
    os.environ["LLM_PROVIDER"] = "gemini"

    def call(provider, pcfg, prompt, system, defaults):
        if provider == "gemini":
            raise RuntimeError("no key / quota")
        return '{"from": "fallback"}'

    monkeypatch.setattr(llm, "_call", call)
    data, _ = llm.generate("metadata", "x")
    assert data == {"from": "fallback"}


def test_generate_raises_when_all_fail(monkeypatch):
    import os
    os.environ["LLM_PROVIDER"] = "gemini"

    def call(provider, pcfg, prompt, system, defaults):
        raise RuntimeError("dead")

    monkeypatch.setattr(llm, "_call", call)
    # llm.yaml has retries:3, failover:true -> many attempts, then LLMError
    with pytest.raises(llm.LLMError):
        llm.generate("metadata", "x")
