# core/tmf_synth_utils.py
from __future__ import annotations

import json
import os
from typing import List

import numpy as np
from openai import OpenAI

_client_cache = None

def _client() -> OpenAI:
    global _client_cache
    if _client_cache is None:
        api_key = None
        # Try Streamlit secrets if available
        try:
            import streamlit as st  # type: ignore
            api_key = (
                st.secrets.get("OPENAI_API_KEY")
                or st.secrets.get("openai_api_key")
                or (st.secrets.get("openai", {}) or {}).get("api_key")
            )
        except Exception:
            api_key = None
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OpenAI API key not found. Set OPENAI_API_KEY in secrets or environment."
            )
        _client_cache = OpenAI(api_key=api_key)
    return _client_cache


def call_gpt(messages, model: str = "gpt-4o-mini", tries: int = 4) -> str:
    cli = _client()
    for _ in range(tries):
        try:
            resp = cli.chat.completions.create(model=model, messages=messages)
            return resp.choices[0].message.content.strip()
        except Exception:
            continue
    return ""


def call_gpt_json(messages, model: str = "gpt-4o-mini", tries: int = 4) -> str:
    cli = _client()
    for _ in range(tries):
        try:
            resp = cli.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content
        except Exception:
            continue
    return "{}"


def safe_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


def embed_texts(texts: List[str], model: str = "text-embedding-3-small") -> np.ndarray:
    cli = _client()
    embs = cli.embeddings.create(model=model, input=texts).data
    return np.vstack([e.embedding for e in embs])


def load_personas(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["personas"]
