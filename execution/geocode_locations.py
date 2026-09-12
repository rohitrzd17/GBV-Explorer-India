"""
Execution script: Geocode extracted locations to coordinates across India.
Uses data/india_gazetteer.json as primary fast local gazetteer with SQLite persistent cache.
"""

import os
import sys
import json
import re
import time
from typing import Optional, Tuple, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import requests
from execution.database import get_connection

GAZETTEER_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "india_gazetteer.json")

_gazetteer = None

def load_gazetteer() -> Dict[str, Any]:
    global _gazetteer
    if _gazetteer is None:
        if os.path.exists(GAZETTEER_PATH):
            with open(GAZETTEER_PATH, "r", encoding="utf-8") as f:
                _gazetteer = json.load(f)
        else:
            _gazetteer = {"states": {}, "places": {}}
    return _gazetteer

def lookup_cache(query: str) -> Optional[Tuple[float, float, str, str]]:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT latitude, longitude, state, district FROM geocode_cache WHERE query = ?", (query.lower().strip(),))
        row = cursor.fetchone()
        if row and row["latitude"] is not None:
            return (row["latitude"], row["longitude"], row["state"], row["district"])
        return None
    finally:
        conn.close()

def save_cache(query: str, lat: Optional[float], lon: Optional[float], state: Optional[str], district: Optional[str]):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO geocode_cache (query, latitude, longitude, state, district)
            VALUES (?, ?, ?, ?, ?)
        """, (query.lower().strip(), lat, lon, state, district))
        conn.commit()
    finally:
        conn.close()

def geocode_location(location_name: Optional[str], state_hint: Optional[str] = None, use_nominatim: bool = False) -> Dict[str, Any]:
    """
    Resolve location string to (latitude, longitude, state, district).
    Returns dict: {"lat": float, "lon": float, "state": str, "district": str, "resolved": bool}
    """
    if not location_name and not state_hint:
        return {"lat": None, "lon": None, "state": None, "district": None, "resolved": False}

    loc_clean = (location_name or "").strip().lower()
    state_clean = (state_hint or "").strip().lower()

    # Clean punctuation and prefixes
    loc_clean = re.sub(r'^(in|at|near|from|around)\s+', '', loc_clean).strip()
    loc_clean = re.sub(r'[\'\".,;:\-]', '', loc_clean).strip()

    search_key = f"{loc_clean}, {state_clean}".strip(", ")
    
    # 1. Check SQLite geocode cache
    cached = lookup_cache(search_key)
    if cached:
        return {"lat": cached[0], "lon": cached[1], "state": cached[2], "district": cached[3], "resolved": True}

    gaz = load_gazetteer()
    places = gaz.get("places", {})
    states = gaz.get("states", {})

    # 2. Check local places dictionary
    if loc_clean in places:
        match = places[loc_clean]
        state = match.get("state")
        lat = match.get("lat")
        lon = match.get("lon")
        save_cache(search_key, lat, lon, state, loc_clean.title())
        return {"lat": lat, "lon": lon, "state": state, "district": loc_clean.title(), "resolved": True}

    # 3. Fuzzy sub-phrase check in places dictionary
    for place_name, coords in places.items():
        if (len(place_name) > 3 and place_name in loc_clean) or (len(loc_clean) > 4 and loc_clean in place_name):
            state = coords.get("state")
            save_cache(search_key, coords["lat"], coords["lon"], state, place_name.title())
            return {"lat": coords["lat"], "lon": coords["lon"], "state": state, "district": place_name.title(), "resolved": True}

    # 4. Check state fallback
    for state_name, coords in states.items():
        if state_name.lower() == loc_clean or state_name.lower() == state_clean:
            save_cache(search_key, coords["lat"], coords["lon"], state_name, None)
            return {"lat": coords["lat"], "lon": coords["lon"], "state": state_name, "district": None, "resolved": True}

    # 5. External fallback to Nominatim (only when explicitly requested)
    if use_nominatim and loc_clean:
        try:
            url = f"https://nominatim.openstreetmap.org/search?q={loc_clean}+India&format=json&limit=1"
            headers = {"User-Agent": "GBV-Explorer-Research-Tool/1.0"}
            resp = requests.get(url, headers=headers, timeout=4)
            if resp.status_code == 200:
                results = resp.json()
                if results and len(results) > 0:
                    lat = float(results[0]["lat"])
                    lon = float(results[0]["lon"])
                    save_cache(search_key, lat, lon, state_hint, loc_clean.title())
                    return {"lat": lat, "lon": lon, "state": state_hint, "district": loc_clean.title(), "resolved": True}
        except Exception:
            pass

    save_cache(search_key, None, None, state_hint, None)
    return {"lat": None, "lon": None, "state": state_hint, "district": None, "resolved": False}

if __name__ == "__main__":
    test_queries = ["Hathras", "Pune", "near kolkata", "bengaluru", "Uttar Pradesh", "NonexistentXYZ"]
    for q in test_queries:
        res = geocode_location(q)
        print(f"Query: '{q}' -> {res}")
