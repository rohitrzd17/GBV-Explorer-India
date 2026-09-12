"""
Execution script: Extract structured GBV incident information from news reports.
Supports hybrid extraction: Gemini Flash API (when GEMINI_API_KEY is configured) 
or local regex/NLP heuristics fallback.
"""

import os
import sys
import re
import json
from datetime import datetime
from typing import Dict, Any, Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

from execution.database import (
    get_unprocessed_sources,
    mark_source_processed,
    create_incident
)
from execution.geocode_locations import geocode_location, load_gazetteer

# Regex patterns for Category Classification
CATEGORY_PATTERNS = [
    (r"\b(pocso|minor girl|child abuse|underage|schoolgirl)\b", "POCSO / Minor"),
    (r"\b(acid attack|threw acid|vitriolage)\b", "Acid Attack"),
    (r"\b(dowry|dowry death|harassed for dowry|demanding dowry)\b", "Dowry Violence"),
    (r"\b(domestic violence|husband beat|in-laws tortured|marital rape|intimate partner)\b", "Domestic Violence"),
    (r"\b(gang rape|gangraped|rape|raped|sexual assault|sexually assaulted)\b", "Sexual Assault"),
    (r"\b(molest|molestation|eve teasing|stalking|harass|inappropriate touch|lewd)\b", "Harassment & Stalking"),
]

LEGAL_STATUS_PATTERNS = [
    (r"\b(arrested|held|nabbed|behind bars|remanded)\b", "Arrest Made"),
    (r"\b(fir registered|booked under|case lodged|fir filed|chargesheet)\b", "FIR Registered"),
    (r"\b(absconding|on the run|fled|manhunt)\b", "Accused Absconding"),
    (r"\b(convicted|sentenced|life imprisonment|death penalty)\b", "Convicted"),
    (r"\b(acquitted|granted bail|out on bail)\b", "Bail / Acquittal"),
]

# Common Indian state abbreviations (must match exact word boundaries)
STATE_ABBREVIATIONS = [
    (r"\bUP\b", "Uttar Pradesh"),
    (r"\bU\.P\.\b", "Uttar Pradesh"),
    (r"\bMP\b", "Madhya Pradesh"),
    (r"\bM\.P\.\b", "Madhya Pradesh"),
    (r"\bWB\b", "West Bengal"),
    (r"\bW\.B\.\b", "West Bengal"),
    (r"\bTN\b", "Tamil Nadu"),
    (r"\bT\.N\.\b", "Tamil Nadu"),
    (r"\bAP\b", "Andhra Pradesh"),
    (r"\bA\.P\.\b", "Andhra Pradesh"),
    (r"\bJ&K\b", "Jammu and Kashmir"),
    (r"\bHP\b", "Himachal Pradesh"),
    (r"\bH\.P\.\b", "Himachal Pradesh"),
]

def rule_based_extract(headline: str, snippet: str, published_at: str) -> Dict[str, Any]:
    text = f"{headline}. {snippet}"
    text_lower = text.lower()

    # 1. Determine category
    category = "Other GBV"
    for pattern, cat_name in CATEGORY_PATTERNS:
        if re.search(pattern, text_lower):
            category = cat_name
            break

    # 2. Determine legal status
    legal_status = "Under Investigation"
    for pattern, status in LEGAL_STATUS_PATTERNS:
        if re.search(pattern, text_lower):
            legal_status = status
            break

    # 3. Determine location
    gaz = load_gazetteer()
    places = gaz.get("places", {})
    states = gaz.get("states", {})

    found_place = None
    found_state = None

    # A. Check dateline prefix (e.g., "MUMBAI: ", "NEW DELHI:", "LUCKNOW -")
    dateline_match = re.match(r"^([A-Z\s]{3,20})\s*[:\-\—]", headline.strip())
    if dateline_match:
        dateline_city = dateline_match.group(1).strip().lower()
        if dateline_city in places:
            found_place = dateline_city.title()
            found_state = places[dateline_city].get("state")

    # B. Prioritize prepositional phrases: "in <place>", "near <place>", "from <place>", "<place> police"
    for p in sorted(places.keys(), key=len, reverse=True):
        prep_pattern = r"\b(in|at|near|from|around)\s+" + re.escape(p) + r"\b"
        if re.search(prep_pattern, text_lower):
            found_place = p.title()
            found_state = places[p].get("state")
            break
        police_pattern = r"\b" + re.escape(p) + r"\s+police\b"
        if re.search(police_pattern, text_lower):
            found_place = p.title()
            found_state = places[p].get("state")
            break

    # C. General place search if not found
    if not found_place:
        for p in sorted(places.keys(), key=len, reverse=True):
            pattern = r"\b" + re.escape(p) + r"\b"
            if re.search(pattern, text_lower):
                found_place = p.title()
                found_state = places[p].get("state")
                break

    # D. Check state abbreviations in original case (e.g. "UP teenager dies...")
    if not found_state:
        for abbr_pattern, full_state in STATE_ABBREVIATIONS:
            if re.search(abbr_pattern, headline) or re.search(abbr_pattern, snippet):
                found_state = full_state
                if not found_place:
                    found_place = full_state
                break

    # E. If no place, check full state names
    if not found_state:
        for s in states.keys():
            pattern = r"\b" + re.escape(s.lower()) + r"\b"
            if re.search(pattern, text_lower):
                found_state = s
                if not found_place:
                    found_place = s
                break

    # Extract clean title (remove publisher suffix like ' - Times of India')
    title = headline.split(" - ")[0].strip() if " - " in headline else headline

    return {
        "title": title[:200],
        "summary": snippet[:500] if snippet else title,
        "category": category,
        "incident_date": published_at[:10] if published_at else datetime.utcnow().strftime("%Y-%m-%d"),
        "location_name": found_place,
        "district": found_place,
        "state": found_state,
        "legal_status": legal_status
    }

