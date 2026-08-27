"""LLM client abstraction with per-task provider selection and failover.

Providers:
  gemini             -> Google Gemini (free tier). Env key: GOOGLE_API_KEY
  openai_compatible  -> any OpenAI-compatible endpoint (Groq, OpenRouter...).
                        Env key: GROQ_API_KEY (configurable via api_key_env).

Per-task provider/model come from config/llm.yaml. Runtime overrides:
  LLM_PROVIDER  -> force provider for every task
  LLM_MODEL     -> force model for every task

Every response is coerced to JSON via utils.json_parse. Raises LLMError if all
providers fail. Secrets are only read from env, never logged.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from src import utils

logger = logging.getLogger("llm")


class LLMError(RuntimeError):
    """Raised when every provider attempt fails or returns no parseable JSON."""


def _load_config() -> dict:
    cfg = utils.load_config("config/llm.yaml")
    if not isinstance(cfg, dict):
        raise LLMError("config/llm.yaml is not a mapping")
    return cfg


def _task_config(task: str, llm_cfg: dict) -> dict:
    task_cfg = llm_cfg.get("tasks", {}).get(task, {})
    provider = os.environ.get("LLM_PROVIDER", task_cfg.get("provider"))
    model = os.environ.get("LLM_MODEL", task_cfg.get("model"))
    return {
        "provider": provider,
        "model": model,
        "temperature": task_cfg.get("temperature", 0.5),
        "max_tokens": task_cfg.get("max_tokens", 4096),
    }


# ── Provider callers ───────────────────────────────────────────────────
def _call_gemini(model: str, prompt: str, system: str | None,
                 temperature: float, max_tokens: int) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=utils.getenv_required("GOOGLE_API_KEY"))
    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
        response_mime_type="application/json",
        system_instruction=system,
    )
    resp = client.models.generate_content(model=model, contents=prompt, config=config)
    if not resp.text:
        raise LLMError("Gemini returned empty response")
    return resp.text


def _call_openai_compatible(base_url: str | None, model: str, prompt: str,
                            system: str | None, temperature: float,
                            max_tokens: int, api_key: str | None) -> str:
    if not api_key:
        raise LLMError("No API key for openai_compatible provider")
    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=api_key)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    def _create(with_json: bool):
        kwargs = dict(model=model, messages=messages,
                      temperature=temperature, max_tokens=max_tokens)
        if with_json:
            kwargs["response_format"] = {"type": "json_object"}
        return client.chat.completions.create(**kwargs)

    try:
        resp = _create(with_json=True)
    except Exception:
        # Some providers/models reject response_format; retry without it.
        resp = _create(with_json=False)
    content = resp.choices[0].message.content
    if not content:
        raise LLMError("openai_compatible returned empty response")
    return content


def _call(provider: str, pcfg: dict, prompt: str, system: str | None,
          task_defaults: dict) -> str:
    model = pcfg.get("model")
    temperature = pcfg.get("temperature", task_defaults.get("temperature", 0.5))
    max_tokens = pcfg.get("max_tokens", task_defaults.get("max_tokens", 4096))

    if provider == "gemini":
        return _call_gemini(model, prompt, system, temperature, max_tokens)
    if provider == "openai_compatible":
        key_env = pcfg.get("api_key_env", "OPENAI_API_KEY")
        api_key = utils.getenv(key_env) or utils.getenv("OPENAI_API_KEY")
        return _call_openai_compatible(pcfg.get("base_url"), model, prompt,
                                       system, temperature, max_tokens, api_key)
    raise LLMError(f"Unknown provider: {provider}")


# ── Public API ─────────────────────────────────────────────────────────
def generate(task: str, prompt: str, system: str | None = None) -> tuple[Any, str]:
    """Run one LLM task with retries + provider failover.

    Returns (parsed_json, raw_text). Raises LLMError on total failure.
    """
    llm_cfg = _load_config()
    cfg = _task_config(task, llm_cfg)
    req_cfg = llm_cfg.get("request", {})
    retries = int(req_cfg.get("retries", 3))
    backoff = float(req_cfg.get("backoff_base_seconds", 2))

    providers = [cfg["provider"]]
    if req_cfg.get("failover", True):
        fallback = llm_cfg.get("fallback", {})
        fb_provider = fallback.get("provider")
        if fb_provider and fb_provider not in providers:
            providers.append(fb_provider)

    last_err: Exception | None = None
    for provider in providers:
        pcfg = cfg if provider == cfg["provider"] else llm_cfg.get("fallback", {})
        for attempt in range(1, retries + 1):
            try:
                raw = _call(provider, pcfg, prompt, system, cfg)
                data = utils.json_parse(raw)
                if data is None:
                    raise LLMError("Provider returned no parseable JSON")
                return data, raw
            except Exception as exc:  # noqa: BLE001 - we want to fail over
                last_err = exc
                logger.warning("LLM provider=%s attempt=%d failed: %s",
                               provider, attempt, exc)
                time.sleep(backoff * (2 ** (attempt - 1)))

    raise LLMError(f"All LLM providers failed: {last_err}")
