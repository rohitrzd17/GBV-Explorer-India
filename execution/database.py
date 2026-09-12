"""
Database layer for GBV Explorer (SQLite).
Stores raw news sources, extracted GBV incidents, and geocoding cache.
"""

import sqlite3
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

DB_PATH = os.environ.get("GBV_DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "incidents.db"))

def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Table: incidents (Master unique incidents)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            summary TEXT,
            category TEXT NOT NULL DEFAULT 'Other GBV',
            incident_date TEXT,
            location_name TEXT,
            district TEXT,
            state TEXT,
            latitude REAL,
            longitude REAL,
            legal_status TEXT DEFAULT 'Under Investigation',
            cluster_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Table: sources (Articles reporting on incidents)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER,
            headline TEXT NOT NULL,
            publisher TEXT,
            url TEXT UNIQUE,
            published_at TEXT,
            raw_snippet TEXT,
            processed BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE SET NULL
        )
    """)

    # Table: geocode_cache (Persistent cache for location lookups)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS geocode_cache (
            query TEXT PRIMARY KEY,
            district TEXT,
            state TEXT,
            latitude REAL,
            longitude REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Table: feeds (Configurable RSS feeds and search queries)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            query TEXT NOT NULL,
            region TEXT DEFAULT 'India',
            category_hint TEXT DEFAULT 'All',
            feed_type TEXT DEFAULT 'google_news',
            constraints TEXT DEFAULT 'gbv_strict',
            is_active BOOLEAN DEFAULT 1,
            last_fetched_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Schema migration for feeds table if columns are missing
    cursor.execute("PRAGMA table_info(feeds)")
    feed_cols = [row[1] for row in cursor.fetchall()]
    if "feed_type" not in feed_cols:
        cursor.execute("ALTER TABLE feeds ADD COLUMN feed_type TEXT DEFAULT 'google_news'")
    if "constraints" not in feed_cols:
        cursor.execute("ALTER TABLE feeds ADD COLUMN constraints TEXT DEFAULT 'gbv_strict'")

    # Seed default Google News monitors if table is empty
    cursor.execute("SELECT COUNT(*) FROM feeds")
    if cursor.fetchone()[0] == 0:
        default_feeds = [
            ("National GBV Monitor", '("rape" OR "sexual assault" OR "domestic violence" OR "POCSO") (India OR Indian OR Delhi OR Mumbai)', "India", "All", "google_news", "gbv_strict"),
            ("Delhi NCR Crime", '("rape" OR "molestation" OR "harassment" OR "eve teasing") (Delhi OR Noida OR Gurugram OR Ghaziabad)', "Delhi NCR", "Harassment & Stalking", "google_news", "gbv_strict"),
            ("Uttar Pradesh Crime", '("rape" OR "gang rape" OR "dowry death" OR "domestic violence") (UP OR "Uttar Pradesh" OR Lucknow OR Kanpur OR Agra)', "Uttar Pradesh", "Sexual Assault", "google_news", "gbv_strict"),
            ("Maharashtra Crime", '("sexual assault" OR "molestation" OR "rape") (Maharashtra OR Mumbai OR Pune OR Thane OR Nagpur)', "Maharashtra", "Sexual Assault", "google_news", "gbv_strict"),
            ("West Bengal Crime", '("rape" OR "sexual assault" OR "harassment") ("West Bengal" OR Kolkata OR Howrah OR Sandeshkhali)', "West Bengal", "Sexual Assault", "google_news", "gbv_strict"),
            ("South India GBV Monitor", '("rape" OR "sexual assault" OR "domestic violence") (Bengaluru OR Chennai OR Hyderabad OR Kerala OR "Tamil Nadu")', "South India", "All", "google_news", "gbv_strict"),
            ("POCSO & Child Safety", '("POCSO" OR "minor girl" OR "schoolgirl" OR "child abuse") (India OR police OR FIR)', "India", "POCSO / Minor", "google_news", "gbv_strict")
        ]
        cursor.executemany("""
            INSERT INTO feeds (name, query, region, category_hint, feed_type, constraints, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, default_feeds)

    # Seed national RSS feeds (The Hindu, TOI) and curated RSS Catalog feeds if not yet registered
    rss_catalog_feeds = [
        ("The Hindu (National)", "https://www.thehindu.com/news/national/feeder/default.rss", "India", "All", "rss_url", "gbv_strict"),
        ("Times of India (National)", "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms", "India", "All", "rss_url", "gbv_strict"),
        ("NDTV National News", "https://feeds.feedburner.com/NDTV-LatestNews", "India", "All", "rss_url", "gbv_strict"),
        ("News18 India", "https://www.news18.com/rss/india.xml", "India", "All", "rss_url", "gbv_strict"),
        ("DNA India", "https://www.dnaindia.com/feeds/india.xml", "India", "All", "rss_url", "gbv_strict"),
        ("Deccan Chronicle", "https://www.deccanchronicle.com/rss_feed/", "South India", "All", "rss_url", "gbv_strict"),
        ("India Today", "https://www.indiatoday.in/rss/1206578", "India", "All", "rss_url", "gbv_strict"),
        ("Scroll.in", "https://feeds.feedburner.com/ScrollinArticles.rss", "India", "All", "rss_url", "gbv_strict"),
        ("Orissa Post", "https://www.orissapost.com/feed/", "Odisha", "All", "rss_url", "gbv_strict"),
        ("Telangana Today", "https://telanganatoday.com/feed", "Telangana", "All", "rss_url", "gbv_strict"),
        ("The Arunachal Times", "https://arunachaltimes.in/index.php/feed/", "North East", "All", "rss_url", "gbv_strict"),
        ("Star of Mysore", "https://starofmysore.com/feed/", "Karnataka", "All", "rss_url", "gbv_strict"),
        ("The News Himachal", "https://thenewshimachal.com/feed/", "Himachal Pradesh", "All", "rss_url", "gbv_strict"),
        ("Chandigarh City News", "https://feeds.feedburner.com/ChandigarhCityNews", "Punjab & Haryana", "All", "rss_url", "gbv_strict"),
        ("#KhabarLive Hyderabad", "https://hydnews.net/feed/", "Telangana", "All", "rss_url", "gbv_strict"),
    ]
    for name, query, region, category_hint, feed_type, constraints in rss_catalog_feeds:
        cursor.execute("SELECT id FROM feeds WHERE query = ? OR name = ?", (query, name))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO feeds (name, query, region, category_hint, feed_type, constraints, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (name, query, region, category_hint, feed_type, constraints))

    # Performance indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sources_incident_id ON sources(incident_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_date ON incidents(incident_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_category ON incidents(category)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_incidents_state ON incidents(state)")

    conn.commit()
    conn.close()

