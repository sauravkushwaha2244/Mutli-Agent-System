"""Disk-backed caching for search results and scraped web pages."""

import os
import sqlite3
import json
import time
from typing import Optional, Any, Dict, List

_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
_CACHE_DB = os.path.join(_CACHE_DIR, "pipeline_cache.db")


def _get_connection() -> sqlite3.Connection:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    conn = sqlite3.connect(_CACHE_DB, timeout=10.0)
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                query TEXT PRIMARY KEY,
                results TEXT,
                created_at REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_cache (
                url TEXT PRIMARY KEY,
                page_data TEXT,
                created_at REAL
            )
        """)
    return conn


def get_cached_search(query: str, max_age_hours: float = 24.0) -> Optional[List[Dict[str, Any]]]:
    """Retrieve cached search results if available and fresh."""
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute("SELECT results, created_at FROM search_cache WHERE query = ?", (query.strip().lower(),))
        row = cur.fetchone()
        conn.close()
        if row:
            results_json, created_at = row
            if time.time() - created_at < max_age_hours * 3600:
                return json.loads(results_json)
    except Exception:
        pass
    return None


def set_cached_search(query: str, results: List[Dict[str, Any]]) -> None:
    """Store search results in cache."""
    try:
        conn = _get_connection()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO search_cache (query, results, created_at) VALUES (?, ?, ?)",
                (query.strip().lower(), json.dumps(results), time.time())
            )
        conn.close()
    except Exception:
        pass


def get_cached_page(url: str, max_age_hours: float = 48.0) -> Optional[Dict[str, Any]]:
    """Retrieve cached scraped page data if available and fresh."""
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute("SELECT page_data, created_at FROM page_cache WHERE url = ?", (url.strip(),))
        row = cur.fetchone()
        conn.close()
        if row:
            page_json, created_at = row
            if time.time() - created_at < max_age_hours * 3600:
                return json.loads(page_json)
    except Exception:
        pass
    return None


def set_cached_page(url: str, page_data: Dict[str, Any]) -> None:
    """Store scraped page data in cache."""
    try:
        conn = _get_connection()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO page_cache (url, page_data, created_at) VALUES (?, ?, ?)",
                (url.strip(), json.dumps(page_data), time.time())
            )
        conn.close()
    except Exception:
        pass


def clear_cache() -> None:
    """Clear all cached search and page records."""
    try:
        if os.path.exists(_CACHE_DB):
            os.remove(_CACHE_DB)
    except Exception:
        pass
