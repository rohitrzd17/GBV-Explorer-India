# GBV Explorer India 🇮🇳

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![Leaflet](https://img.shields.io/badge/Leaflet-1.9.4-199900.svg)](https://leafletjs.com)
[![OpenStreetMap](https://img.shields.io/badge/OpenStreetMap-100%25%20OpenSource-7EBC6F.svg)](https://www.openstreetmap.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A spatial intelligence and open-source monitoring web tool that tracks, extracts, geolocates, and visualizes news reports of **Gender-Based Violence (GBV)** across all 28 States and 8 Union Territories of India.

🔗 **Live Web Demo**: [https://rohitrzd17.github.io/GBV-Explorer-India/](https://rohitrzd17.github.io/GBV-Explorer-India/)

---

## 🌟 Key Features

- 🗺️ **Interactive Open-Source Map**:
  - Built with **Leaflet.js** and **OpenStreetMap (OSM)** tiles.
  - **Zero API Key Requirement**: No Google Maps API key, no Mapbox tokens, and no credit card required.
  - Category-coded pins with dynamic clustering for high-density metropolitan areas.
  - Flying animations to pinpointed incident districts and towns.

- 🔍 **Multi-Faceted Filtering & Search**:
  - **GBV Categories**: Sexual Assault / Rape, POCSO / Minor, Domestic Violence, Dowry Violence, Harassment & Stalking, Acid Attack, and Other Offenses.
  - **Geographic Scope**: Filter dynamically by Indian State / Union Territory.
  - **Temporal Windows**: Last 7 Days, Last 30 Days, or Complete Dataset.
  - **Instant Search**: Search by town, district, accused, or case details.

- 📥 **1-Click CSV Export**:
  - Download currently filtered or total incident records directly in your browser.
  - Includes **UTF-8 Byte Order Mark (`\uFEFF`)** and quote formatting for seamless opening in Excel, Google Sheets, or LibreOffice.
  - Also available via programmatic endpoint: `GET /api/incidents/export/csv`.

- 🛡️ **India Relevance Gatekeeper & Deduplication**:
  - Pre-indexed India Gazetteer ([`data/india_gazetteer.json`](data/india_gazetteer.json)) containing 329+ Indian cities and districts.
  - Distinguishes **incident location** from **media bureau/courtroom dateline**.
  - Strict negative filters discard foreign crime stories (e.g. US/UK court trials).
  - Cluster-based deduplication groups duplicate reporting across multiple outlets into unified incident clusters.

- ⚙️ **Protected Database Management Portal**:
  - Password-protected with client- and server-side **SHA-256 cryptographic hashing** (zero plaintext passphrases in source code).
  - **Incidents Manager**: Edit titles, categories, dates, legal status, and coordinates with automatic re-geocoding.
  - **Add Incident Form**: Manually submit verified incidents to plot instantly on the map.
  - **RSS Feeds Manager**: Add custom regional queries or toggles for state-level news feeds.
  - **Sources & Purge**: Inspect raw news articles and perform 1-click database sanitation.

- 🌐 **Dual-Mode Hosting (Local + GitHub Pages)**:
  - **Local Mode**: FastAPI server (`http://localhost:8000`) with dynamic SQLite database operations and background news scrapers.
  - **Static Mode**: Bundles pre-exported datasets in [`docs/data/`](docs/data/) for 1-click, serverless hosting on **GitHub Pages**.

---

## 🏛️ 3-Layer Architecture

In accordance with [`AGENTS.md`](AGENTS.md), this project strictly separates concerns into three layers:

```
GBV Explorer/
├── directives/                    # Layer 1: SOPs and Specifications
│   ├── gbv_ingest_pipeline.md     # SOP for RSS querying, NLP extraction, geocoding & deduplication
│   └── webtool_service.md         # SOP for FastAPI web server & admin capabilities
├── execution/                     # Layer 3: Deterministic Python Execution Scripts
│   ├── database.py                # SQLite persistence (incidents, sources, feeds, geocodes)
│   ├── fetch_news.py              # Multi-feed Google News RSS ingester with India context
│   ├── extract_incidents.py       # Hybrid extractor (NLP heuristics + Gemini Flash fallback)
│   ├── geocode_locations.py       # India Gazetteer resolver with persistent caching
│   ├── deduplicate.py             # Multi-source article clustering
│   ├── export_static.py           # Static JSON & CSV generator for GitHub Pages
│   ├── build_full_gazetteer.py    # India district & coordinates compiler
│   └── serve_webtool.py           # FastAPI backend server
├── data/                          # Persistent storage & reference tables
│   ├── india_gazetteer.json       # 329+ Indian cities, districts, and state coordinates
│   └── incidents.db               # SQLite database
├── docs/                          # Static distribution bundle for GitHub Pages
│   ├── index.html                 # Frontend dashboard
│   ├── style.css                  # Responsive dark-theme styling
│   ├── app.js                     # Interactive mapping, client filters & WebCrypto auth
│   └── data/                      # Bundled static JSON datasets & CSV export
├── web/                           # Source frontend files (mirrored to docs/)
├── requirements.txt               # Python package dependencies
├── .env.example                   # Environment configuration template
└── README.md
```

---

## 🚀 Quick Start (Local Setup)

### Prerequisites
- Python 3.10+ installed
- Git

### 1. Clone & Set Up Environment
```bash
git clone https://github.com/rohitrzd17/GBV-Explorer-India.git
cd GBV-Explorer-India

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment (Optional)
```bash
cp .env.example .env
```
*(Optional: Add `GEMINI_API_KEY` to `.env` if you wish to use LLM-assisted deep extraction alongside the default rule-based parser).*

### 3. Launch Web Server
```bash
python execution/serve_webtool.py
```
Open your browser at **[http://localhost:8000](http://localhost:8000)**.

---

## 🔄 Running the Ingestion Pipeline

To fetch the latest reports from configured RSS feeds, extract incident locations, and deduplicate coverage:

```bash
# Run complete pipeline in sequence
python execution/fetch_news.py
python execution/extract_incidents.py
python execution/deduplicate.py

# Export latest database state for GitHub Pages
python execution/export_static.py
```

---

## 🌐 Deploying to GitHub Pages (1-Click)

1. Push your repository to GitHub:
   ```bash
   git add .
   git commit -m "Deploy GBV Explorer India"
   git push -u origin master
   ```
2. In your GitHub repository, open **Settings** > **Pages**.
3. Under **Build and deployment > Branch**:
   - Branch: **`master`** (or `main`)
   - Folder: **/docs**
4. Click **Save**. Within 1–2 minutes, your web tool is live at `https://<YOUR_USERNAME>.github.io/GBV-Explorer-India/`.

---

## ⚖️ Ethical & Privacy Safeguards

- **Strict Identity Protection**: In compliance with Section 228A of the Indian Penal Code (IPC) and Section 74 of the Juvenile Justice (JJ) Act, this platform **never stores or publishes identifying names of victims**.
- **Public Record Verification**: All entries are sourced from verified news media publishers with direct citation links for factual cross-referencing.
- **Academic & Public Interest**: Developed as a public-interest research tool to assist journalists, researchers, policy analysts, and civil society organizations in spatial trend analysis.

---

## 📄 License

This project is released under the [MIT License](LICENSE).
