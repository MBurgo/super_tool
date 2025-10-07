# core/synth_utils.py
# Robust OpenAI helpers used across the app.
# - Works with OpenAI Python SDK v1.x (preferred) and v0.28.x (fallback).
# - Reads API key from env or Streamlit secrets ([openai].api_key or OPENAI_API_KEY).
# - Exposes: call_gpt_json(messages, model=...), embed_texts(texts, model=...)

from __future__ import annotations

from typing import List, Dict, Any, Optional
import os
import json
import time

# Streamlit is optional; used only for secrets if available.
try:
    import streamlit as st  # type: ignore
except Exception:
    st = None  # type: ignore

# Try new SDK (v1.x)
_OPENAI_V1 = False
try:
    from openai import OpenAI  # type: ignore
    _OPENAI_V1 = True
except Exception:
    OpenAI = None  # type: ignore

# Try old SDK (v0.28.x)
try:
    import openai as openai_legacy  # type: ignore
except Exception:
    openai_legacy = None  # type: ignore


def _nested_get(mapping: Any, keys: List[str]) -> Optional[Any]:
    cur = mapping
    for k in keys:
        nxt = None
        try:
            nxt = cur[k]  # type: ignore[index]
        except Exception:
            try:
                nxt = cur.get(k)  # type: ignore[attr-defined]
            except Exception:
                return None
        cur = nxt
        if cur is None:
            return None
    return cur


def _get_openai_api_key() -> str:
    # 1) ENV
    for name in ("OPENAI_API_KEY", "OpenAI_APIKey", "openai_api_key"):
        val = os.environ.get(name)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # 2) Streamlit secrets ([openai].api_key, or top-level OPENAI_API_KEY)
    if st is not None:
        v = _nested_get(st.secrets, ["openai", "api_key"])  # type: ignore[arg-type]
        if isinstance(v, str) and v.strip():
            return v.strip()
        for name in ("OPENAI_API_KEY", "openai_api_key"):
            v = _nested_get(st.secrets, [name])  # type: ignore[arg-type]
            if isinstance(v, str) and v.strip():
                return v.strip()

    raise RuntimeError(
        "OpenAI API key not found. Set st.secrets['openai']['api_key'] OR st.secrets['OPENAI_API_KEY'] OR env OPENAI_API_KEY."
    )


def _client_v1():
    if not _OPENAI_V1:
        return None
    key = _get_openai_api_key()
    try:
        return OpenAI(api_key=key)  # type: ignore
    except Exception:
        # Some deployments inject key via env only
        return OpenAI()  # type: ignore


def _ensure_legacy_config():
    if openai_legacy is None:
        return False
    try:
        openai_legacy.api_key = _get_openai_api_key()
        return True
    except Exception:
        return False


def call_gpt_json(
    messages: List[Dict[str, str]],
    *,
    model: str = "gpt-4o-mini",
    temperature: float = 0.2,
    max_tokens: int = 1200,
    retries: int = 2,
    response_format_json: bool = True,
) -> str:
    """
    Call Chat Completions and return the assistant content as a JSON string.
    We do not parse here; the caller will parse and handle errors.
    """
    # V1 path
    if _OPENAI_V1:
        cli = _client_v1()
        if cli is None:
            raise RuntimeError("OpenAI v1 client failed to initialize.")
        for attempt in range(retries + 1):
            try:
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if response_format_json:
                    kwargs["response_format"] = {"type": "json_object"}
                resp = cli.chat.completions.create(**kwargs)  # type: ignore
                content = resp.choices[0].message.content or "{}"
                return content.strip()
            except Exception:
                if attempt >= retries:
                    raise
                time.sleep(0.8 * (attempt + 1))

    # Legacy path
    if _ensure_legacy_config():
        for attempt in range(retries + 1):
            try:
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if response_format_json:
                    kwargs["response_format"] = {"type": "json_object"}
                # Older SDKs may not support response_format; fall back silently
                try:
                    resp = openai_legacy.ChatCompletion.create(**kwargs)  # type: ignore
                except Exception:
                    kwargs.pop("response_format", None)
                    resp = openai_legacy.ChatCompletion.create(**kwargs)  # type: ignore
                content = resp["choices"][0]["message"]["content"] or "{}"
                return str(content).strip()
            except Exception:
                if attempt >= retries:
                    raise
                time.sleep(0.8 * (attempt + 1))

    raise RuntimeError("OpenAI SDK not installed or misconfigured.")


def embed_texts(
    texts: List[str],
    *,
    model: str = "text-embedding-3-small",
    retries: int = 2,
) -> List[List[float]]:
    """
    Return a list of embeddings (list of floats) matching the input order.
    """
    # V1 path
    if _OPENAI_V1:
        cli = _client_v1()
        if cli is None:
            raise RuntimeError("OpenAI v1 client failed to initialize.")
        for attempt in range(retries + 1):
            try:
                resp = cli.embeddings.create(model=model, input=texts)  # type: ignore
                return [row.embedding for row in resp.data]  # type: ignore
            except Exception:
                if attempt >= retries:
                    raise
                time.sleep(0.8 * (attempt + 1))

    # Legacy path
    if _ensure_legacy_config():
        for attempt in range(retries + 1):
            try:
                resp = openai_legacy.Embedding.create(model=model, input=texts)  # type: ignore
                return [row["embedding"] for row in resp["data"]]  # type: ignore
            except Exception:
                if attempt >= retries:
                    raise
                time.sleep(0.8 * (attempt + 1))

    raise RuntimeError("OpenAI SDK not installed or misconfigured for embeddings.")
