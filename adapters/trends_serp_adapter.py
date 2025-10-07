# adapters/trends_serp_adapter.py
import asyncio, httpx
from bs4 import BeautifulSoup
from serpapi import GoogleSearch

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"
}

def _serp(key, **params):
    params["api_key"] = key
    return GoogleSearch(params).get_dict()

def fetch_trends_and_news(serp_api_key: str):
    # Trends (AU, last 4h, related queries)
    t = _serp(serp_api_key, engine="google_trends", q="/m/0bl5c2", geo="AU",
              data_type="RELATED_QUERIES", tz="-600", date="now 4-H")
    rising = t.get("related_queries", {}).get("rising", [])[:20]

    # News (AU, last day)
    news = _serp(serp_api_key, engine="google", q="asx 200",
                 google_domain="google.com.au", tbs="qdr:d",
                 gl="au", hl="en", location="Australia", tbm="nws", num="40")
    news_results = news.get("news_results", [])[:40]
    return rising, news_results

async def _desc(session, url: str) -> str:
    try:
        r = await session.get(url, timeout=10, headers=BROWSER_HEADERS, follow_redirects=True)
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        soup = BeautifulSoup(r.content, "lxml")
        tag = soup.find("meta", attrs={"name":"description"})
        return tag["content"].strip() if tag and tag.get("content") else "No Meta Description"
    except Exception:
        return "Error Fetching Description"

async def fetch_meta_descriptions(urls: list[str], concurrency: int = 10) -> list[str]:
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient() as session:
        async def run(u): 
            async with sem: 
                return await _desc(session, u)
        return await asyncio.gather(*(run(u) for u in urls))
