"""
FastAPI Server for GBV Explorer Web Tool.
Serves interactive map frontend and REST API for incident querying, statistics, and full Admin CRUD.
"""

import os
import sys
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException, BackgroundTasks, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

from execution.database import (
    init_db,
    get_all_incidents,
    get_incident_sources,
    get_statistics,
    create_incident,
    update_incident,
    delete_incident,
    get_all_sources,
    add_custom_source,
    delete_source,
    get_all_feeds,
    create_feed,
    toggle_feed,
    delete_feed,
    purge_non_india_records
)
from execution.geocode_locations import geocode_location
from execution.fetch_news import run_fetch, run_fetch_for_feed
from execution.extract_incidents import process_unprocessed_articles
from execution.deduplicate import deduplicate_incidents

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="GBV Explorer - India News Map & Admin Backend", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")

def run_pipeline_sync():
    print("[Pipeline] Running full ingestion and extraction pipeline...")
    run_fetch(sample_mode=False, max_regions=12)
    process_unprocessed_articles(batch_size=150)
    deduplicate_incidents()
    print("[Pipeline] Completed.")

# ----------------- PUBLIC API -----------------

@app.get("/api/incidents")
def list_incidents(
    category: Optional[str] = Query(None, description="Filter by category"),
    state: Optional[str] = Query(None, description="Filter by state"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    only_geocoded: bool = Query(True, description="Only return incidents with valid lat/lon")
):
    incidents = get_all_incidents(
        category=category,
        state=state,
        start_date=start_date,
        end_date=end_date,
        only_geocoded=only_geocoded
    )
    return {"count": len(incidents), "incidents": incidents}

@app.get("/api/incidents/{incident_id}/sources")
def incident_sources(incident_id: int):
    sources = get_incident_sources(incident_id)
    return {"incident_id": incident_id, "count": len(sources), "sources": sources}

@app.get("/api/stats")
def stats():
    return get_statistics()

@app.post("/api/pipeline/refresh")
def trigger_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_pipeline_sync)
    return {"status": "accepted", "message": "News ingestion and incident extraction pipeline started in background."}

@app.get("/api/incidents/export/csv")
def export_incidents_csv(
    category: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None)
):
    import io, csv
    incidents = get_all_incidents(
        category=category,
        state=state,
        start_date=start_date,
        end_date=end_date,
        only_geocoded=False
    )
    output = io.StringIO()
    output.write("\ufeff")  # UTF-8 BOM
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Title", "Category", "Date", "Location", "District",
        "State", "Latitude", "Longitude", "Legal Status",
        "Source Count", "Publishers", "Primary URL", "Summary"
    ])
    for inc in incidents:
        writer.writerow([
            inc.get("id"), inc.get("title"), inc.get("category"),
            inc.get("incident_date"), inc.get("location_name"),
            inc.get("district"), inc.get("state"), inc.get("latitude"),
            inc.get("longitude"), inc.get("legal_status"),
            inc.get("source_count"), inc.get("publishers"),
            inc.get("primary_url"), inc.get("summary")
        ])
    from fastapi.responses import Response
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=gbv_incidents_report.csv"}
    )

class AuthPayload(BaseModel):
    password_hash: Optional[str] = None
    password: Optional[str] = None

@app.post("/api/admin/auth")
def admin_auth(payload: AuthPayload):
    import hashlib
    expected_hash = os.environ.get("ADMIN_PASSWORD_HASH", "ed8c9cfe75c84b881f159ca0a98cdc37b6f93422b6888c3ef29d5acd43fba239")
    given_hash = payload.password_hash
    if not given_hash and payload.password:
        given_hash = hashlib.sha256(payload.password.encode("utf-8")).hexdigest()

    if given_hash and given_hash.lower() == expected_hash.lower():
        return {"authenticated": True, "token": "session_admin_granted"}
    raise HTTPException(status_code=401, detail="Invalid admin credentials.")

# ----------------- ADMIN API -----------------

class IncidentCreatePayload(BaseModel):
    title: str
    summary: Optional[str] = ""
    category: str = "Other GBV"
    incident_date: Optional[str] = None
    location_name: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    legal_status: Optional[str] = "Under Investigation"
    source_url: Optional[str] = None
    publisher: Optional[str] = "Manual Entry"