def save_raw_source(headline: str, publisher: str, url: str, published_at: str, raw_snippet: str) -> Optional[int]:
    """Save article if not already present."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR IGNORE INTO sources (headline, publisher, url, published_at, raw_snippet)
            VALUES (?, ?, ?, ?, ?)
        """, (headline, publisher, url, published_at, raw_snippet))
        conn.commit()
        return cursor.lastrowid if cursor.rowcount > 0 else None
    finally:
        conn.close()

def get_unprocessed_sources(limit: int = 100) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM sources WHERE processed = 0 ORDER BY id ASC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def mark_source_processed(source_id: int, incident_id: Optional[int] = None):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE sources SET processed = 1, incident_id = ? WHERE id = ?", (incident_id, source_id))
        conn.commit()
    finally:
        conn.close()

def create_incident(data: Dict[str, Any]) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO incidents (
                title, summary, category, incident_date, location_name,
                district, state, latitude, longitude, legal_status, cluster_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get("title", "GBV Incident"),
            data.get("summary", ""),
            data.get("category", "Other GBV"),
            data.get("incident_date"),
            data.get("location_name"),
            data.get("district"),
            data.get("state"),
            data.get("latitude"),
            data.get("longitude"),
            data.get("legal_status", "Under Investigation"),
            data.get("cluster_id")
        ))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def get_all_incidents(
    category: Optional[str] = None,
    state: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    only_geocoded: bool = False
) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        query = """
            SELECT i.*, 
                   (SELECT COUNT(*) FROM sources s WHERE s.incident_id = i.id) as source_count,
                   (SELECT GROUP_CONCAT(publisher, ', ') FROM sources s WHERE s.incident_id = i.id) as publishers,
                   (SELECT url FROM sources s WHERE s.incident_id = i.id LIMIT 1) as primary_url
            FROM incidents i
            WHERE 1=1
        """
        params = []

        if only_geocoded:
            query += " AND i.latitude IS NOT NULL AND i.longitude IS NOT NULL"
        if category and category != "All":
            query += " AND i.category = ?"
            params.append(category)
        if state and state != "All":
            query += " AND i.state = ?"
            params.append(state)
        if start_date:
            query += " AND i.incident_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND i.incident_date <= ?"
            params.append(end_date)

        query += " ORDER BY i.incident_date DESC, i.id DESC"
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def get_incident_sources(incident_id: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM sources WHERE incident_id = ? ORDER BY published_at DESC", (incident_id,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def get_statistics() -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM incidents")
        total_incidents = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM incidents WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
        geocoded_incidents = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sources")
        total_sources = cursor.fetchone()[0]

        cursor.execute("""
            SELECT category, COUNT(*) as cnt 
            FROM incidents 
            GROUP BY category 
            ORDER BY cnt DESC
        """)
        category_breakdown = {row["category"]: row["cnt"] for row in cursor.fetchall()}

        cursor.execute("""
            SELECT state, COUNT(*) as cnt 
            FROM incidents 
            WHERE state IS NOT NULL 
            GROUP BY state 
            ORDER BY cnt DESC 
            LIMIT 10
        """)
        state_breakdown = {row["state"]: row["cnt"] for row in cursor.fetchall()}

        return {
            "total_incidents": total_incidents,
            "geocoded_incidents": geocoded_incidents,
            "total_sources": total_sources,
            "categories": category_breakdown,
            "top_states": state_breakdown
        }
    finally:
        conn.close()

