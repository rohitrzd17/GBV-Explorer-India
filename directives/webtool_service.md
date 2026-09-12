# Directive: GBV Explorer Web Tool Service

## 1. Goal
Run and maintain the web service hosting the interactive map, REST API endpoints, analytics charts, and filter controls for exploring GBV news reports across India.

## 2. Inputs
- SQLite database: `data/incidents.db`
- Static web assets in `web/` (`index.html`, `style.css`, `app.js`)
- Host & Port configuration from `.env` (default: `PORT=8000`, `HOST=127.0.0.1`)

## 3. Tools & Scripts
- `execution/serve_webtool.py` - FastAPI server with REST API (`/api/incidents`, `/api/stats`, `/api/pipeline/refresh`) and static file hosting.

## 4. Outputs & Deliverables
- Interactive Web App accessible at `http://localhost:8000`
- REST endpoints:
  - `GET /api/incidents`: Filterable list of geocoded incidents (by state, category, date range, search keyword).
  - `GET /api/stats`: Aggregate counts by state, category breakdown, time distribution.
  - `POST /api/pipeline/refresh`: Trigger a live pipeline run to pull latest news.
  - `GET/POST/PUT/DELETE /api/admin/incidents`: CRUD operations for incident metadata, categories, and coordinates.
  - `GET/POST/DELETE /api/admin/sources`: Add, delete, and inspect raw news reports.
  - `GET/POST/PUT/DELETE /api/admin/feeds`: Configure custom regional RSS feeds and queries.
  - `POST /api/admin/purge-foreign`: Purge non-India reports from database.

## 5. Execution Steps
1. Ensure `data/incidents.db` is populated or run the pipeline if empty.
2. Launch server: `python execution/serve_webtool.py`
3. Access UI in web browser at `http://localhost:8000`.
4. Click "Database Admin" in header to manage incidents, configure RSS feeds, or prune data.

## 6. Edge Cases & Learnings
- **Zero Coordinates**: Incidents whose location could not be pinpointed with confidence are kept with null coordinates and displayed in an "Unmapped / State-level Reports" sidebar filter rather than placed at false zero (0,0) coordinates.
- **Admin Re-geocoding**: Updating an incident's location or district in the admin portal automatically recalculates latitude and longitude via `geocode_location` if coordinates are not manually specified.
- **Header Responsiveness**: Metric cards and navigation buttons use fluid wrapping and breakpoint rules to remain within bounds on mobile and tablet viewport widths.
