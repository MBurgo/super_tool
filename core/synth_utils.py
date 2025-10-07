# core/synth_utils.py
# Single source of truth for OpenAI helpers + safe JSON parsing.
# - Compatible with OpenAI Python SDK v1.x (preferred) and v0.28.x (fallback).
# - Reads API key from env or Streamlit secrets ([openai].api_key or OPENAI_API_KEY).
# - Exposes:
#     call_gpt_json(messages, model=...)
#     embed_texts(texts, model=...)
#     safe_json(raw_text, default={})
#     openai_key_diagnostics()

from __future__ import annotations

from typing import List, Dict, Any, Optional
import os
import json
import time
import re

# Streamlit is optional; used only to read secrets if available.
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


# --------------------------- secrets helpers ---------------------------

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


def openai_key_diagnostics() -> Dict[str, Any]:
    env = {
        "OPENAI_API_KEY": len(os.environ.get("OPENAI_API_KEY", "")) or 0,
        "OpenAI_APIKey": len(os.environ.get("OpenAI_APIKey", "")) or 0,
        "openai_api_key": len(os.environ.get("openai_api_key", "")) or 0,
    }
    secrets = {"[openai].api_key": 0, "OPENAI_API_KEY": 0, "openai_api_key": 0}
    tops = []
    if st is not None:
        try:
            tops = list(getattr(st, "secrets", {}).keys())  # type: ignore
        except Exception:
            tops = []
        v = _nested_get(st.secrets, ["openai", "api_key"])  # type: ignore[arg-type]
        secrets["[openai].api_key"] = len(v) if isinstance(v, str) else 0
        for name in ("OPENAI_API_KEY", "openai_api_key"):
            t = _nested_get(st.secrets, [name])  # type: ignore[arg-type]
            secrets[name] = len(t) if isinstance(t, str) else 0
    return {
        "module_path": __file__,
        "env_value_lengths": env,
        "secrets_value_lengths": secrets,
        "secrets_top_level_keys": tops,
    }


# --------------------------- OpenAI clients ---------------------------

def _ensure_env_has_key(key: str) -> None:
    # Make sure the runtime also has the env var set for any downstream lib that reads it.
    if key and os.environ.get("OPENAI_API_KEY", "") != key:
        os.environ["OPENAI_API_KEY"] = key

def _client_v1():
    if not _OPENAI_V1:
        return None
    key = _get_openai_api_key()
    _ensure_env_has_key(key)
    # Prefer explicit key first. Some very early v1 builds didn't accept api_key kwarg; fall back to env.
    try:
        return OpenAI(api_key=key)  # type: ignore
    except TypeError:
        return OpenAI()  # type: ignore


def _ensure_legacy_config():
    if openai_legacy is None:
        return False
    try:
        key = _get_openai_api_key()
        _ensure_env_has_key(key)
        openai_legacy.api_key = key
        return True
    except Exception:
        return False


# --------------------------- Public API ---------------------------

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
    Chat completions returning assistant content as a JSON string.
    We do not parse here; caller decides how to handle bad JSON.
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


def safe_json(raw: Any, default: Any = None) -> Any:
    """
    Best-effort JSON loader that tolerates:
      - leading/trailing junk or code fences
      - stray prose around a JSON object/array
      - trailing commas before } or ]
    Returns `default` ({} by default) if parsing fails.
    """
    if default is None:
        default = {}
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return default

    s = raw.strip()

    # Strip code fences ```json ... ```
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)

    # Direct parse
    try:
        return json.loads(s)
    except Exception:
        pass

    # Try to isolate the outermost {...} or [...]
    def _slice_to_json(text: str) -> Optional[str]:
        a1, b1 = text.find("{"), text.rfind("}")
        a2, b2 = text.find("["), text.rfind("]")
        candidate_obj = text[a1:b1 + 1] if a1 != -1 and b1 > a1 else None
        candidate_arr = text[a2:b2 + 1] if a2 != -1 and b2 > a2 else None
        return candidate_obj or candidate_arr

    cand = _slice_to_json(s)
    if cand:
        try:
            return json.loads(cand)
        except Exception:
            # Remove trailing commas: ,\s*([}\]])
            s2 = re.sub(r",\s*([}\]])", r"\1", cand)
            try:
                return json.loads(s2)
            except Exception:
                pass

    # Last-ditch: remove trailing commas in whole string and try again
    s3 = re.sub(r",\s*([}\]])", r"\1", s)
    try:
        return json.loads(s3)
    except Exception:
        return default


__all__ = ["call_gpt_json", "embed_texts", "safe_json", "openai_key_diagnostics"]
