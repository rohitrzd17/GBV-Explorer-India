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

# Positive GBV classification patterns
GBV_POSITIVE_PATTERNS = [
    # Sexual assault & rape
    r"\b(gang\s*rape[ds]?|gang\s*raping|rape[ds]?|raping|rapist[s]?)\b",
    r"\b(sexual(?:ly)?\s+(?:assault(?:ed|s|ing)?|harass(?:ed|ment|ing)?|abuse[ds]?|abusing|exploit(?:ed|ation|ing)?))\b",
    r"\b(sex\s+assault(?:ed|s|ing)?)\b",
    r"\b(molest(?:ed|ation|s|ing)?|molester[s]?)\b",
    r"\b(eve[\s\-]teas(?:ing|ed|er[s]?))\b",
    r"\b(indecent\s+assault|outrag(?:ing|ed)\s+(?:the\s+)?modesty)\b",
    
    # POCSO & child safety
    r"\b(pocso|protection of children from sexual offences)\b",
    r"\b(?:minor|underage|school)\s*girl[s]?\s+(?:rape[ds]?|assault(?:ed)?|molest(?:ed)?|abused|kidnapped|murdered)\b",
    r"\bchild\s+(?:sexual\s+abuse|sexual\s+assault|rape[ds]?|molestation)\b",
    
    # Domestic & Dowry violence
    r"\b(domestic\s+violence|dowry|dowry\s+death|dowry\s+harassment|bride\s+burning)\b",
    r"\b(498[\s\-]?a|bns\s+85|cruelty\s+by\s+husband)\b",
    r"\b(?:husband|in[\s\-]laws|father[\s\-]in[\s\-]law|mother[\s\-]in[\s\-]law)\s+(?:beat(?:en|ing)?|tortur(?:ed|ing)|kill(?:ed|ing)?|harass(?:ed|ing)?)\s+(?:wife|woman|daughter[\s\-]in[\s\-]law)\b",
    r"\bmarital\s+rape\b",
    
    # Acid attacks & stalking
    r"\b(acid\s+attack[s]?|threw\s+acid|acid\s+thrown|vitriolage)\b",
    r"\b(stalk(?:ed|ing|er[s]?)|voyeurism)\b",
    
    # Honor killings, foeticide & forced marriages
    r"\b(honou?r\s+killing[s]?)\b",
    r"\b(female\s+fo?eticide|female\s+infanticide)\b",
    r"\b(child\s+marriage[s]?|forced\s+marriage[s]?|underage\s+marriage[s]?)\b",
    r"\b(traffick(?:ed|ing)?\s+(?:of\s+)?(?:girls?|women)|forced\s+prostitution|flesh\s+trade)\b",
]

GBV_METAPHOR_EXCLUSIONS = [
    r"\brape\s+of\s+democracy\b",
    r"\bassault\s+on\s+(?:democracy|institutions?|judiciary|constitution|media|rights)\b",
    r"\btax\s+harassment\b",
    r"\bfinancial\s+harassment\b",
    r"\bpolitical\s+harassment\b",
    r"\bcricket\s+assault\b",
    r"\bbatting\s+assault\b"
]

def passes_gbv_constraints(headline: str, snippet: str, constraints: str = "gbv_strict") -> bool:
    """Validate whether an article strictly pertains to Gender-Based Violence."""
    import re
    text = f"{headline} {snippet}".lower()
    
    # 1. Reject metaphorical or political usage
    for excl in GBV_METAPHOR_EXCLUSIONS:
        if re.search(excl, text):
            return False

    # 2. Check custom constraints if provided and not default
    if constraints and constraints != "gbv_strict":
        parts = [p.strip() for p in constraints.split(",") if p.strip()]
        for p in parts:
            if re.search(r"\b" + re.escape(p.lower()) + r"\b", text):
                return True
        try:
            if re.search(constraints, text, re.IGNORECASE):
                return True
        except Exception:
            pass

    # 3. Check core positive GBV patterns
    for pat in GBV_POSITIVE_PATTERNS:
        if re.search(pat, text):
            return True
            
    return False

