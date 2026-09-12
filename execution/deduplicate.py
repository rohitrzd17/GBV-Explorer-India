"""
Execution script: Deduplicate and cluster news reports covering the same incident.
Groups articles by date window (±3 days), location, and category, linking them to a master incident.
"""

import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from execution.database import get_connection

def parse_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except Exception:
        return None

def deduplicate_incidents() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM incidents ORDER BY incident_date ASC, id ASC")
        incidents = [dict(row) for row in cursor.fetchall()]

        merged_count = 0
        processed_ids = set()

        for i in range(len(incidents)):
            inc_a = incidents[i]
            id_a = inc_a["id"]
            if id_a in processed_ids:
                continue

            date_a = parse_date(inc_a.get("incident_date"))
            loc_a = (inc_a.get("district") or inc_a.get("location_name") or "").lower().strip()
            cat_a = inc_a.get("category")

            if not loc_a or not date_a:
                continue

            cluster_id = inc_a.get("cluster_id") or f"cluster_{id_a}"

            for j in range(i + 1, len(incidents)):
                inc_b = incidents[j]
                id_b = inc_b["id"]
                if id_b in processed_ids:
                    continue

                date_b = parse_date(inc_b.get("incident_date"))
                loc_b = (inc_b.get("district") or inc_b.get("location_name") or "").lower().strip()
                cat_b = inc_b.get("category")

                if not loc_b or not date_b:
                    continue

                # Check date difference
                days_diff = abs((date_a - date_b).days)
                if days_diff > 3:
                    continue

                # Check location & category match
                is_same_loc = (loc_a == loc_b) or (loc_a in loc_b) or (loc_b in loc_a)
                is_same_cat = (cat_a == cat_b)

                if is_same_loc and is_same_cat:
                    # Merge B into A
                    cursor.execute("UPDATE sources SET incident_id = ? WHERE incident_id = ?", (id_a, id_b))
                    cursor.execute("UPDATE incidents SET cluster_id = ? WHERE id = ?", (cluster_id, id_a))
                    # Remove duplicate incident B
                    cursor.execute("DELETE FROM incidents WHERE id = ?", (id_b,))
                    processed_ids.add(id_b)
                    merged_count += 1

            processed_ids.add(id_a)

        conn.commit()
        print(f"[Deduplicate] Merged {merged_count} duplicate incident records.")
        return merged_count
    finally:
        conn.close()

if __name__ == "__main__":
    deduplicate_incidents()
