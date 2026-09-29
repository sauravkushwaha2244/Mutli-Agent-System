"""Supabase integration client for storing and retrieving research history."""

import os
import json
import time
import requests
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

_TIMEOUT = 8.0


def is_supabase_configured() -> bool:
    """Check if Supabase credentials are set."""
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _get_headers() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }


def save_research_run(
    result_dict: Dict[str, Any],
    user_id: Optional[str] = None,
    user_email: Optional[str] = None
) -> Dict[str, Any]:
    """Save completed research run to Supabase research_history table.
    Falls back gracefully to local SQLite cache if table is not yet created or unreachable."""
    topic = result_dict.get("topic", "")
    report = result_dict.get("report_markdown", "")
    sources = result_dict.get("sources", [])
    claims = result_dict.get("claims", [])
    visuals = result_dict.get("visuals", {})
    stats = result_dict.get("stats", {})

    avg_cred = 0.0
    if sources:
        avg_cred = round(sum(s.get("credibility", 0.5) for s in sources) / len(sources), 2)

    payload = {
        "topic": topic,
        "report_markdown": report,
        "sources_count": len(sources),
        "claims_count": len(claims),
        "credibility_avg": avg_cred,
        "sources_data": sources,
        "claims_data": claims,
        "visuals_data": visuals,
    }
    if user_id:
        payload["user_id"] = user_id
    if user_email:
        payload["user_email"] = user_email

    if is_supabase_configured():
        try:
            endpoint = f"{SUPABASE_URL}/rest/v1/research_history"
            resp = requests.post(endpoint, headers=_get_headers(), json=payload, timeout=_TIMEOUT)
            if resp.status_code in (200, 201):
                rows = resp.json()
                if rows and isinstance(rows, list):
                    return {"saved_to": "supabase", "id": rows[0].get("id")}
                return {"saved_to": "supabase"}
            elif resp.status_code in (400, 422) and (user_id or user_email):
                # Retry without user fields in case columns do not exist yet
                clean_payload = {k: v for k, v in payload.items() if k not in ("user_id", "user_email")}
                retry_resp = requests.post(endpoint, headers=_get_headers(), json=clean_payload, timeout=_TIMEOUT)
                if retry_resp.status_code in (200, 201):
                    rows = retry_resp.json()
                    if rows and isinstance(rows, list):
                        return {"saved_to": "supabase", "id": rows[0].get("id")}
                    return {"saved_to": "supabase"}
        except Exception:
            pass

    # Fallback to local SQLite history if Supabase is unavailable
    try:
        import cache
        conn = cache._get_connection()
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS local_history (
                    id TEXT PRIMARY KEY,
                    topic TEXT,
                    report_markdown TEXT,
                    sources_count INTEGER,
                    claims_count INTEGER,
                    credibility_avg REAL,
                    sources_json TEXT,
                    claims_json TEXT,
                    visuals_json TEXT,
                    created_at REAL
                )
            """)
            local_id = f"local_{int(time.time())}"
            conn.execute("""
                INSERT INTO local_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                local_id, topic, report, len(sources), len(claims), avg_cred,
                json.dumps(sources), json.dumps(claims), json.dumps(visuals), time.time()
            ))
        conn.close()
        return {"saved_to": "local_sqlite", "id": local_id}
    except Exception:
        return {"saved_to": "none"}


def get_history(limit: int = 20, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve list of previous research runs from Supabase or local fallback."""
    if is_supabase_configured():
        try:
            if user_id:
                endpoint = f"{SUPABASE_URL}/rest/v1/research_history?user_id=eq.{user_id}&select=id,topic,created_at,sources_count,claims_count,credibility_avg&order=created_at.desc&limit={limit}"
                resp = requests.get(endpoint, headers=_get_headers(), timeout=_TIMEOUT)
                if resp.status_code == 200:
                    rows = resp.json()
                    if rows:
                        return rows
                # If no user-specific rows or error, proceed to fallback general list
            endpoint = f"{SUPABASE_URL}/rest/v1/research_history?select=id,topic,created_at,sources_count,claims_count,credibility_avg&order=created_at.desc&limit={limit}"
            resp = requests.get(endpoint, headers=_get_headers(), timeout=_TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass

    # Local fallback
    try:
        import cache
        conn = cache._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, topic, created_at, sources_count, claims_count, credibility_avg
            FROM local_history ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "topic": r[1],
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r[2])),
                "sources_count": r[3],
                "claims_count": r[4],
                "credibility_avg": r[5]
            }
            for r in rows
        ]
    except Exception:
        return []


def get_history_detail(record_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve full research brief by ID."""
    if is_supabase_configured():
        try:
            endpoint = f"{SUPABASE_URL}/rest/v1/research_history?id=eq.{record_id}&select=*"
            resp = requests.get(endpoint, headers=_get_headers(), timeout=_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list):
                    item = data[0]
                    return {
                        "topic": item.get("topic"),
                        "report_markdown": item.get("report_markdown"),
                        "sources": item.get("sources_data", []),
                        "claims": item.get("claims_data", []),
                        "visuals": item.get("visuals_data", {}),
                        "created_at": item.get("created_at"),
                    }
        except Exception:
            pass

    # Local fallback
    try:
        import cache
        conn = cache._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT topic, report_markdown, sources_json, claims_json, visuals_json, created_at FROM local_history WHERE id = ?", (record_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                "topic": row[0],
                "report_markdown": row[1],
                "sources": json.loads(row[2]) if row[2] else [],
                "claims": json.loads(row[3]) if row[3] else [],
                "visuals": json.loads(row[4]) if row[4] else {},
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(row[5])),
            }
    except Exception:
        pass

    return None