def build_google_news_rss_url(query: str) -> str:
    final_query = f"{query} {FOREIGN_NEGATIVES}".strip()
    encoded_q = urllib.parse.quote(final_query)
    return f"https://news.google.com/rss/search?q={encoded_q}&hl=en-IN&gl=IN&ceid=IN:en"

def fetch_feed_items(query_or_url: str, feed_type: str = "google_news", constraints: str = "gbv_strict") -> List[Dict[str, Any]]:
    """Fetch feed items and enforce strict GBV constraints."""
    import re
    is_direct_url = (feed_type == "rss_url") or query_or_url.startswith("http://") or query_or_url.startswith("https://")
    
    if is_direct_url:
        fetch_url = query_or_url
    else:
        fetch_url = build_google_news_rss_url(query_or_url)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        resp = requests.get(fetch_url, headers=headers, timeout=12)
        if resp.status_code != 200:
            print(f"[Warn] RSS fetch returned status {resp.status_code} for: {fetch_url[:80]}")
            return []
        
        feed = feedparser.parse(resp.content)
        items = []
        rejected_non_gbv = 0

        for entry in feed.entries:
            title = getattr(entry, "title", "").strip()
            summary = getattr(entry, "summary", "").strip()
            link = getattr(entry, "link", "")

            # Strip HTML tags from summary
            clean_summary = re.sub(r"<[^>]+>", "", summary).strip()

            # Enforce GBV Constraint
            if not passes_gbv_constraints(title, clean_summary, constraints):
                rejected_non_gbv += 1
                continue

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
            elif " - " in title:
                publisher = title.split(" - ")[-1].strip()

            items.append({
                "headline": title,
                "publisher": publisher,
                "url": link,
                "published_at": published_dt,
                "raw_snippet": clean_summary
            })
            
        if rejected_non_gbv > 0:
            print(f"       [GBV Constraint] Kept {len(items)} GBV reports, filtered out {rejected_non_gbv} non-GBV general articles.")
            
        return items
    except Exception as e:
        print(f"[Error] Failed to fetch feed '{query_or_url[:60]}': {e}")
        return []

def run_fetch_for_feed(feed_id: int) -> int:
    """Fetch and filter articles for a specific active feed."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM feeds WHERE id = ?", (feed_id,))
    feed = cursor.fetchone()
    if not feed:
        conn.close()
        return 0

    query = feed["query"]
    feed_type = feed["feed_type"] if "feed_type" in feed.keys() else "google_news"
    constraints = feed["constraints"] if "constraints" in feed.keys() else "gbv_strict"

    print(f"[Fetch] Querying feed [{feed['name']}] ({feed_type}): {query[:60]}... [Constraints: {constraints}]")
    items = fetch_feed_items(query, feed_type=feed_type, constraints=constraints)
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
    print(f"[Fetch] Feed [{feed['name']}] yielded {len(items)} GBV items ({new_count} new saved).")
    return new_count

def run_fetch(sample_mode: bool = False, max_feeds: int = 8) -> int:
    init_db()
    os.makedirs(RAW_NEWS_DIR, exist_ok=True)
    
    total_new = 0
    all_fetched = []

    # Pull active feeds from database
    active_feeds = [f for f in get_all_feeds() if f.get("is_active", 1)]
    if sample_mode:
        active_feeds = active_feeds[:max_feeds]

    for feed in active_feeds:
        f_type = feed.get("feed_type", "google_news")
        f_cons = feed.get("constraints", "gbv_strict")
        print(f"[Fetch] Querying active feed [{feed['name']}] ({f_type})...")
        items = fetch_feed_items(feed["query"], feed_type=f_type, constraints=f_cons)
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

    print(f"[Fetch] Completed. Ingested {len(all_fetched)} total GBV reports ({total_new} new unique) from {len(active_feeds)} feeds.")
    return total_new

if __name__ == "__main__":
    is_sample = "--sample" in sys.argv
    run_fetch(sample_mode=is_sample, max_feeds=5 if is_sample else 30)