# ----------------- ADMIN CRUD & FEEDS -----------------

def update_incident(incident_id: int, data: Dict[str, Any]) -> bool:
    """Update editable incident fields."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        fields = []
        params = []
        allowed = ["title", "summary", "category", "incident_date", "location_name", "district", "state", "latitude", "longitude", "legal_status"]
        for key in allowed:
            if key in data:
                fields.append(f"{key} = ?")
                params.append(data[key])
        
        if not fields:
            return False
        
        fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(incident_id)
        cursor.execute(f"UPDATE incidents SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def delete_incident(incident_id: int) -> bool:
    """Delete an incident and unlink related sources."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE sources SET incident_id = NULL WHERE incident_id = ?", (incident_id,))
        cursor.execute("DELETE FROM incidents WHERE id = ?", (incident_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def get_all_sources(search: Optional[str] = None, limit: int = 150) -> List[Dict[str, Any]]:
    """Fetch raw news sources with optional search query."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        query = """
            SELECT s.*, i.title as incident_title 
            FROM sources s
            LEFT JOIN incidents i ON s.incident_id = i.id
            WHERE 1=1
        """
        params = []
        if search:
            query += " AND (s.headline LIKE ? OR s.publisher LIKE ? OR s.raw_snippet LIKE ?)"
            term = f"%{search}%"
            params.extend([term, term, term])
        query += " ORDER BY s.published_at DESC, s.id DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def add_custom_source(headline: str, publisher: str, url: str, published_at: str, raw_snippet: str, incident_id: Optional[int] = None) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO sources (headline, publisher, url, published_at, raw_snippet, processed, incident_id)
            VALUES (?, ?, ?, ?, ?, 1, ?)
        """, (headline, publisher, url, published_at, raw_snippet, incident_id))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def delete_source(source_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def get_all_feeds() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM feeds ORDER BY id ASC")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def create_feed(name: str, query: str, region: str = "India", category_hint: str = "All", feed_type: Optional[str] = None, constraints: str = "gbv_strict") -> int:
    if not feed_type:
        feed_type = "rss_url" if (query.startswith("http://") or query.startswith("https://")) else "google_news"
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO feeds (name, query, region, category_hint, feed_type, constraints, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (name, query, region, category_hint, feed_type, constraints or "gbv_strict"))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def update_feed(feed_id: int, name: str, query: str, region: str = "India", category_hint: str = "All", feed_type: Optional[str] = None, constraints: str = "gbv_strict") -> bool:
    if not feed_type:
        feed_type = "rss_url" if (query.startswith("http://") or query.startswith("https://")) else "google_news"
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE feeds 
            SET name = ?, query = ?, region = ?, category_hint = ?, feed_type = ?, constraints = ?
            WHERE id = ?
        """, (name, query, region, category_hint, feed_type, constraints or "gbv_strict", feed_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def toggle_feed(feed_id: int, is_active: bool) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE feeds SET is_active = ? WHERE id = ?", (1 if is_active else 0, feed_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def delete_feed(feed_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def purge_non_india_records() -> Dict[str, int]:
    """Purge foreign news items (Kentucky, Lindsay Clancy, US/UK stories) from database."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        foreign_terms = [
            "%kentucky%", "%clancy%", "%massachusetts%", "%mayfield%", "%jay-z%",
            "%florida%", "%texas%", "%chicago%", "%ohio%", "%michigan%",
            "%alabama%", "%california%", "%sheriff%", "%county pd%", "%colorado%",
            "%houston%", "%tennessee%"
        ]

        deleted_incidents = 0
        deleted_sources = 0

        # Purge matching sources
        for term in foreign_terms:
            cursor.execute("DELETE FROM sources WHERE headline LIKE ? OR raw_snippet LIKE ?", (term, term))
            deleted_sources += cursor.rowcount

        # Purge matching incidents
        for term in foreign_terms:
            cursor.execute("DELETE FROM incidents WHERE title LIKE ? OR summary LIKE ?", (term, term))
            deleted_incidents += cursor.rowcount

        # Also purge incidents with no state, no location, and non-Indian indicators
        cursor.execute("""
            DELETE FROM incidents 
            WHERE state IS NULL 
              AND location_name IS NULL 
              AND id NOT IN (SELECT DISTINCT incident_id FROM sources WHERE incident_id IS NOT NULL)
        """)
        deleted_incidents += cursor.rowcount

        conn.commit()
        return {"deleted_incidents": deleted_incidents, "deleted_sources": deleted_sources}
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at", DB_PATH)

