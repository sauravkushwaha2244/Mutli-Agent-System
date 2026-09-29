from langchain.tools import tool 
import requests
from bs4 import BeautifulSoup
from tavily import TavilyClient
import os 
from dotenv import load_dotenv
from rich import print
from urllib.parse import urlparse

load_dotenv()

openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
tavily_api_key = os.getenv("TAVILY_API_KEY") or os.getenv("TAVILY_API")

if not openrouter_api_key and not tavily_api_key:
    raise ValueError(
        "Search API key missing. Please set OPENROUTER_API_KEY (for Perplexity search via OpenRouter) "
        "or TAVILY_API_KEY in your environment or .env file."
    )

tavily = TavilyClient(api_key=tavily_api_key) if tavily_api_key else None


def _search_with_perplexity_openrouter(query: str, api_key: str, max_results: int = 5) -> str:
    """Uses OpenRouter's Perplexity Sonar model for live web search and citations."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Saurav-Kushwaha/ResearchMind",
        "X-Title": "ResearchMind",
    }
    payload = {
        "model": "perplexity/sonar",
        "messages": [
            {
                "role": "user",
                "content": f"Search the web for recent, reliable information on: {query}. Return details and source citations.",
            }
        ],
        "max_tokens": 1000,
    }
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    choices = data.get("choices", [])
    if not choices:
        return "No search results found."

    msg = choices[0].get("message", {})
    content = msg.get("content", "")
    annotations = msg.get("annotations", [])

    citations = [
        a.get("url_citation")
        for a in annotations
        if isinstance(a, dict) and a.get("type") == "url_citation" and "url_citation" in a
    ]

    out = []
    if citations:
        for c in citations[:max_results]:
            title = c.get("title") or "Web Source"
            url = c.get("url") or ""
            out.append(f"Title: {title}\nURL: {url}\nSnippet: {content[:300]}\n")
    else:
        out.append(f"Title: Perplexity Sonar Search\nURL: https://www.perplexity.ai\nSnippet: {content[:600]}\n")

    return "\n----\n".join(out)


def _search_with_tavily(query: str, max_results: int = 5) -> str:
    results = tavily.search(query=query, max_results=max_results)
    raw_results = results.get("results") if isinstance(results, dict) else None
    if not raw_results:
        return "No search results found for the given query."

    out = []
    for r in raw_results:
        out.append(
            f"Title: {r.get('title', 'No Title')}\nURL: {r.get('url', '')}\nSnippet: {r.get('content', '')[:300]}\n"
        )
    return "\n----\n".join(out)


@tool
def web_search(query : str) -> str:
    """Search the web for recent and reliable information on a topic . Returns Titles , URLs and snippets."""
    try:
        if openrouter_api_key:
            return _search_with_perplexity_openrouter(query, openrouter_api_key)
        elif tavily:
            return _search_with_tavily(query)
        else:
            return "No search provider configured."
    except Exception as e:
        if openrouter_api_key and tavily:
            try:
                return _search_with_tavily(query)
            except Exception:
                pass
        return f"Web search error: {str(e)}"


@tool
def scrape_url(url: str) -> str:
    """Scrape and return clean text content from a given URL for deeper reading."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return f"Invalid URL scheme '{parsed.scheme}'. Only http and https URLs are allowed."

        resp = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
            stream=True
        )
        resp.raise_for_status()
        max_bytes = 500_000
        content = resp.raw.read(max_bytes, decode_content=True)
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)[:3000]
    except Exception as e:
        return f"Could not scrape URL: {str(e)}"
