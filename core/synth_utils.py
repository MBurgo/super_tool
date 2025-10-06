import os, time, random, json
from typing import List
import numpy as np
from openai import OpenAI

_client_cache = None
def _client():
    global _client_cache
    if _client_cache is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            try:
                import streamlit as st
                api_key = st.secrets.get("OPENAI_API_KEY")
            except Exception:
                api_key = None
        _client_cache = OpenAI(api_key=api_key)
    return _client_cache

def call_gpt(messages, model="gpt-4o-mini", tries=4):
    cli = _client()
    for i in range(tries):
        try:
            resp = cli.chat.completions.create(model=model, messages=messages)
            return resp.choices[0].message.content.strip()
        except Exception:
            time.sleep(2 ** i + random.random())
    return ""

def call_gpt_json(messages, model="gpt-4o-mini", tries=4):
    cli = _client()
    for i in range(tries):
        try:
            resp = cli.chat.completions.create(model=model, messages=messages, response_format={"type":"json_object"})
            return resp.choices[0].message.content.strip()
        except Exception:
            time.sleep(2 ** i + random.random())
    return "{}"

def embed_texts(texts: List[str], model="text-embedding-3-small"):
    cli = _client()
    embs = cli.embeddings.create(model=model, input=texts).data
    return np.vstack([e.embedding for e in embs])

def safe_json(text: str):
    import re, json as _json
    try:
        return _json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        return _json.loads(m.group(0)) if m else {}
