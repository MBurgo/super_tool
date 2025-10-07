# core/tmf_synth_utils.py
import os, json, numpy as np

_client_cache = None

def _get_openai_key():
    # Try Streamlit secrets if present, then env var
    try:
        import streamlit as st
        if "openai" in st.secrets and isinstance(st.secrets["openai"], dict):
            k = st.secrets["openai"].get("api_key")
            if k: return k
        k = st.secrets.get("openai_api_key")
        if k: return k
    except Exception:
        pass
    return os.getenv("OPENAI_API_KEY")

def _client():
    global _client_cache
    if _client_cache is None:
        from openai import OpenAI
        key = _get_openai_key()
        if not key:
            raise RuntimeError(
                "OpenAI API key not found. Add `[openai].api_key` or `openai_api_key` to secrets "
                "or set OPENAI_API_KEY environment variable."
            )
        _client_cache = OpenAI(api_key=key)
    return _client_cache

def call_gpt(messages, model="gpt-4o-mini"):
    cli = _client()
    resp = cli.chat.completions.create(model=model, messages=messages)
    return resp.choices[0].message.content.strip()

def embed_texts(texts, model="text-embedding-3-small"):
    cli = _client()
    embs = cli.embeddings.create(model=model, input=texts).data
    return np.vstack([e.embedding for e in embs])

def load_personas(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Accept either {"personas":[...]} or a raw list
    return data["personas"] if isinstance(data, dict) and "personas" in data else data
