"""Evidence collection tools: parallel search, Trafilatura scraping, credibility scoring, quote verification, and citation formatting."""

import os
import re
import requests
import trafilatura
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from typing import List, Dict, Any, Optional, Tuple

from models import PageRecord
import cache

_NETWORK_TIMEOUT = 12.0
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Authoritative & low-credibility domain registries
_HIGH_CRED_DOMAINS = {
    "nature.com", "science.org", "reuters.com", "apnews.com", "bbc.com",
    "arxiv.org", "ieee.org", "nih.gov", "nasa.gov", "who.int", "bloomberg.com",
    "wsj.com", "economist.com", "nytimes.com", "ft.com", "sciencedirect.com"
}
_LOW_CRED_DOMAINS = {
    "reddit.com", "twitter.com", "x.com", "quora.com", "medium.com",
    "blogspot.com", "wordpress.com", "tiktok.com", "facebook.com"
}


def generate_query_variants(question: str) -> List[str]:
    """Generate 2-3 focused search query variants for the topic."""
    clean = question.strip()
    return [
        clean,
        f"{clean} factual evidence research",
        f"{clean} controversy debate analysis",
    ]


def calculate_credibility(url: str, publish_date: Optional[str] = None, is_snippet_fallback: bool = False) -> float:
    """Assign an objective, rule-based credibility score from 0.10 to 1.00."""
    score = 0.50

    try:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]

        # Domain type rules
        if domain.endswith(".gov") or domain.endswith(".mil"):
            score += 0.35
        elif domain.endswith(".edu") or domain.endswith(".ac.uk"):
            score += 0.30
        elif any(domain == d or domain.endswith("." + d) for d in _HIGH_CRED_DOMAINS):
            score += 0.25
        elif any(domain == d or domain.endswith("." + d) for d in _LOW_CRED_DOMAINS):
            score -= 0.25

        # Publish date recency rules
        if publish_date:
            year_match = re.search(r"\b(20\d{2})\b", str(publish_date))
            if year_match:
                year = int(year_match.group(1))
                if year >= 2025:
                    score += 0.10
                elif year <= 2018:
                    score -= 0.10

        # Heavy penalty if full scrape failed and only snippet is available
        if is_snippet_fallback:
            score = min(score, 0.35)

    except Exception:
        score = 0.40

    return max(0.10, min(1.00, round(score, 2)))


def _fetch_search_results(query: str, max_results: int = 4) -> List[Dict[str, Any]]:
    """Query search provider (Tavily or OpenRouter Perplexity) with caching."""
    cached = cache.get_cached_search(query)
    if cached is not None:
        return cached

    results: List[Dict[str, Any]] = []

    # 1. Try Tavily if configured
    tavily_key = os.getenv("TAVILY_API_KEY") or os.getenv("TAVILY_API")
    if tavily_key:
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=tavily_key)
            resp = client.search(query=query, max_results=max_results)
            raw = resp.get("results", []) if isinstance(resp, dict) else []
            for r in raw:
                results.append({
                    "title": r.get("title") or "Source",
                    "url": r.get("url", ""),
                    "snippet": r.get("content", "")[:400],
                })
        except Exception:
            pass

    # 2. Fallback to OpenRouter Perplexity Sonar search if needed
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if not results and openrouter_key:
        try:
            headers = {
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "perplexity/sonar",
                "messages": [{"role": "user", "content": f"Find recent factual info on: {query}"}],
                "max_tokens": 500,
            }
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=_NETWORK_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                msg = data["choices"][0]["message"]
                content = msg.get("content", "")
                annotations = msg.get("annotations", [])
                citations = [
                    a.get("url_citation")
                    for a in annotations
                    if isinstance(a, dict) and a.get("type") == "url_citation"
                ]
                for c in citations[:max_results]:
                    results.append({
                        "title": c.get("title") or "Web Citation",
                        "url": c.get("url", ""),
                        "snippet": content[:350],
                    })
        except Exception:
            pass

    cache.set_cached_search(query, results)
    return results


