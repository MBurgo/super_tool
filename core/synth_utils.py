# core/synth_utils.py
import os
import time
import json
from typing import Any, List

import numpy as np
import streamlit as st
from openai import OpenAI

_client_cache = None


def _discover_openai_key() -> str | None:
    # 1) Nested secrets style: [openai] api_key="..."
    try:
        sec = st.secrets
        if "openai" in sec and isinstance(sec["openai"], dict):
            k = sec["openai"].get("api_key")
            if k:
                return k
    except Exception:
        pass

    # 2) Flat secrets
    for k in ("OPENAI_API_KEY", "openai_api_key", "openaiApiKey"):
        try:
            if k in st.secrets:
                return st.secrets.get(k)
        except Exception:
            pass

    # 3) Environment
    return os.environ.get("OPENAI_API_KEY")


def _client() -> OpenAI:
    global _client_cache
    if _client_cache is None:
        key = _discover_openai_key()
        if not key:
            raise RuntimeError(
                "OpenAI API key not found. Set st.secrets['openai']['api_key'] "
                "OR st.secrets['OPENAI_API_KEY'] OR env OPENAI_API_KEY."
            )
        _client_cache = OpenAI(api_key=key)
    return _client_cache


def _pick_model(default: str = "gpt-4.1") -> str:
    try:
        return st.secrets.get("openai_model", default)
    except Exception:
        pass
    return os.environ.get("OPENAI_MODEL", default)


def call_gpt(messages: List[dict], model: str | None = None, tries: int = 4) -> str:
    cli = _client()
    model = model or _pick_model()
    last_err: Exception | None = None
    for i in range(tries):
        try:
            resp = cli.chat.completions.create(model=model, messages=messages)
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (2 ** i))
    raise RuntimeError(f"OpenAI call failed after retries: {last_err}")


def call_gpt_json(messages: List[dict], model: str | None = None, tries: int = 4) -> str:
    cli = _client()
    model = model or _pick_model()
    last_err: Exception | None = None
    for i in range(tries):
        try:
            resp = cli.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (2 ** i))
    raise RuntimeError(f"OpenAI JSON call failed after retries: {last_err}")


def embed_texts(texts: List[str], model: str = "text-embedding-3-small") -> np.ndarray:
    cli = _client()
    resp = cli.embeddings.create(model=model, input=texts)
    return np.vstack([d.embedding for d in resp.data])


def safe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return {}
