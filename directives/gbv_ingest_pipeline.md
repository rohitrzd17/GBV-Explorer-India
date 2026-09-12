# Directive: GBV News Ingestion & Incident Mapping Pipeline

## 1. Goal
Collect news reports on Gender-Based Violence (GBV) incidents across Indian states and union territories, extract incident location and metadata, geocode the coordinates, deduplicate coverage, and store structured records for visualization on the map.

## 2. Inputs
- Google News RSS query endpoints (no auth required).
- Keywords: Broad GBV terminology (`rape`, `assault`, `molestation`, `harassment`, `domestic violence`, `dowry`, `acid attack`, `POCSO`, `eve teasing`).
- Geographic scope: All 28 Indian States and 8 Union Territories.
- Optional: `GEMINI_API_KEY` in `.env` for deep LLM structured extraction (with automatic fallback to regex/gazetteer extraction if not provided).

## 3. Tools & Scripts
- `execution/fetch_news.py` - Fetches articles from Google News RSS feeds partitioned by region and GBV keywords, saves raw feeds to `.tmp/raw_news/`.
- `execution/extract_incidents.py` - Parses news snippets/articles to identify incident location (distinguishing incident spot vs bureau/court), category, date, and status.
- `execution/geocode_locations.py` - Resolves extracted district/city to latitude and longitude using `data/india_gazetteer.json` and cached Nominatim lookups.
- `execution/deduplicate.py` - Clusters multiple news reports covering the same incident by time window and location.
- `execution/database.py` - Manages SQLite persistence in `data/incidents.db`.

## 4. Outputs & Deliverables
- Intermediates: `.tmp/raw_news/*.json`
- Database: `data/incidents.db` (tables: `incidents`, `sources`, `geocodes`)
- Deliverable: Queryable SQLite database powering the interactive map API.

## 5. Execution Steps
1. Run `python execution/fetch_news.py` to ingest the latest news items.
2. Run `python execution/extract_incidents.py` to extract entities and categories from newly fetched articles.
3. Run `python execution/geocode_locations.py` to attach coordinates to any unmapped locations.
4. Run `python execution/deduplicate.py` to link articles describing the same incident.
5. All pipeline steps can also be run in sequence via `python execution/fetch_news.py --run-all`.

## 6. Edge Cases & Learnings
- **Reporting Location vs Incident Location**: News articles frequently start with the dateline city (e.g., *"NEW DELHI:"*) even when the crime occurred in a remote district (e.g. *"in a village in Hathras"*). The extraction script must prioritize incident location prepositional phrases (*in [Location]*, *at [Location]*, *resident of [Location]*).
- **Sensitive Identity Safeguards**: In accordance with Section 228A of IPC / Section 74 of JJ Act, victim names must never be stored or displayed. The extractor strips or ignores identifying names of victims.
- **Geocoding Limits**: Direct OSM Nominatim calls are rate-limited to 1 req/sec. All known districts are pre-indexed in `data/india_gazetteer.json` to eliminate external network requests for 99%+ of queries.