def scrape_page(url: str, snippet: str = "") -> Tuple[str, str, Optional[str], bool]:
    """Scrape webpage content using Trafilatura with BeautifulSoup & snippet fallbacks.
    Returns: (title, text, publish_date, is_snippet_fallback)"""
    cached = cache.get_cached_page(url)
    if cached is not None:
        return (
            cached.get("title", ""),
            cached.get("text", ""),
            cached.get("published"),
            cached.get("is_snippet_fallback", False),
        )

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return ("Invalid URL", snippet, None, True)

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_NETWORK_TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code == 200:
            html = resp.text

            # 1. Primary extractor: Trafilatura
            extracted_text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
            )

            # Metadata extraction (date, title)
            metadata = trafilatura.extract_metadata(html)
            title = metadata.title if (metadata and metadata.title) else ""
            pub_date = metadata.date if (metadata and metadata.date) else None

            # 2. Secondary fallback: BeautifulSoup if Trafilatura returned nothing
            if not extracted_text or len(extracted_text.strip()) < 100:
                soup = BeautifulSoup(html, "html.parser")
                if not title:
                    title_tag = soup.find("title")
                    title = title_tag.get_text(strip=True) if title_tag else ""
                for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()
                extracted_text = soup.get_text(separator=" ", strip=True)

            if extracted_text and len(extracted_text.strip()) >= 100:
                result = (title or domain_name(url), extracted_text, pub_date, False)
                cache.set_cached_page(url, {
                    "title": result[0],
                    "text": result[1],
                    "published": result[2],
                    "is_snippet_fallback": False,
                })
                return result

    except Exception:
        pass

    # 3. Tertiary fallback: search snippet (marked as low confidence)
    fallback_text = snippet if snippet else "No detailed text available."
    result = (domain_name(url), fallback_text, None, True)
    cache.set_cached_page(url, {
        "title": result[0],
        "text": result[1],
        "published": result[2],
        "is_snippet_fallback": True,
    })
    return result


def domain_name(url: str) -> str:
    """Extract clean domain name as source label."""
    try:
        netloc = urlparse(url).netloc
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return "Source"


def search_and_read(question: str, max_sources: int = 6) -> List[PageRecord]:
    """Stage 1: Parallel search queries, deduplicate URLs, scrape with Trafilatura,
    trim to ~2000 tokens, and assign rule-based credibility scores. (NO LLM)"""
    variants = generate_query_variants(question)
    all_results: List[Dict[str, Any]] = []

    # Parallel search across query variants
    with ThreadPoolExecutor(max_workers=len(variants)) as executor:
        future_to_query = {executor.submit(_fetch_search_results, q): q for q in variants}
        for future in as_completed(future_to_query):
            try:
                res = future.result()
                all_results.extend(res)
            except Exception:
                pass

    # Deduplicate by URL
    seen_urls = set()
    deduped: List[Dict[str, Any]] = []
    for item in all_results:
        url = item.get("url", "").strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped.append(item)

    # Scrape pages in parallel
    pages: List[PageRecord] = []
    with ThreadPoolExecutor(max_workers=min(len(deduped) or 1, max_sources)) as executor:
        future_to_item = {
            executor.submit(scrape_page, item["url"], item.get("snippet", "")): item
            for item in deduped[:max_sources]
        }
        source_idx = 1
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            url = item["url"]
            try:
                title, raw_text, pub_date, is_fallback = future.result()
            except Exception:
                title, raw_text, pub_date, is_fallback = (
                    domain_name(url), item.get("snippet", ""), None, True
                )

            # Trim to ~2000 tokens (~8000 characters)
            trimmed_text = raw_text[:8000]
            credibility = calculate_credibility(url, pub_date, is_fallback)

            source_id = f"s{source_idx}"
            source_idx += 1

            pages.append(PageRecord(
                source_id=source_id,
                source_name=title or domain_name(url),
                url=url,
                raw_text=raw_text,
                trimmed_text=trimmed_text,
                published=pub_date or "Unknown date",
                credibility=credibility,
                is_snippet_fallback=is_fallback,
            ))

    return pages


def verify_quote(quote: str, page_text: str) -> bool:
    """Strict verification: checks if the exact quote is contained in the page text.
    Whitespace-normalized and case-insensitive.
    Returns False if quote is hallucinated or shorter than 12 characters."""
    if not quote or not page_text:
        return False

    norm_quote = " ".join(quote.strip().split()).lower()
    norm_page = " ".join(page_text.split()).lower()

    if len(norm_quote) < 12:
        return False

    return norm_quote in norm_page


def format_citations(report_text: str, valid_source_ids: Dict[str, PageRecord]) -> Tuple[str, List[str]]:
    """Converts [s1] markers to clickable Markdown links, and rejects any marker
    not present in the registered source records.
    Returns: (cleaned_report_markdown, list_of_rejected_markers)"""
    rejected = []

    def _replace_marker(match: re.Match) -> str:
        marker = match.group(1).lower()  # e.g., "s1"
        if marker in valid_source_ids:
            source = valid_source_ids[marker]
            name = source.source_name[:25]
            # Clickable anchor link with tooltip
            return f" [[{marker}: {name}]]({source.url}) "
        else:
            rejected.append(marker)
            return ""  # Reject / remove hallucinated marker

    # Replace markers like [s1], [s2], [S1]
    formatted = re.sub(r"\[(s\d+)\]", _replace_marker, report_text, flags=re.IGNORECASE)
    
    # Clean up double spaces or floating punctuation
    formatted = re.sub(r" {2,}", " ", formatted)
    formatted = re.sub(r" \.", ".", formatted)
    return formatted.strip(), rejected
