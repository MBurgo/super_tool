# app/streamlit/pages/9_Secrets_Diagnostics.py
import _bootstrap
import sys
import json
import importlib
import streamlit as st

st.set_page_config(page_title="Diagnostics: Secrets & Imports", page_icon="🛠️", layout="wide")
st.title("Diagnostics: Secrets & Imports")

# Lazy import so we can show real errors if the adapter fails
def load_adapter(name: str):
    try:
        mod = importlib.import_module(name)
        return mod, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

adapter, err = load_adapter("adapters.trends_serp_adapter")
if err:
    st.error("Failed to import adapters.trends_serp_adapter")
    st.code(err)
    st.stop()

get_serpapi_key = getattr(adapter, "get_serpapi_key", None)
serp_key_diagnostics = getattr(adapter, "serp_key_diagnostics", None)

st.subheader("Import info")
st.write({
    "python_version": sys.version,
    "adapter_module_path": getattr(adapter, "__file__", "n/a"),
    "adapter_version": getattr(adapter, "ADAPTER_VERSION", "n/a"),
})

st.subheader("Key detection diagnostics (lengths only)")
diag = {}
if callable(serp_key_diagnostics):
    try:
        diag = serp_key_diagnostics()
    except Exception as e:
        diag = {"error": f"{type(e).__name__}: {e}"}
else:
    # Fallback: rebuild minimal diagnostics locally
    import os
    def _nested_get(mapping, keys):
        cur = mapping
        for k in keys:
            try:
                cur = cur[k]
            except Exception:
                try:
                    cur = cur.get(k)
                except Exception:
                    return None
            if cur is None:
                return None
        return cur

    env = {
        "SERPAPI_API_KEY": len(os.environ.get("SERPAPI_API_KEY", "")) or 0,
        "SERP_API_KEY": len(os.environ.get("SERP_API_KEY", "")) or 0,
        "serpapi_api_key": len(os.environ.get("serpapi_api_key", "")) or 0,
    }
    secrets = {"[serpapi].api_key": 0, "serpapi_api_key": 0, "SERPAPI_API_KEY": 0, "SERP_API_KEY": 0}
    top_keys = []
    try:
        top_keys = list(st.secrets.keys())  # type: ignore
    except Exception:
        top_keys = []
    try:
        v = _nested_get(st.secrets, ["serpapi", "api_key"])  # type: ignore
        secrets["[serpapi].api_key"] = len(v) if isinstance(v, str) else 0
        for name in ("serpapi_api_key", "SERPAPI_API_KEY", "SERP_API_KEY"):
            t = _nested_get(st.secrets, [name])  # type: ignore
            secrets[name] = len(t) if isinstance(t, str) else 0
    except Exception:
        pass
    diag = {
        "adapter_version": getattr(adapter, "ADAPTER_VERSION", "n/a"),
        "module_path": getattr(adapter, "__file__", "n/a"),
        "env_value_lengths": env,
        "secrets_value_lengths": secrets,
        "secrets_top_level_keys": top_keys,
    }

st.code(json.dumps(diag, indent=2), language="json")

st.subheader("Resolved key presence")
present = False
if callable(get_serpapi_key):
    try:
        present = bool(get_serpapi_key())
    except Exception as e:
        st.warning(f"get_serpapi_key raised: {type(e).__name__}: {e}")
        present = False
st.write("`get_serpapi_key()`:", "✅ found" if present else "❌ not found")
