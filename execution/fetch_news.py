"""
Execution script: Fetch news reports regarding GBV from Google News RSS across India.
"""

import os
import sys
import json
import urllib.parse
from datetime import datetime, timezone
from typing import List, Dict, Any
import xml.etree.ElementTree as ET

# Ensure workspace root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import requests
import feedparser
from execution.database import init_db, save_raw_source, get_all_feeds, get_connection

RAW_NEWS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".tmp", "raw_news")

# Negative foreign keywords to prevent US/UK crime stories from Google News
FOREIGN_NEGATIVES = "-Kentucky -Massachusetts -Clancy -Mayfield -Florida -Texas -Ohio -Sheriff -California"

def build_google_news_rss_url(query: str) -> str:
    # If query does not already contain URL or negative filters, append them
    final_query = f"{query} {FOREIGN_NEGATIVES}".strip()
    encoded_q = urllib.parse.quote(final_query)
    return f"https://news.google.com/rss/search?q={encoded_q}&hl=en-IN&gl=IN&ceid=IN:en"

def fetch_feed_items(query: str) -> List[Dict[str, Any]]:
    url = build_google_news_rss_url(query)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code != 200:
            print(f"[Warn] RSS fetch returned status {resp.status_code} for query: {query}")
            return []
        
        feed = feedparser.parse(resp.content)
        items = []
        for entry in feed.entries:
            published_dt = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published_dt = datetime(*entry.published_parsed[:6]).isoformat()
                except Exception:
                    published_dt = datetime.now(timezone.utc).isoformat()
            else:
                published_dt = datetime.now(timezone.utc).isoformat()

            # Clean publisher source name
            publisher = "Unknown"
            if hasattr(entry, "source") and hasattr(entry.source, "title"):
                publisher = entry.source.title
            elif " - " in entry.title:
                publisher = entry.title.split(" - ")[-1].strip()

            items.append({
                "headline": entry.title,
                "publisher": publisher,
                "url": entry.link,
                "published_at": published_dt,
                "raw_snippet": getattr(entry, "summary", "")
            })
        return items
    except Exception as e:
        print(f"[Error] Failed to fetch feed for query '{query}': {e}")
        return []

def run_fetch_for_feed(feed_id: int) -> int:
    """Fetch articles for a specific active feed."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM feeds WHERE id = ?", (feed_id,))
    feed = cursor.fetchone()
    if not feed:
        conn.close()
        return 0

    query = feed["query"]
    print(f"[Fetch] Querying feed [{feed['name']}]: {query}")
    items = fetch_feed_items(query)
    new_count = 0
    for item in items:
        row_id = save_raw_source(
            headline=item["headline"],
            publisher=item["publisher"],
            url=item["url"],
            published_at=item["published_at"],
            raw_snippet=item["raw_snippet"]
        )
        if row_id:
            new_count += 1

    cursor.execute("UPDATE feeds SET last_fetched_at = CURRENT_TIMESTAMP WHERE id = ?", (feed_id,))
    conn.commit()
    conn.close()
    print(f"[Fetch] Feed [{feed['name']}] fetched {len(items)} items ({new_count} new).")
    return new_count

def run_fetch(sample_mode: bool = False, max_regions: int = 5) -> int:
    init_db()
    os.makedirs(RAW_NEWS_DIR, exist_ok=True)
    
    total_new = 0
    all_fetched = []

    # Pull active feeds from the database
    active_feeds = [f for f in get_all_feeds() if f.get("is_active", 1)]
    if sample_mode:
        active_feeds = active_feeds[:max_regions]

    for feed in active_feeds:
        print(f"[Fetch] Querying active feed [{feed['name']}]: {feed['query']}")
        items = fetch_feed_items(feed["query"])
        all_fetched.extend(items)
        # Update last_fetched_at
        conn = get_connection()
        conn.execute("UPDATE feeds SET last_fetched_at = CURRENT_TIMESTAMP WHERE id = ?", (feed["id"],))
        conn.commit()
        conn.close()

    # Save to SQLite and intermediate cache
    for item in all_fetched:
        row_id = save_raw_source(
            headline=item["headline"],
            publisher=item["publisher"],
            url=item["url"],
            published_at=item["published_at"],
            raw_snippet=item["raw_snippet"]
        )
        if row_id:
            total_new += 1

    cache_file = os.path.join(RAW_NEWS_DIR, f"fetch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json")
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(all_fetched, f, indent=2)

    print(f"[Fetch] Ingested {len(all_fetched)} total articles ({total_new} new unique) from {len(active_feeds)} feeds.")
    return total_new

if __name__ == "__main__":
    is_sample = "--sample" in sys.argv
    run_fetch(sample_mode=is_sample, max_regions=3 if is_sample else 15)
