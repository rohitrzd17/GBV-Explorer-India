"""
Execution script: Backfill 6 months of historical GBV incident reports across India.
Queries Google News RSS month-by-month from March 2026 to September 2026 across
all major categories and regions, extracting structured records and geocoding them.
"""

import os
import sys
import time
import re
import urllib.parse
from datetime import datetime, timezone
import feedparser

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from execution.database import (
    get_connection,
    save_raw_source,
    create_incident,
    mark_source_processed,
    get_all_incidents,
    get_statistics
)
from execution.extract_incidents import rule_based_extract, clean_text
from execution.geocode_locations import geocode_location
from execution.deduplicate import deduplicate_incidents

# Monthly intervals over the past 6 months (March 2026 - September 2026)
MONTH_WINDOWS = [
    ("2026-03-01", "2026-04-01", "March 2026"),
    ("2026-04-01", "2026-05-01", "April 2026"),
    ("2026-05-01", "2026-06-01", "May 2026"),
    ("2026-06-01", "2026-07-01", "June 2026"),
    ("2026-07-01", "2026-08-01", "July 2026"),
    ("2026-08-01", "2026-09-12", "Aug-Sep 2026")
]

# Core GBV thematic and regional search queries
QUERY_TEMPLATES = [
    '("rape" OR "gang rape" OR "sexual assault") (India OR police OR FIR) -UK -USA -Australia',
    '("POCSO" OR "minor girl" OR "child abuse" OR "schoolgirl") (India OR police OR arrested) -UK -USA -Australia',
    '("domestic violence" OR "dowry death" OR "dowry harassment" OR "498A") (India OR police) -UK -USA -Australia',
    '("molestation" OR "harassment" OR "acid attack" OR "stalking") (India OR police) -UK -USA -Australia',
    '("rape" OR "sexual assault" OR "crime") (Delhi OR Noida OR Gurugram OR UP OR "Uttar Pradesh") -UK -USA -Australia',
    '("rape" OR "sexual assault" OR "crime") (Maharashtra OR Mumbai OR Pune OR Gujarat) -UK -USA -Australia',
    '("rape" OR "sexual assault" OR "crime") (Bengaluru OR Karnataka OR Chennai OR "Tamil Nadu" OR Hyderabad OR Telangana OR Kerala) -UK -USA -Australia',
    '("rape" OR "sexual assault" OR "crime") ("West Bengal" OR Kolkata OR Bihar OR Patna OR Odisha OR Assam) -UK -USA -Australia',
    '("rape" OR "sexual assault" OR "crime") (Punjab OR Haryana OR Rajasthan OR "Madhya Pradesh") -UK -USA -Australia'
]

def fetch_rss_window(base_query: str, start_date: str, end_date: str):
    full_q = f"{base_query} after:{start_date} before:{end_date}"
    encoded = urllib.parse.quote(full_q)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        feed = feedparser.parse(url, request_headers=headers)
        return feed.entries
    except Exception as e:
        print(f"      [Error] RSS fetch failed for {full_q[:50]}: {e}")
        return []

def run_backfill():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM incidents")
    initial_cnt = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) as cnt FROM incidents WHERE latitude IS NOT NULL")
    initial_geo = cur.fetchone()["cnt"]
    conn.close()
    
    print("=" * 65)
    print(f"Starting 6-Month GBV Incident Historical Backfill (March - September 2026)")
    print(f"Current database state: {initial_cnt} incidents ({initial_geo} geocoded)")
    print("=" * 65)

    total_new_extracted = 0
    total_new_geocoded = 0

    for start_date, end_date, window_label in MONTH_WINDOWS:
        print(f"\n>>> Processing {window_label} ({start_date} to {end_date})...")
        window_extracted = 0
        window_geocoded = 0

        for q_idx, q_template in enumerate(QUERY_TEMPLATES, 1):
            entries = fetch_rss_window(q_template, start_date, end_date)
            
            for entry in entries:
                title = getattr(entry, "title", "").strip()
                summary = getattr(entry, "summary", "").strip()
                link = getattr(entry, "link", "").strip()

                if not title or not link:
                    continue

                clean_summary = clean_text(re.sub(r"<[^>]+>", "", summary).strip())
                clean_title = clean_text(title)

                # Parse publication date
                pub_dt = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        pub_dt = datetime(*entry.published_parsed[:6]).isoformat()
                    except Exception:
                        pub_dt = f"{start_date}T12:00:00"
                else:
                    pub_dt = f"{start_date}T12:00:00"

                # Extract incident using rule-based NLP
                extracted = rule_based_extract(clean_title, clean_summary, pub_dt)
                if not extracted:
                    continue

                loc_name = extracted.get("location_name")
                state_hint = extracted.get("state")

                # Geocode
                geo = geocode_location(loc_name, state_hint)
                lat = geo.get("lat")
                lon = geo.get("lon")
                resolved_state = geo.get("state") or state_hint
                resolved_dist = geo.get("district") or loc_name

                # Clean publisher name
                publisher = "News Outlet"
                if hasattr(entry, "source") and hasattr(entry.source, "title"):
                    publisher = entry.source.title
                elif " - " in title:
                    publisher = title.split(" - ")[-1].strip()

                # Save raw source (returns None if URL already exists in DB)
                source_id = save_raw_source(
                    headline=clean_title,
                    publisher=publisher,
                    url=link,
                    published_at=pub_dt,
                    raw_snippet=clean_summary
                )

                if source_id:
                    # Create incident
                    inc_id = create_incident({
                        "title": extracted["title"],
                        "summary": extracted["summary"],
                        "category": extracted["category"],
                        "incident_date": extracted["incident_date"],
                        "location_name": resolved_dist or loc_name,
                        "district": resolved_dist or loc_name,
                        "state": resolved_state,
                        "latitude": lat,
                        "longitude": lon,
                        "legal_status": extracted["legal_status"]
                    })
                    mark_source_processed(source_id, inc_id)
                    window_extracted += 1
                    total_new_extracted += 1

                    if lat is not None and lon is not None:
                        window_geocoded += 1
                        total_new_geocoded += 1

            # Friendly rate limiting to avoid hitting Google News RSS rate limits
            time.sleep(0.6)

        print(f"    Completed {window_label}: +{window_extracted} incidents extracted (+{window_geocoded} geocoded)")

    print("\n" + "=" * 65)
    print(f"Backfill Completed: +{total_new_extracted} incidents added (+{total_new_geocoded} geocoded)")
    print("Running deduplication across 6-month historical corpus...")
    print("=" * 65)

    dedup_results = deduplicate_incidents()
    print(f"Deduplication: merged {dedup_results} duplicate incident clusters.")

    # Final DB Stats
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM incidents")
    final_cnt = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) as cnt FROM incidents WHERE latitude IS NOT NULL")
    final_geo = cur.fetchone()["cnt"]
    conn.close()

    print(f"\nFinal 6-Month Database State:")
    print(f"  Total Incidents: {final_cnt}")
    print(f"  Geocoded Incidents: {final_geo} ({final_geo/final_cnt*100:.1f}%)")

if __name__ == "__main__":
    run_backfill()
