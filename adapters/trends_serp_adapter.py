# adapters/trends_serp_adapter.py
import requests

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def fetch_trends_and_news(api_key: str):
    """
    Returns (rising, news)
    rising: list of {query, value}
    news:   list of {title, link, snippet}
    """
    base = "https://serpapi.com/search.json"

    # Google Trends (AU, last 4 hours), using SerpAPI "google_trends"
    r_params = {
        "engine": "google_trends",
        "q": "/m/0bl5c2",            # ASX 200 topic id used in your earlier scripts
        "geo": "AU",
        "data_type": "RELATED_QUERIES",
        "tz": "-600",
        "date": "now 4-H",
        "api_key": api_key,
        "no_cache": "true",
    }
    r = requests.get(base, params=r_params, timeout=30)
    r.raise_for_status()
    rd = r.json()
    rising = rd.get("related_queries", {}).get("rising", [])

    # Google News for "asx 200"
    n_params = {
        "engine": "google",
        "q": "asx 200",
        "google_domain": "google.com.au",
        "tbm": "nws",
        "gl": "au",
        "hl": "en",
        "location": "Australia",
        "num": "40",
        "api_key": api_key,
        "no_cache": "true",
    }
    n = requests.get(base, params=n_params, timeout=30)
    n.raise_for_status()
    nd = n.json()
    news = [
        {
            "title": a.get("title") or "No Title",
            "link": a.get("link")  or "",
            "snippet": a.get("snippet") or "",
        }
        for a in nd.get("news_results", []) or []
    ]

    return rising, news