class IncidentUpdatePayload(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    incident_date: Optional[str] = None
    location_name: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    legal_status: Optional[str] = None

class SourceCreatePayload(BaseModel):
    headline: str
    publisher: str
    url: str
    published_at: Optional[str] = None
    raw_snippet: Optional[str] = ""
    incident_id: Optional[int] = None

class FeedCreatePayload(BaseModel):
    name: str
    query: str
    region: str = "India"
    category_hint: str = "All"

@app.get("/api/admin/incidents")
def admin_get_incidents(
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    state: Optional[str] = Query(None)
):
    all_incs = get_all_incidents(category=category, state=state, only_geocoded=False)
    if search:
        s = search.lower()
        all_incs = [i for i in all_incs if s in (i.get("title") or "").lower() or s in (i.get("location_name") or "").lower() or s in (i.get("district") or "").lower()]
    return {"count": len(all_incs), "incidents": all_incs}

@app.post("/api/admin/incidents")
def admin_create_incident(payload: IncidentCreatePayload):
    data = payload.dict()
    # Auto geocode if coordinates not specified
    if not data.get("latitude") or not data.get("longitude"):
        geo = geocode_location(data.get("location_name") or data.get("district"), data.get("state"))
        if geo.get("lat") and geo.get("lon"):
            data["latitude"] = geo["lat"]
            data["longitude"] = geo["lon"]
            if not data.get("state") and geo.get("state"):
                data["state"] = geo["state"]

    inc_id = create_incident(data)
    if payload.source_url:
        add_custom_source(
            headline=payload.title,
            publisher=payload.publisher or "Manual Entry",
            url=payload.source_url,
            published_at=payload.incident_date,
            raw_snippet=payload.summary or "",
            incident_id=inc_id
        )
    return {"id": inc_id, "message": "Incident created successfully"}

@app.put("/api/admin/incidents/{incident_id}")
def admin_update_incident(incident_id: int, payload: IncidentUpdatePayload):
    data = {k: v for k, v in payload.dict().items() if v is not None}
    
    # Auto re-geocode if location/district/state changed and coords weren't manually overridden
    if ("location_name" in data or "district" in data or "state" in data) and ("latitude" not in data):
        loc = data.get("location_name") or data.get("district")
        st = data.get("state")
        geo = geocode_location(loc, st)
        if geo.get("lat"):
            data["latitude"] = geo["lat"]
            data["longitude"] = geo["lon"]
            if not data.get("state") and geo.get("state"):
                data["state"] = geo["state"]

    success = update_incident(incident_id, data)
    if not success:
        raise HTTPException(status_code=404, detail="Incident not found or no changes made")
    return {"success": True, "message": "Incident updated successfully"}

@app.delete("/api/admin/incidents/{incident_id}")
def admin_delete_incident(incident_id: int):
    success = delete_incident(incident_id)
    if not success:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"success": True, "message": "Incident deleted successfully"}

@app.get("/api/admin/sources")
def admin_get_sources(search: Optional[str] = Query(None), limit: int = Query(100)):
    sources = get_all_sources(search=search, limit=limit)
    return {"count": len(sources), "sources": sources}

@app.post("/api/admin/sources")
def admin_add_source(payload: SourceCreatePayload):
    source_id = add_custom_source(
        headline=payload.headline,
        publisher=payload.publisher,
        url=payload.url,
        published_at=payload.published_at,
        raw_snippet=payload.raw_snippet or "",
        incident_id=payload.incident_id
    )
    return {"id": source_id, "message": "Source added successfully"}

@app.delete("/api/admin/sources/{source_id}")
def admin_delete_source(source_id: int):
    success = delete_source(source_id)
    if not success:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"success": True, "message": "Source removed successfully"}

@app.get("/api/admin/feeds")
def admin_list_feeds():
    feeds = get_all_feeds()
    return {"count": len(feeds), "feeds": feeds}

@app.post("/api/admin/feeds")
def admin_create_feed(payload: FeedCreatePayload):
    feed_id = create_feed(
        name=payload.name,
        query=payload.query,
        region=payload.region,
        category_hint=payload.category_hint
    )
    return {"id": feed_id, "message": "Feed created successfully"}

@app.put("/api/admin/feeds/{feed_id}/toggle")
def admin_toggle_feed(feed_id: int, is_active: bool = Body(..., embed=True)):
    success = toggle_feed(feed_id, is_active)
    if not success:
        raise HTTPException(status_code=404, detail="Feed not found")
    return {"success": True, "is_active": is_active}

@app.delete("/api/admin/feeds/{feed_id}")
def admin_delete_feed(feed_id: int):
    success = delete_feed(feed_id)
    if not success:
        raise HTTPException(status_code=404, detail="Feed not found")
    return {"success": True, "message": "Feed deleted successfully"}

@app.post("/api/admin/feeds/{feed_id}/fetch")
def admin_fetch_feed(feed_id: int, background_tasks: BackgroundTasks):
    def fetch_and_process():
        run_fetch_for_feed(feed_id)
        process_unprocessed_articles(batch_size=100)
        deduplicate_incidents()
    background_tasks.add_task(fetch_and_process)
    return {"status": "accepted", "message": f"Fetch started for feed #{feed_id}."}

@app.post("/api/admin/purge-foreign")
def admin_purge_foreign():
    res = purge_non_india_records()
    return {"success": True, "result": res}

# Mount frontend static files
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend_root")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"Starting GBV Explorer Web Server on http://{host}:{port}")
    uvicorn.run("serve_webtool:app", host=host, port=port, reload=True)