def gemini_extract(headline: str, snippet: str, published_at: str) -> Optional[Dict[str, Any]]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or api_key.startswith("your_"):
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        prompt = f"""
        Extract structured GBV incident information from this Indian news report.
        Strictly prioritize the INCIDENT location (where the crime occurred), NOT the media bureau or supreme court location.
        Categories must be one of: ["Sexual Assault", "Domestic Violence", "Dowry Violence", "Harassment & Stalking", "Acid Attack", "POCSO / Minor", "Other GBV"].
        Legal statuses: ["FIR Registered", "Arrest Made", "Under Investigation", "Accused Absconding", "Convicted", "Bail / Acquittal"].

        Headline: {headline}
        Summary: {snippet}
        Published Date: {published_at}

        Return a JSON object with:
        {{
          "is_gbv": true/false,
          "title": "Concise factual incident title (anonymizing victim)",
          "category": "Category name",
          "incident_location": "Town/City or Village",
          "district": "District name if known",
          "state": "Indian State",
          "legal_status": "Legal status",
          "incident_date": "YYYY-MM-DD"
        }}
        """

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        data = json.loads(response.text)
        if not data.get("is_gbv", True):
            return None

        return {
            "title": data.get("title", headline)[:200],
            "summary": snippet[:500] if snippet else headline,
            "category": data.get("category", "Other GBV"),
            "incident_date": data.get("incident_date", published_at[:10] if published_at else None),
            "location_name": data.get("incident_location") or data.get("district"),
            "district": data.get("district"),
            "state": data.get("state"),
            "legal_status": data.get("legal_status", "Under Investigation")
        }
    except Exception as e:
        print(f"[Warn] Gemini extraction failed: {e}, falling back to rule-based.")
        return None

FOREIGN_EXCLUSIONS = [
    r"\bkentucky\b", r"\bclancy\b", r"\bmassachusetts\b", r"\bmayfield\b",
    r"\bjay-z\b", r"\bflorida\b", r"\btexas\b", r"\bohio\b", r"\bmichigan\b",
    r"\balabama\b", r"\bcalifornia\b", r"\bsheriff\b", r"\bcounty police\b",
    r"\bcolorado\b", r"\bhouston\b", r"\btennessee\b", r"\bchicago\b"
]

INDIAN_INDICATORS = [
    r"\bindia\b", r"\bindian\b", r"\bpocso\b", r"\bfir\b", r"\bipc\b",
    r"\bbns\b", r"\bhigh court\b", r"\bsupreme court\b", r"\bpolice station\b",
    r"\bmahila thana\b", r"\bthana\b", r"\bpanchayat\b", r"\blakh\b", r"\bcrore\b"
]

def is_india_relevant(headline: str, snippet: str, publisher: str, state: Optional[str] = None) -> bool:
    text = f"{headline} {snippet} {publisher}".lower()
    for pat in FOREIGN_EXCLUSIONS:
        if re.search(pat, text):
            if not state:
                return False
    if state:
        return True
    for pat in INDIAN_INDICATORS:
        if re.search(pat, text):
            return True
    indian_media = ["times of india", "ndtv", "hindustan times", "the hindu", "indian express", "deccan herald", "ani", "pti", "india today", "the print", "the wire", "tribune"]
    for m in indian_media:
        if m in text:
            return True
    return False

def process_unprocessed_articles(batch_size: int = 50) -> int:
    unprocessed = get_unprocessed_sources(limit=batch_size)
    if not unprocessed:
        print("[Extract] No unprocessed articles found.")
        return 0

    print(f"[Extract] Processing {len(unprocessed)} articles...")
    created_count = 0

    for article in unprocessed:
        headline = article["headline"]
        snippet = article.get("raw_snippet", "")
        published_at = article.get("published_at", "")
        publisher = article.get("publisher", "")

        # Try Gemini if key exists, else rule-based
        extracted = gemini_extract(headline, snippet, published_at)
        if not extracted:
            extracted = rule_based_extract(headline, snippet, published_at)

        # Geocode the location
        geo = geocode_location(extracted.get("location_name") or extracted.get("district"), extracted.get("state"))
        extracted["latitude"] = geo.get("lat")
        extracted["longitude"] = geo.get("lon")
        if geo.get("state"):
            extracted["state"] = geo["state"]
        if geo.get("district"):
            extracted["district"] = geo["district"]

        # Strict India Relevance Gatekeeper: Discard foreign reports
        if not is_india_relevant(headline, snippet, publisher, extracted.get("state")):
            print(f"[Gatekeeper] Discarded non-India report: {headline[:60]}...")
            mark_source_processed(article["id"], incident_id=None)
            continue

        # Create incident
        inc_id = create_incident(extracted)
        mark_source_processed(article["id"], incident_id=inc_id)
        created_count += 1

    print(f"[Extract] Successfully created {created_count} incidents from raw articles.")
    return created_count

if __name__ == "__main__":
    process_unprocessed_articles(100)
