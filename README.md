# Marketing Super-Tool v4

One Streamlit app to do the work of four:
**Trends → Briefs → Copy → Persona feedback → Optimise → Finalists**
with an optional **Synthetic Focus** panel for clustered reactions.

## Quickstart
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=your_key   # or set in Streamlit Secrets
streamlit run app/streamlit/Home.py
```

## Streamlit Secrets (recommended)
In your app's **Settings → Secrets**, paste TOML like:
```toml
OPENAI_API_KEY = "sk-xxxxxxxxxxxxxxxx"
GOOGLE_TRENDS_SHEET_ID = "1BzTJgX7OgaA0QNfzKs5AgAx2rvZZjDdorgAz0SD9NZg"

[service_account]
type = "service_account"
project_id = "your-project"
private_key_id = "xxxxxxxxxxxxxxxxxxxxxxxx"
private_key = """-----BEGIN PRIVATE KEY-----
MIIE....
-----END PRIVATE KEY-----"""
client_email = "svc@your-project.iam.gserviceaccount.com"
client_id = "1234567890"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/your-svc%40your-project.iam.gserviceaccount.com"
```

> Make sure the Sheet is shared with the `client_email` above.

## Pages
- **Personas**: upload your Personas Portal JSON (overlays supported). Saves to `data/personas.json`.
- **Trends (Google Sheets)**: auto-uses `st.secrets["service_account"]` (falls back to upload/paste). Saves TrendBriefs JSON.
- **Copy Studio**: generate copy using trait controls and built-in guardrails.
- **Campaign Lab**: pick a TrendBrief, choose evaluator (Heuristic | Synthetic | Hybrid), run the optimisation loop to a finalist.
- **Synthetic Focus**: run the 50-persona reaction test on any copy and export results.
- **Finalists**: browse and export winners.

### Notes
- Synthetic evaluation is slower/costlier; prefer **Hybrid** in Campaign Lab.
- Credentials are never committed. See `.gitignore`.


## Deployment gotchas
- Put the **contents** of this folder at the **repo root** so Streamlit Cloud sees `requirements.txt`.
- We added `runtime.txt` (`3.11`) to avoid Python 3.13 shenanigans.
- To avoid uploading personas each run, paste them into **Secrets** as `PERSONAS_JSON` (full JSON), or commit to `data/personas.json`.
