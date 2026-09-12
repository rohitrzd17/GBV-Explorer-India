"""
Script to:
1. Purge foreign/international articles that should not be in the India GBV tracker.
2. Attribute Supreme Court & High Court legal/policy cases to their respective court seats.
3. Re-geocode remaining domestic reports.
"""

import sqlite3
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from execution.database import get_connection, DB_PATH
from execution.geocode_locations import geocode_location

FOREIGN_PATTERNS = [
    r"\b(britain|uk|england|wales|scotland|london|nottingham|portsmouth|kent|essex|manchester|birmingham)\b",
    r"\b(us|usa|united states|texas|florida|california|ohio|massachusetts|kentucky|georgia|colorado|new york|jpmorgan|syracuse|mountain home)\b",
    r"\b(australia|sydney|melbourne|brisbane|canberra|perth|adelaide|victoria|grace tame|ralph carr)\b",
    r"\b(france|paris|pelicot|spain|ceuta|madrid|barcelona|italy|germany|netherlands)\b",
    r"\b(pakistan|lahore|karachi|islamabad|bangladesh|dhaka|nepal|kathmandu|sri lanka)\b",
    r"\b(canada|toronto|vancouver|ottawa)\b",
    r"\b(romania|andrew tate|israel|gaza|hamas)\b",
    r"\b(rape crisis england|nnedv|nl times)\b"
]

COURT_MAPPINGS = [
    (r"\b(supreme court|sc asks|cji|constitutional validity of marital rape|union's stand|plea in sc)\b", "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
    (r"\b(bombay high court|bombay hc)\b", "Mumbai", "Mumbai", "Maharashtra", 18.9220, 72.8347),
    (r"\b(allahabad high court|allahabad hc)\b", "Prayagraj", "Prayagraj", "Uttar Pradesh", 25.4358, 81.8463),
    (r"\b(calcutta high court|calcutta hc)\b", "Kolkata", "Kolkata", "West Bengal", 22.5697, 88.3697),
    (r"\b(delhi high court|delhi hc)\b", "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
    (r"\b(madras high court|madras hc)\b", "Chennai", "Chennai", "Tamil Nadu", 13.0827, 80.2707),
    (r"\b(karnataka high court|karnataka hc)\b", "Bengaluru", "Bengaluru", "Karnataka", 12.9716, 77.5946),
    (r"\b(kerala high court|kerala hc)\b", "Kochi", "Ernakulam", "Kerala", 9.9312, 76.2673),
    (r"\b(patna high court|patna hc)\b", "Patna", "Patna", "Bihar", 25.5941, 85.1376),
    (r"\b(punjab and haryana high court|punjab & haryana hc)\b", "Chandigarh", "Chandigarh", "Chandigarh", 30.7333, 76.7794),
    (r"\b(telangana high court|telangana hc)\b", "Hyderabad", "Hyderabad", "Telangana", 17.3850, 78.4867),
    (r"\b(high court|hc grants|hc rejects|hc asks|hc quashes)\b", "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
]

def clean_and_remedy():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT i.id, i.title, i.summary, s.headline, s.publisher, s.url, s.raw_snippet
        FROM incidents i
        LEFT JOIN sources s ON s.incident_id = i.id
    """)
    incidents = cursor.fetchall()
    print(f"Total incidents before cleanup: {len(incidents)}")

    deleted_foreign = 0
    attributed_courts = 0
    regeocoded_count = 0

    for inc in incidents:
        inc_id = inc["id"]
        text = f"{inc['title']} {inc['summary'] or ''} {inc['headline'] or ''} {inc['publisher'] or ''} {inc['url'] or ''} {inc['raw_snippet'] or ''}".lower()

        # 1. Identify foreign
        is_foreign = False
        for pat in FOREIGN_PATTERNS:
            if re.search(pat, text):
                is_foreign = True
                break

        if is_foreign:
            cursor.execute("DELETE FROM sources WHERE incident_id = ?", (inc_id,))
            cursor.execute("DELETE FROM incidents WHERE id = ?", (inc_id,))
            deleted_foreign += 1
            continue

        # 2. Check judicial/court mapping if missing coordinates
        cursor.execute("SELECT latitude, longitude, location_name FROM incidents WHERE id = ?", (inc_id,))
        row = cursor.fetchone()
        if not row or (row["latitude"] is None):
            court_found = False
            for pat, loc_name, dist, state, lat, lon in COURT_MAPPINGS:
                if re.search(pat, text):
                    cursor.execute("""
                        UPDATE incidents 
                        SET location_name = ?, district = ?, state = ?, latitude = ?, longitude = ?, category = 'Other GBV'
                        WHERE id = ?
                    """, (loc_name, dist, state, lat, lon, inc_id))
                    attributed_courts += 1
                    court_found = True
                    break

            if not court_found:
                # 3. Check if any Indian state or city is mentioned
                from execution.extract_incidents import load_gazetteer
                gaz = load_gazetteer()
                places = gaz.get("places", {})
                states = gaz.get("states", {})

                found_p = None
                for p, info in places.items():
                    if len(p) >= 4 and re.search(r"\b" + re.escape(p) + r"\b", text):
                        cursor.execute("""
                            UPDATE incidents 
                            SET location_name = ?, district = ?, state = ?, latitude = ?, longitude = ?
                            WHERE id = ?
                        """, (p.title(), p.title(), info.get("state"), info["lat"], info["lon"], inc_id))
                        regeocoded_count += 1
                        found_p = p
                        break
                
                if not found_p:
                    for s, info in states.items():
                        if re.search(r"\b" + re.escape(s.lower()) + r"\b", text):
                            cursor.execute("""
                                UPDATE incidents 
                                SET location_name = ?, district = ?, state = ?, latitude = ?, longitude = ?
                                WHERE id = ?
                            """, (s, s, s, info["lat"], info["lon"], inc_id))
                            regeocoded_count += 1
                            break

    conn.commit()

    # Get updated stats
    cursor.execute("SELECT COUNT(*) as total FROM incidents")
    new_total = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) as geocoded FROM incidents WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
    new_geocoded = cursor.fetchone()["geocoded"]
    conn.close()

    print(f"\nCleanup & Remediation Complete:")
    print(f"- Deleted {deleted_foreign} foreign/non-Indian incidents")
    print(f"- Attributed {attributed_courts} judicial/legal cases to court seats")
    print(f"- Re-geocoded {regeocoded_count} domestic incidents")
    print(f"- Updated Total Incidents: {new_total}")
    print(f"- Updated Geocoded Incidents: {new_geocoded} ({new_geocoded/new_total*100:.1f}%)")

if __name__ == "__main__":
    clean_and_remedy()
