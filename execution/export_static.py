"""
Execution script: Export SQLite database into static JSON and CSV files.
Enables running the GBV Explorer entirely on static hosts like GitHub Pages.
"""

import os
import sys
import json
import csv

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from execution.database import get_all_incidents, get_statistics, get_all_feeds

import shutil

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs")
WEB_DATA_DIR = os.path.join(WEB_DIR, "data")
ROOT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

def export_static_data():
    os.makedirs(WEB_DATA_DIR, exist_ok=True)
    os.makedirs(ROOT_DATA_DIR, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)

    # 1. Fetch all incidents
    incidents = get_all_incidents(only_geocoded=False)
    stats = get_statistics()
    feeds = get_all_feeds()

    # 2. Write JSON files for web consumption
    for dest_dir in [WEB_DATA_DIR, ROOT_DATA_DIR]:
        with open(os.path.join(dest_dir, "incidents.json"), "w", encoding="utf-8") as f:
            json.dump({"count": len(incidents), "incidents": incidents}, f, indent=2)

        with open(os.path.join(dest_dir, "stats.json"), "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)

        with open(os.path.join(dest_dir, "feeds.json"), "w", encoding="utf-8") as f:
            json.dump({"count": len(feeds), "feeds": feeds}, f, indent=2)

    # 3. Write CSV file
    csv_file = os.path.join(WEB_DATA_DIR, "incidents.csv")
    csv_columns = [
        "id", "title", "category", "incident_date", "oldest_article_date", "latest_article_date",
        "location_name", "district", "state", "latitude", "longitude", "legal_status",
        "source_count", "publishers", "primary_url", "summary"
    ]

    with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=csv_columns, extrasaction="ignore")
        writer.writeheader()
        for inc in incidents:
            writer.writerow(inc)

    # 4. Sync web directory into docs/ for GitHub Pages (docs folder method)
    for item in os.listdir(WEB_DIR):
        s = os.path.join(WEB_DIR, item)
        d = os.path.join(DOCS_DIR, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)

    print(f"[Export] Successfully exported {len(incidents)} incidents to JSON and CSV.")
    print(f"         Web files synced to 'docs/' for 1-click GitHub Pages deployment.")

if __name__ == "__main__":
    export_static_data()
